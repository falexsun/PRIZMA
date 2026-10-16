from pathlib import Path

import aiosqlite
from pymax import Client
from pymax.auth import AuthFlow
from pymax.config import ExtraConfig, generate_device_id
from pymax.session.models import SessionInfo

from app.services.max_user_agent import MAX_APP_VERSION


class _SettingsAuthFlow(AuthFlow):
    async def authenticate(self, app):
        raise RuntimeError("MAX session is missing. Sign in to MAX in settings.")


class ContentTrackerMaxClient(Client):
    """PyMax 2.x adapter for staged UI authentication and raw post statistics."""

    def __init__(self, phone: str, work_dir: str, auth_config: ExtraConfig | None = None):
        super().__init__(
            phone=phone,
            work_dir=work_dir,
            app_version=MAX_APP_VERSION,
            auth_flow=_SettingsAuthFlow(),
            extra_config=auth_config or ExtraConfig(
                reconnect=False,
                relogin=False,
                request_timeout=20,
                device_id=generate_device_id(),
                telemetry=False,
            ),
        )

    async def connect(self) -> None:
        await self._ensure_runtime()
        try:
            await self._migrate_legacy_session()
            # Reuse this runtime: Client.connect() would create another App
            # before opening the transport and leave the migration store open.
            await self._app.start()
            if not self._app.started:
                raise RuntimeError("MAX login did not complete")
            await self._app.dispatcher.emit_start(self)
        except BaseException:
            await self.close()
            raise

    async def _migrate_legacy_session(self) -> None:
        store = self._app.store
        if await store.load_session() is not None:
            return
        db_path = Path(self.work_dir) / self.session_name
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT name FROM sqlite_master WHERE name = 'auth'") as cursor:
                if await cursor.fetchone() is None:
                    return
            async with db.execute("SELECT token, device_id FROM auth WHERE token IS NOT NULL AND token != '' LIMIT 1") as cursor:
                legacy = await cursor.fetchone()
        if legacy:
            await store.save_session(SessionInfo(token=legacy[0], device_id=legacy[1], phone=self.phone))

    async def connect_auth(self) -> None:
        # The UI supplies code/password in later HTTP requests, outside App.start().
        await self._ensure_runtime()
        await self._app.connection.open()
        self._app.handshake_response = await self._app.handshake(self._config.device.device_id)
        self.extra_config.user_agent = self._config.device.user_agent

    async def request_code(self, phone: str) -> str:
        return (await self._app.api.auth.request_code(phone)).token

    async def send_code(self, code: str, token: str) -> dict:
        result = await self._app.api.auth.send_code(token, code)
        return result.model_dump(by_alias=True)

    async def check_password(self, track_id: str, password: str) -> dict:
        result = await self._app.api.auth.check_password(track_id, password)
        return result.model_dump(by_alias=True)

    async def save_token(self, token: str) -> None:
        store = self._app.store
        # SessionStore.load_session selects the first row, so replace old tokens.
        previous = await store.load_session()
        await store.save_session(SessionInfo(
            token=token,
            device_id=self._config.device.device_id,
            phone=self.phone,
            mt_instance_id=self._config.device.mt_instance_id,
            user_agent=self._config.device.user_agent,
        ))
        if previous is not None and previous.token != token:
            await store.delete_session(previous.token)

    async def request(self, opcode: int, payload: dict) -> dict:
        response = await self._app.invoke(opcode, payload)
        return {"payload": response.payload or {}}
