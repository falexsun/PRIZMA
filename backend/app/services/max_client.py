import asyncio
import contextlib
from typing import Any

import lz4.block
import msgpack
from pymax import SocketMaxClient


class ContentTrackerMaxClient(SocketMaxClient):
    """SocketMaxClient with support for initial-sync packets larger than 100 KB.

    maxapi-python 1.2.5 uses a fixed 99,999-byte LZ4 output buffer, so accounts
    with a larger initial sync lose the LOGIN response and time out.
    """

    def _unpack_packet(self, data: bytes) -> dict[str, Any] | None:
        version = int.from_bytes(data[0:1], "big")
        command = int.from_bytes(data[1:3], "big")
        sequence = int.from_bytes(data[3:4], "big")
        opcode = int.from_bytes(data[4:6], "big")
        packed_length = int.from_bytes(data[6:10], "big", signed=False)
        compression = packed_length >> 24
        payload_length = packed_length & 0xFFFFFF
        payload_bytes = data[10 : 10 + payload_length]

        payload = None
        if payload_bytes:
            if compression:
                try:
                    payload_bytes = lz4.block.decompress(
                        payload_bytes,
                        uncompressed_size=16 * 1024 * 1024,
                    )
                except lz4.block.LZ4BlockError:
                    return None
            payload = msgpack.unpackb(payload_bytes, raw=False, strict_map_key=False)

        return {
            "ver": version,
            "cmd": command,
            "seq": sequence,
            "opcode": opcode,
            "payload": payload,
        }

    async def _sync(self, user_agent=None) -> None:
        """Run initial sync without hanging on invalid MAX login tokens."""
        pymax_globals = SocketMaxClient._sync.__globals__
        UserAgentPayload = pymax_globals["UserAgentPayload"]
        SyncPayload = pymax_globals["SyncPayload"]
        Opcode = pymax_globals["Opcode"]
        MixinsUtils = pymax_globals["MixinsUtils"]
        ChatType = pymax_globals["ChatType"]
        Dialog = pymax_globals["Dialog"]
        Chat = pymax_globals["Chat"]
        Channel = pymax_globals["Channel"]
        User = pymax_globals["User"]
        Me = pymax_globals["Me"]

        self.logger.info("Starting initial sync")
        if user_agent is None:
            user_agent = self.headers or UserAgentPayload()

        payload = SyncPayload(
            interactive=True,
            token=self._token,
            chats_sync=0,
            contacts_sync=0,
            presence_sync=0,
            drafts_sync=0,
            chats_count=40,
            user_agent=user_agent,
        ).model_dump(by_alias=True)
        try:
            data = await self._send_and_wait(opcode=Opcode.LOGIN, payload=payload)
            raw_payload = data.get("payload", {})
            if raw_payload.get("error"):
                MixinsUtils.handle_error(data)

            for raw_chat in raw_payload.get("chats", []):
                try:
                    if raw_chat.get("type") == ChatType.DIALOG.value:
                        self.dialogs.append(Dialog.from_dict(raw_chat))
                    elif raw_chat.get("type") == ChatType.CHAT.value:
                        self.chats.append(Chat.from_dict(raw_chat))
                    elif raw_chat.get("type") == ChatType.CHANNEL.value:
                        self.channels.append(Channel.from_dict(raw_chat))
                except Exception:
                    self.logger.exception("Error parsing chat entry")

            for raw_user in raw_payload.get("contacts", []):
                try:
                    user = User.from_dict(raw_user)
                    if user:
                        self.contacts.append(user)
                except Exception:
                    self.logger.exception("Error parsing contact entry")

            if raw_payload.get("profile", {}).get("contact"):
                self.me = Me.from_dict(raw_payload.get("profile", {}).get("contact", {}))

            self.logger.info(
                "Sync completed: dialogs=%d chats=%d channels=%d",
                len(self.dialogs),
                len(self.chats),
                len(self.channels),
            )
        except Exception:
            self.logger.exception("Sync failed")
            await self.close()
            raise

    async def close(self) -> None:
        """Close native socket resources left open by maxapi-python 1.2.x."""
        self.is_connected = False
        with contextlib.suppress(Exception):
            self._stop_event.set()
        with contextlib.suppress(Exception):
            if self._socket is not None:
                self._socket.shutdown(2)
        with contextlib.suppress(Exception):
            if self._socket is not None:
                self._socket.close()
        with contextlib.suppress(Exception):
            if self._ws is not None:
                await asyncio.wait_for(self._ws.close(), timeout=2)

        tasks = [task for task in (self._recv_task, self._outgoing_task) if task is not None]
        for task in tasks:
            task.cancel()

        self._socket = None
        self._ws = None
