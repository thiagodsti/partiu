"""Domain-level error for the trips feature.

Like auth, trips has many distinct (message, status code) pairs and nothing
downstream needs to distinguish them by type — one parametrized exception instead
of a dozen near-identical subclasses.
"""


class TripError(Exception):
    def __init__(self, message: str, status_code: int):
        self.status_code = status_code
        super().__init__(message)
