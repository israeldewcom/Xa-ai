import time
from dataclasses import dataclass

from app.core.exceptions import BackendError


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_seconds: int = 30
    _failures: int = 0
    _opened_at: float = 0.0

    @property
    def is_open(self) -> bool:
        if self._opened_at == 0:
            return False
        if time.monotonic() - self._opened_at >= self.recovery_seconds:
            self._opened_at = 0
            self._failures = 0
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = time.monotonic()

    def check(self) -> None:
        if self.is_open:
            raise BackendError("Circuit breaker is open.", code="CIRCUIT_OPEN")
