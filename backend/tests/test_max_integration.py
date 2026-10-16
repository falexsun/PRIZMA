import base64
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.parsers import max_ru
from app.services.max_auth_service import MaxAuthManager
from app.services.max_client import ContentTrackerMaxClient


@pytest.mark.asyncio
async def test_connect_reuses_migration_store_and_closes_it(tmp_path, monkeypatch):
    client = ContentTrackerMaxClient("+79990000000", str(tmp_path))
    async def start(app):
        app.started = True
    monkeypatch.setattr("pymax.app.App.start", start)
    prepare = AsyncMock(wraps=client._ensure_runtime)
    monkeypatch.setattr(client, "_ensure_runtime", prepare)
    try:
        await client.connect()
        prepare.assert_awaited_once()
        runtime = client._app
    finally:
        await client.close()
    assert runtime.store.conn is None


@pytest.mark.asyncio
async def test_sms_request_includes_current_app_fingerprint(tmp_path):
    client = ContentTrackerMaxClient("+79990000000", str(tmp_path))
    try:
        await client._ensure_runtime()
        client._app.handshake_response = SimpleNamespace(calls_seed=123456)
        client._app.invoke = AsyncMock(return_value=SimpleNamespace(payload={
            "token": "sms-token", "codeLength": 6, "requestMaxDuration": 60,
            "requestCountLeft": 3, "altActionDuration": 60,
        }))
        assert await client.request_code(client.phone) == "sms-token"
        payload = client._app.invoke.call_args.args[1]
        assert isinstance(payload["mode"], bytes)
        assert len(payload["mode"]) == 96
        assert payload["phone"] == client.phone
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_legacy_session_migration_and_token_replacement(tmp_path):
    with sqlite3.connect(tmp_path / "session.db") as db:
        db.execute("CREATE TABLE auth (token TEXT, device_id TEXT PRIMARY KEY)")
        db.execute("INSERT INTO auth VALUES (?, ?)", ("old-token", "old-device"))
    client = ContentTrackerMaxClient("+79990000000", str(tmp_path))
    try:
        await client._ensure_runtime()
        await client._migrate_legacy_session()
        session = await client._app.store.load_session()
        assert (session.token, session.device_id) == ("old-token", "old-device")
        await client.save_token("new-token")
        session = await client._app.store.load_session()
        assert session.token == "new-token"
        assert session.user_agent.app_version == "26.28.0"
        assert session.user_agent.device_type == "ANDROID"
        assert client._config.fingering.build_number == session.user_agent.build_number
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("two_factor", [False, True])
async def test_staged_login_preserves_device_and_saves_token(tmp_path, monkeypatch, two_factor):
    manager = MaxAuthManager()
    monkeypatch.setattr(manager, "_work_dir", lambda: tmp_path)
    config = SimpleNamespace(device_id="new-device")
    result = {"passwordChallenge": {"trackId": "track"}} if two_factor else {"tokenAttrs": {"LOGIN": {"token": "login-token"}}}
    client = SimpleNamespace(
        extra_config=config, connect_auth=AsyncMock(), close=AsyncMock(),
        request_code=AsyncMock(return_value="sms-token"),
        send_code=AsyncMock(return_value=result), save_token=AsyncMock(),
        check_password=AsyncMock(return_value={"tokenAttrs": {"LOGIN": {"token": "login-token"}}}),
    )
    factory = []
    def make_client(phone, device_id=None):
        factory.append(device_id)
        if device_id:
            assert manager._auth_config is config
        return client
    monkeypatch.setattr(manager, "_make_client", make_client)
    assert (await manager.start("+79990000000"))["stage"] == "code_required"
    assert (await manager.submit_code("123456"))["stage"] == ("password_required" if two_factor else "authenticated")
    if two_factor:
        assert (await manager.submit_password("test-password"))["stage"] == "authenticated"
        client.check_password.assert_awaited_once_with("track", "test-password")
    client.save_token.assert_awaited_once_with("login-token")
    client.send_code.assert_awaited_once_with("123456", "sms-token")
    assert factory[1:] == ["new-device"] * (len(factory) - 1)
    assert (tmp_path / "phone.txt").read_text() == "+79990000000"


@pytest.mark.asyncio
async def test_metrics_use_authenticated_history(tmp_path, monkeypatch):
    (tmp_path / "phone.txt").write_text("+79990000000")
    (tmp_path / "session.db").touch()
    monkeypatch.setattr(max_ru, "_pymax_work_dir", lambda: tmp_path)
    encoded = base64.urlsafe_b64encode((42).to_bytes(8, "big")).decode().rstrip("=")
    client = SimpleNamespace(connect=AsyncMock(), close=AsyncMock(), request=AsyncMock(side_effect=[
        {"payload": {"chat": {"id": 123}, "message": {"id": 42, "time": 1000}}},
        {"payload": {"messages": [{"id": 42, "stats": {"views": 987}, "reactionInfo": {"totalCount": 23}}]}},
    ]))
    monkeypatch.setattr("app.services.max_client.ContentTrackerMaxClient", lambda **kwargs: client)
    metrics = await max_ru._fetch_via_pymax(f"https://max.ru/channel/{encoded}")
    assert (metrics.views, metrics.likes) == (987, 23)
    client.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", ["FAIL_LOGIN_TOKEN", "FAIL_WRONG_PASSWORD [login.cred]"])
async def test_status_invalid_session_always_closes_client(tmp_path, monkeypatch, error):
    (tmp_path / "phone.txt").write_text("+79990000000")
    (tmp_path / "session.db").touch()
    manager = MaxAuthManager()
    monkeypatch.setattr(manager, "_work_dir", lambda: tmp_path)
    client = SimpleNamespace(connect=AsyncMock(side_effect=RuntimeError(error)), close=AsyncMock())
    monkeypatch.setattr("app.services.max_client.ContentTrackerMaxClient", lambda **kwargs: client)
    status = await manager.session_status()
    assert status["valid"] is False
    assert "expired" in status["message"]
    client.close.assert_awaited_once()
