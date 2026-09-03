class DomainError(Exception):
    def __init__(self, message: str, status_code: int = 400, code: str = "validation_error"):
        self.message = message
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class Unauthorized(DomainError):
    def __init__(self, message: str = "Autenticação necessária."):
        super().__init__(message, 401, "unauthorized")


class Forbidden(DomainError):
    def __init__(self, message: str = "Você não possui permissão para esta ação."):
        super().__init__(message, 403, "forbidden")
