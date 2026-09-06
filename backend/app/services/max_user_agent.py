from pymax.payloads import UserAgentPayload


MAX_WEB_APP_VERSION = "26.8.4"
MAX_WEB_BUILD_NUMBER = 0


def make_max_user_agent() -> UserAgentPayload:
    return UserAgentPayload(
        device_type="DESKTOP",
        app_version=MAX_WEB_APP_VERSION,
        build_number=MAX_WEB_BUILD_NUMBER,
    )
