"""Shared XHS SDK errors that callers can handle without parsing messages."""


class XhsLoginBlockedError(RuntimeError):
    """The platform rejected the login request; stop automatic retries."""

    http_status = 471
    error_code = "xhs_login_blocked"

    def __init__(self, operation: str):
        super().__init__(
            f"小红书拒绝了本次{operation}请求（HTTP 471），已停止自动重试。"
            "请先在小红书官方网页或 App 确认可正常登录，并完成平台提示的验证，再重新绑定。"
        )

    def public_details(self) -> dict:
        return {
            "message": str(self),
            "error_code": self.error_code,
            "upstream_status": self.http_status,
            "retryable": False,
        }
