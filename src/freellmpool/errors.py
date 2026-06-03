"""Exception hierarchy for freellmpool."""

from __future__ import annotations


class FreeLLMPoolError(Exception):
    """Base class for all freellmpool errors."""


# Deprecated pre-rename alias; kept so old `except BuffetError` imports don't break.
# Will be removed in a future release — catch FreeLLMPoolError instead.
BuffetError = FreeLLMPoolError


class NoProvidersConfigured(FreeLLMPoolError):
    """Raised when no provider has a usable API key in the environment."""


class AllProvidersExhausted(FreeLLMPoolError):
    """Raised when every candidate provider failed or is over budget.

    The ``attempts`` attribute holds a list of ``(target, reason)`` tuples
    describing what was tried and why each one was skipped or failed.
    """

    def __init__(self, attempts: list[tuple[str, str]]):
        self.attempts = attempts
        detail = "; ".join(f"{name}: {reason}" for name, reason in attempts) or "no candidates"
        super().__init__(f"all providers exhausted ({detail})")


class ProviderHTTPError(FreeLLMPoolError):
    """A provider returned a non-success HTTP status.

    ``status`` is the HTTP status code; ``retryable`` indicates whether the
    router should move on to another provider (True) or give up (False).
    """

    def __init__(self, status: int, message: str, *, retryable: bool):
        self.status = status
        self.retryable = retryable
        super().__init__(f"HTTP {status}: {message}")
