"""对外错误仅包含可公开的信息，禁止直接拼接第三方异常或请求 URL。"""


class ProviderError(RuntimeError):
    def __init__(self, service: str, code: str, message: str, *, retryable: bool = False):
        self.service, self.code, self.message, self.retryable = service, code, message, retryable
        super().__init__(f"{service}：{message}")
