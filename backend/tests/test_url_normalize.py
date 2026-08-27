import pytest

from app.models.enums import Platform
from app.services.url_normalize import UnsupportedUrlError, normalize_url


def test_vk_ru_normalizes_to_vk_ru():
    normalized, platform = normalize_url("https://vk.ru/wall-123_456?utm_source=test")
    assert normalized == "https://vk.ru/wall-123_456"
    assert platform == Platform.vk


def test_vk_com_normalizes_to_vk_ru():
    normalized, platform = normalize_url("https://vk.com/wall-123_456?utm_source=test")
    assert normalized == "https://vk.ru/wall-123_456"
    assert platform == Platform.vk


def test_strips_utm_params():
    normalized, _ = normalize_url("https://www.youtube.com/watch?v=abc123&utm_campaign=x")
    assert "utm_campaign" not in normalized
    assert "v=abc123" in normalized


def test_trailing_slash_removed():
    normalized, _ = normalize_url("https://t.me/somechannel/42/")
    assert normalized == "https://t.me/somechannel/42"


def test_unsupported_platform_raises():
    with pytest.raises(UnsupportedUrlError):
        normalize_url("https://example.com/post/1")


def test_max_ru_is_recognized():
    normalized, platform = normalize_url("https://max.ru/rayonamz/AZ-CuWydUDo")
    assert normalized == "https://max.ru/rayonamz/AZ-CuWydUDo"
    assert platform == Platform.max_ru


def test_tiktok_short_link_keeps_its_own_host():
    """vt./vm. are TikTok's short-link redirect domains - collapsing them into
    bare tiktok.com produces a path that 404s instead of redirecting."""
    normalized, platform = normalize_url("https://vt.tiktok.com/ZSQp3df2V/")
    assert normalized == "https://vt.tiktok.com/ZSQp3df2V"
    assert platform == Platform.tiktok


def test_tiktok_vm_short_link_keeps_its_own_host():
    normalized, _ = normalize_url("https://vm.tiktok.com/ZSAbCdEfG/")
    assert normalized == "https://vm.tiktok.com/ZSAbCdEfG"


def test_tiktok_www_still_collapses_to_bare_domain():
    normalized, _ = normalize_url("https://www.tiktok.com/@user/video/123")
    assert normalized == "https://tiktok.com/@user/video/123"


def test_ok_ru_variants_normalize():
    for host in ("ok.ru", "www.ok.ru", "m.ok.ru", "web.ok.ru"):
        normalized, platform = normalize_url(f"https://{host}/video/239713520360")
        assert normalized == "https://ok.ru/video/239713520360"
        assert platform == Platform.ok


def test_vk_query_param_wall_id():
    """VK links like /name?w=wall-XXX_YYY should normalize to /wall-XXX_YYY."""
    normalized, platform = normalize_url("https://vk.com/yuzh_poleznyi?w=wall-203288413_4917")
    assert normalized == "https://vk.ru/wall-203288413_4917"
    assert platform == Platform.vk


def test_vk_query_param_video_id():
    """VK links like /name?z=video-XXX_YYY should normalize to /video-XXX_YYY."""
    normalized, platform = normalize_url("https://vk.com/club123?z=video-123456_789")
    assert normalized == "https://vk.ru/video-123456_789"
    assert platform == Platform.vk


def test_vkvideo_ru_direct_video():
    normalized, platform = normalize_url("https://vkvideo.ru/video-123456_789")
    assert normalized == "https://vkvideo.ru/video-123456_789"
    assert platform == Platform.vk


def test_vkvideo_ru_with_username():
    normalized, platform = normalize_url("https://vkvideo.ru/@username/video-123456_789")
    assert normalized == "https://vkvideo.ru/video-123456_789"
    assert platform == Platform.vk


def test_vkvideo_ru_www():
    normalized, platform = normalize_url("https://www.vkvideo.ru/video-123456_789")
    assert normalized == "https://vkvideo.ru/video-123456_789"
    assert platform == Platform.vk
