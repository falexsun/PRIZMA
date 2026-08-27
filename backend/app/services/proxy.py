import re

_HOSTISH = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _is_host_port(s: str) -> bool:
    """Вернуть True, если строка похожа на host:port с цифровым портом."""
    if not s:
        return False
    if ":" not in s:
        # host без порта — допустимо, но для proxy-URL обычно нужен порт.
        return bool(_HOSTISH.match(s))
    host, _, port = s.rpartition(":")
    if not host or not port:
        return False
    if not port.isdigit():
        return False
    port_num = int(port)
    return 1 <= port_num <= 65535


def normalize_proxy(proxy: str | None) -> str | None:
    """Привести прокси к URL-виду, понятному HTTP/SOCKS5 клиентам.

    Поддерживаемые форматы:
      - http://user:pass@host:port
      - socks5://user:pass@host:port
      - host:port@user:pass
      - user:pass@host:port
      - host:port (без авторизации)
    """
    if not proxy:
        return None

    proxy = proxy.strip()
    if not proxy:
        return None

    if "://" in proxy:
        return proxy

    if "@" not in proxy:
        return f"http://{proxy}"

    left, right = proxy.rsplit("@", 1)
    left_is_host_port = _is_host_port(left)
    right_is_host_port = _is_host_port(right)

    if left_is_host_port and not right_is_host_port:
        host_port, credentials = left, right
    elif right_is_host_port and not left_is_host_port:
        credentials, host_port = left, right
    elif left_is_host_port and right_is_host_port:
        # Оба похожи на host:port — неоднозначно. Берём левую часть как host:port
        # (формат proxy-продавцов: host:port@user:pass).
        host_port, credentials = left, right
    else:
        # Ни одна часть не похожа на host:port — по умолчанию host:port@user:pass.
        host_port, credentials = left, right

    if ":" in credentials:
        user, _, password = credentials.rpartition(":")
        auth = f"{user}:{password}"
    else:
        auth = credentials

    return f"http://{auth}@{host_port}"
