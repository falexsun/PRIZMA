from pymax.payloads import UserAgentPayload


MAX_APP_VERSION = "26.25.0"
MAX_BUILD_NUMBER = 6790


def make_max_user_agent() -> UserAgentPayload:
    return UserAgentPayload(
        device_type="DESKTOP",
        app_version=MAX_APP_VERSION,
        build_number=MAX_BUILD_NUMBER,
    )
