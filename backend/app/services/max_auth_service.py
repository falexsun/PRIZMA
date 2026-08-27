import re
from pathlib import Path
from typing import Literal
from uuid import UUID

from app.core.config import settings

MaxAuthStage = Literal["idle", "code_required", "password_required", "authenticated", "error"]


class MaxAuthError(RuntimeError):
    pass


class MaxAuthManager:
    """MAX authentication through the native socket API (maxapi-python)."""

    def __init__(self) -> None:
        self._stage: MaxAuthStage = "idle"
        self._message = ""
        self._phone = ""
        self._temp_token: str | None = None
        self._device_id: str | None = None
        self._track_id: str | None = None

    @property
    def phone(self) -> str:
        return self._phone

    def status(self) -> dict[str, str]:
        return {"stage": self._stage, "message": self._message}

    async def session_status(self) -> dict[str, str | bool]:
        work_dir = self._work_dir()
        phone_path = work_dir / "phone.txt"
        session_db = work_dir / "session.db"
        if not phone_path.exists() or not session_db.exists():
            return {
                "configured": False,
                "valid": False,
                "message": "MAX session is missing. Sign in to MAX.",
            }

        client = None
        try:
            from pymax.payloads import UserAgentPayload
            from app.services.max_client import ContentTrackerMaxClient

            client = ContentTrackerMaxClient(
                phone=phone_path.read_text(encoding="utf-8").strip(),
                work_dir=str(work_dir),
                headers=UserAgentPayload(device_type="DESKTOP", app_version="25.12.13"),
                reconnect=False,
            )
            await client.connect()
            await client._sync(client.user_agent)
            return {
                "configured": True,
                "valid": True,
                "message": "MAX session is active.",
            }
        except Exception as exc:
            return {
                "configured": True,
                "valid": False,
                "message": f"MAX session is not working: {exc}",
            }
        finally:
            await self._close_client(client)

    async def start(self, phone: str, target_url: str = "https://max.ru/") -> dict[str, str]:
        del target_url  # Kept in the API contract for backwards compatibility.
        self._reset()
        self._phone = self._normalize_phone(phone)
        client = None
        try:
            client = self._make_client(self._phone)
            await client.connect()
            self._temp_token = await client.request_code(self._phone, language="ru")
            self._device_id = str(client._device_id)
            self._stage = "code_required"
            self._message = "Код отправлен. Введите код из SMS."
            return self.status()
        except Exception as exc:
            self._stage = "error"
            self._message = f"Не удалось отправить SMS через MAX API: {exc}"
            raise MaxAuthError(self._message) from exc
        finally:
            await self._close_client(client)

    async def submit_code(self, code: str) -> dict[str, str]:
        if not self._temp_token or not self._device_id or not self._phone:
            raise MaxAuthError("Сначала запросите SMS-код.")
        if not re.fullmatch(r"\d{4,8}", code.strip()):
            raise MaxAuthError("Код должен содержать от 4 до 8 цифр.")

        client = None
        try:
            client = self._make_client(self._phone, UUID(self._device_id))
            await client.connect()
            result = await client._send_code(code.strip(), self._temp_token)
            challenge = result.get("passwordChallenge") if isinstance(result, dict) else None
            if challenge and challenge.get("trackId"):
                self._track_id = challenge["trackId"]
                self._stage = "password_required"
                hint = challenge.get("hint")
                self._message = (
                    "SMS подтверждено. Введите пароль двухфакторной аутентификации."
                    + (f" Подсказка: {hint}" if hint else "")
                )
                return self.status()

            login_token = self._login_token(result)
            if not login_token:
                raise MaxAuthError("MAX не подтвердил SMS-код.")
            self._save_token(client, login_token)
            self._authenticated()
            return self.status()
        except MaxAuthError:
            raise
        except Exception as exc:
            raise MaxAuthError(f"Не удалось подтвердить SMS-код: {exc}") from exc
        finally:
            await self._close_client(client)

    async def submit_password(self, password: str) -> dict[str, str]:
        if not self._track_id or not self._device_id or not self._phone:
            raise MaxAuthError("Сначала подтвердите номер телефона и SMS-код.")
        if not password:
            raise MaxAuthError("Введите пароль двухфакторной аутентификации.")

        client = None
        try:
            from pymax import Opcode
            from pymax.payloads import CheckPasswordChallengePayload

            client = self._make_client(self._phone, UUID(self._device_id))
            await client.connect()
            payload = CheckPasswordChallengePayload(
                track_id=self._track_id,
                password=password,
            ).model_dump(by_alias=True)
            response = await client._send_and_wait(
                opcode=Opcode.AUTH_LOGIN_CHECK_PASSWORD,
                payload=payload,
            )
            result = response.get("payload", {}) if isinstance(response, dict) else {}
            if result.get("error"):
                raise MaxAuthError("MAX отклонил пароль двухфакторной аутентификации.")
            login_token = self._login_token(result)
            if not login_token:
                raise MaxAuthError("MAX не вернул токен после проверки пароля.")
            self._save_token(client, login_token)
            self._authenticated()
            return self.status()
        except MaxAuthError:
            raise
        except Exception as exc:
            raise MaxAuthError(f"Не удалось подтвердить пароль 2FA: {exc}") from exc
        finally:
            await self._close_client(client)

    async def cancel(self) -> dict[str, str]:
        self._reset()
        self._message = "Вход отменён."
        return self.status()

    def _make_client(self, phone: str, device_id: UUID | None = None):
        try:
            from pymax import SocketMaxClient
            from pymax.payloads import UserAgentPayload
        except ImportError as exc:
            raise MaxAuthError(
                "Библиотека MAX API не установлена. Пересоберите контейнеры api и worker."
            ) from exc

        return SocketMaxClient(
            phone=phone,
            work_dir=str(self._work_dir()),
            headers=UserAgentPayload(device_type="DESKTOP", app_version="25.12.13"),
            device_id=device_id,
            reconnect=False,
        )

    def _work_dir(self) -> Path:
        path = Path(settings.max_session_path)
        work_dir = path if not path.suffix else path.with_suffix("")
        work_dir.mkdir(parents=True, exist_ok=True)
        return work_dir

    def _save_token(self, client, token: str) -> None:
        client._database.update_auth_token(client._device_id, token)
        (self._work_dir() / "phone.txt").write_text(self._phone, encoding="utf-8")

    def _authenticated(self) -> None:
        self._stage = "authenticated"
        self._message = "MAX авторизован, токен сессии сохранён."
        self._temp_token = None
        self._track_id = None

    @staticmethod
    def _login_token(result: dict) -> str | None:
        return result.get("tokenAttrs", {}).get("LOGIN", {}).get("token")

    @staticmethod
    async def _close_client(client) -> None:
        if client is None:
            return
        try:
            await client.close()
        except Exception:
            try:
                await client.stop()
            except Exception:
                pass

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        digits = re.sub(r"\D", "", phone)
        if len(digits) == 11 and digits.startswith("8"):
            digits = "7" + digits[1:]
        if len(digits) < 10 or len(digits) > 15:
            raise MaxAuthError("Введите корректный номер телефона.")
        return f"+{digits}"

    def _reset(self) -> None:
        self._stage = "idle"
        self._message = ""
        self._phone = ""
        self._temp_token = None
        self._device_id = None
        self._track_id = None


max_auth_manager = MaxAuthManager()
