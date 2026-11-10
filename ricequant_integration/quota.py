from __future__ import annotations

from dataclasses import dataclass


class QuotaPaused(RuntimeError):
    """Expected stop: there is not enough daily quota for another safe slice."""


@dataclass(frozen=True)
class QuotaSnapshot:
    bytes_limit: int
    bytes_used: int

    @property
    def bytes_remaining(self) -> int:
        if self.bytes_limit <= 0:
            return 2**63 - 1
        return max(0, self.bytes_limit - self.bytes_used)

    @property
    def unlimited(self) -> bool:
        return self.bytes_limit <= 0


class QuotaGuard:
    def __init__(self, min_reserve_bytes: int, estimate_multiplier: float = 1.5):
        self.min_reserve_bytes = min_reserve_bytes
        self.estimate_multiplier = estimate_multiplier

    def required_reserve(self, estimated_next_slice_bytes: int) -> int:
        return max(
            self.min_reserve_bytes,
            int(estimated_next_slice_bytes * self.estimate_multiplier),
        )

    def check(
        self,
        snapshot: QuotaSnapshot,
        estimated_next_slice_bytes: int,
        label: str = "next slice",
    ) -> None:
        if snapshot.unlimited:
            return
        required = self.required_reserve(estimated_next_slice_bytes)
        if snapshot.bytes_remaining <= required:
            raise QuotaPaused(
                f"daily quota paused before {label}: remaining={snapshot.bytes_remaining}, required_reserve={required}"
            )
