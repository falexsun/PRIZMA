"""Helper to ensure httpx supports socks5 proxies.

httpx requires httpx[socks] extra to support socks5:// proxies.
"""


def ensure_socks_support() -> bool:
    """Check if socks5 support is available in httpx."""
    try:
        import socksio  # noqa: F401
        return True
    except ImportError:
        return False


def get_httpx_proxy_note() -> str:
    """Return a note about httpx socks5 support."""
    if ensure_socks_support():
        return "SOCKS5 proxy support is available."
    return (
        "SOCKS5 proxy support is not installed. "
        "Install with: pip install httpx[socks]. "
        "Only http:// proxies will work."
    )
