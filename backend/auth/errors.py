"""Domain-level error for the auth feature.

Unlike other features, auth has a large number of distinct (message, status code)
pairs and nothing downstream ever needs to distinguish between them by type — they
all just become ``HTTPException(status_code, detail)``. So this is one parametrized
exception rather than a dozen near-identical subclasses.
"""


class AuthError(Exception):
    def __init__(self, message: str, status_code: int):
        self.status_code = status_code
        super().__init__(message)
