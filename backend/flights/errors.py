"""Domain-level error for the flights feature (same rationale as trips/auth:
many distinct (message, status code) pairs, nothing downstream needs the type)."""


class FlightError(Exception):
    def __init__(self, message: str, status_code: int):
        self.status_code = status_code
        super().__init__(message)
