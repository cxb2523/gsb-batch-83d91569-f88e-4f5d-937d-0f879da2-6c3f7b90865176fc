from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class RetryStrategy:
    """Configuration for automatic retry behavior with exponential backoff and jitter.

    The RetryStrategy controls how the SDK handles transient API errors by automatically
    retrying failed requests with increasing delays between attempts. This helps handle
    temporary network issues, rate limits, and other transient failures gracefully.

    Attributes:
        max_retries: Maximum number of retry attempts (default: 5).
            The total number of attempts will be max_retries (first attempt is not counted).
            For example, max_retries=5 means up to 6 total attempts (1 initial + 5 retries).

        initial_delay: Initial delay in seconds before the first retry (default: 2.0).
            This value is doubled for each subsequent retry using exponential backoff.
            For example, with initial_delay=2.0:
            - Retry 1: ~2-3.6s delay
            - Retry 2: ~4-7.2s delay
            - Retry 3: ~8-14.4s delay

        jitter_min: Minimum jitter as a fraction of the delay (default: 0.1 = 10%).
            Jitter adds randomization to prevent thundering herd problems when many
            clients retry simultaneously. This is the lower bound of the random range.

        jitter_max: Maximum jitter as a fraction of the delay (default: 0.9 = 90%).
            This is the upper bound of the random jitter range. The actual jitter
            applied will be a random value between jitter_min and jitter_max.

    Examples:
        Default retry strategy (5 retries, 2s initial, 10-90% jitter):
        >>> strategy = RetryStrategy()
        >>> strategy.max_duration()
        57.0

        Conservative strategy (3 retries, 1s initial, 20-80% jitter):
        >>> strategy = RetryStrategy(max_retries=3, initial_delay=1.0, jitter_min=0.2, jitter_max=0.8)
        >>> strategy.max_duration()
        12.6

        Aggressive strategy (10 retries, 0.5s initial):
        >>> strategy = RetryStrategy(max_retries=10, initial_delay=0.5)
        >>> strategy.max_duration()
        969.75

        No retries (fail fast):
        >>> strategy = RetryStrategy(max_retries=0)
        >>> strategy.max_duration()
        0.0

    Notes:
        - Retries only occur for transient errors (temporary server issues, timeouts)
        - Non-retryable errors (authentication, validation, not found) fail immediately
        - The retry strategy only applies to the caller layer (API-level errors)
        - Network-level connection retries are handled separately by the transport layer
    """

    max_retries: int = 5
    initial_delay: float = 2.0
    jitter_min: float = 0.1
    jitter_max: float = 0.9

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and jitter.

        Args:
            attempt: Zero-based retry attempt number (0 for first retry, 1 for second, etc.)

        Returns:
            Delay in seconds before the next retry attempt, including jitter.

        Example:
            >>> strategy = RetryStrategy(initial_delay=2.0, jitter_min=0.1, jitter_max=0.9)
            >>> delay = strategy.calculate_delay(0)  # First retry
            >>> 2.0 <= delay <= 3.8  # 2s base + up to 90% jitter
            True
        """
        base_delay = self.initial_delay * (2**attempt)
        jitter_range = base_delay * (self.jitter_max - self.jitter_min)
        jitter = random.uniform(
            base_delay * self.jitter_min, base_delay * self.jitter_min + jitter_range
        )
        return base_delay + jitter

    def max_duration(self) -> float:
        """Calculate maximum possible duration for all retries.

        Returns the worst-case total time spent on retries, assuming maximum jitter
        for each attempt. This does NOT include the actual request execution time.

        Returns:
            Maximum total retry duration in seconds (worst case).

        Example:
            >>> strategy = RetryStrategy(max_retries=5, initial_delay=2.0, jitter_max=0.9)
            >>> strategy.max_duration()
            117.8
        """
        total = 0.0
        for attempt in range(self.max_retries):
            total += self.initial_delay * (2**attempt) * (1 + self.jitter_max)
        return total
