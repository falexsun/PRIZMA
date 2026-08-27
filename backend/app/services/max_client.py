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
