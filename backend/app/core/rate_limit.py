"""Rate limiting middleware for login and API protection."""
import time
from collections import defaultdict
from functools import wraps
from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

# In-memory rate limiter (per IP)
_login_attempts: dict[str, list[float]] = defaultdict(list)
_api_requests: dict[str, list[float]] = defaultdict(list)
_endpoint_attempts: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 900  # 15 minutes

API_MAX_REQUESTS = 100
API_WINDOW_SECONDS = 60


def _clean_old(entries: list[float], window: float) -> list[float]:
    now = time.time()
    return [t for t in entries if now - t < window]


def rate_limit(times: int = 10, seconds: int = 60):
    """Decorator for per-endpoint rate limiting."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                request = kwargs.get("request")

            if request:
                client_ip = request.client.host if request.client else "unknown"
                endpoint = request.url.path
                key = f"{client_ip}:{endpoint}"
                attempts = _clean_old(_endpoint_attempts[endpoint][key], seconds)
                _endpoint_attempts[endpoint][key] = attempts

                if len(attempts) >= times:
                    raise HTTPException(
                        status_code=429,
                        detail="Слишком много запросов. Попробуйте позже.",
                    )
                _endpoint_attempts[endpoint][key].append(time.time())

            return await func(*args, **kwargs)
        return wrapper
    return decorator


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path

        # Login rate limiting
        if path.startswith("/auth/login"):
            attempts = _clean_old(_login_attempts[client_ip], LOGIN_WINDOW_SECONDS)
            _login_attempts[client_ip] = attempts

            if len(attempts) >= LOGIN_MAX_ATTEMPTS:
                return Response(
                    content='{"detail":"Слишком много попыток входа. Попробуйте через 30 минут."}',
                    status_code=429,
                    media_type="application/json",
                )

            response = await call_next(request)

            if response.status_code == 401:
                _login_attempts[client_ip].append(time.time())

            return response

        # General API rate limiting
        requests = _clean_old(_api_requests[client_ip], API_WINDOW_SECONDS)
        _api_requests[client_ip] = requests

        if len(requests) >= API_MAX_REQUESTS:
            return Response(
                content='{"detail":"Слишком много запросов. Попробуйте позже."}',
                status_code=429,
                media_type="application/json",
            )

        _api_requests[client_ip].append(time.time())
        return await call_next(request)
