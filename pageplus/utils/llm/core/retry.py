"""Unified retry decorator with exponential backoff + rate-limit awareness.

Replaces the ad-hoc ``request_timestamps`` rate-limiter in ``pageplus/cli/gemini.py``
and the per-thread locks in the gemini multithread path. Both sync and async
variants are provided; the sync one is used by CLI code, the async one by the
pipeline's concurrent path.
"""
from __future__ import annotations

import asyncio
import functools
import random
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Tuple, Type, TypeVar

from pageplus.io.logger import logging
from pageplus.utils.llm.core.errors import (
    OCRError,
    RateLimitError,
    TransientError,
)

T = TypeVar("T")


@dataclass
class RetryPolicy:
    max_attempts: int = 5
    initial_backoff: float = 1.0
    max_backoff: float = 30.0
    multiplier: float = 2.0
    jitter: float = 0.25  # +/- 25%
    # Exception classes that trigger a retry. Subclasses are included automatically.
    retry_on: Tuple[Type[BaseException], ...] = (TransientError,)

    def backoff_seconds(self, attempt: int, retry_after: float | None = None) -> float:
        """Return the sleep time before ``attempt`` (1-indexed)."""
        if retry_after is not None and retry_after > 0:
            return min(retry_after, self.max_backoff)
        base = min(self.initial_backoff * (self.multiplier ** (attempt - 1)),
                   self.max_backoff)
        if self.jitter:
            delta = base * self.jitter
            base = base + random.uniform(-delta, delta)
        return max(0.0, base)


DEFAULT_POLICY = RetryPolicy()


def _extract_retry_after(exc: BaseException) -> float | None:
    return getattr(exc, "retry_after", None)


def with_retry(
    policy: RetryPolicy | None = None,
    *,
    on_failure: Callable[[BaseException, int], None] | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Sync retry decorator.

    ``on_failure`` is invoked with ``(exception, attempt_number)`` for every
    attempt that raised (including the last one, right before the exception is
    re-raised). Useful for surfacing ``RateLimitError`` warnings in the CLI.
    """
    policy = policy or DEFAULT_POLICY

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            attempt = 0
            while True:
                attempt += 1
                try:
                    return fn(*args, **kwargs)
                except policy.retry_on as exc:
                    if on_failure is not None:
                        on_failure(exc, attempt)
                    if attempt >= policy.max_attempts:
                        raise
                    sleep = policy.backoff_seconds(attempt, _extract_retry_after(exc))
                    is_rate_limit = isinstance(exc, RateLimitError)
                    logging.warning(
                        "OCR backend call failed (attempt %d/%d, rate_limit=%s): %s; sleeping %.2fs",
                        attempt, policy.max_attempts, is_rate_limit, exc, sleep,
                    )
                    time.sleep(sleep)
                except OCRError:
                    raise
                except BaseException as exc:
                    # Unexpected; surface it without retrying unless caller opted in.
                    if on_failure is not None:
                        on_failure(exc, attempt)
                    raise

        return wrapper

    return decorator


def awith_retry(
    policy: RetryPolicy | None = None,
    *,
    on_failure: Callable[[BaseException, int], None] | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Async variant of :func:`with_retry`."""
    policy = policy or DEFAULT_POLICY

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs) -> T:
            attempt = 0
            while True:
                attempt += 1
                try:
                    return await fn(*args, **kwargs)
                except policy.retry_on as exc:
                    if on_failure is not None:
                        on_failure(exc, attempt)
                    if attempt >= policy.max_attempts:
                        raise
                    sleep = policy.backoff_seconds(attempt, _extract_retry_after(exc))
                    is_rate_limit = isinstance(exc, RateLimitError)
                    logging.warning(
                        "OCR backend call failed (attempt %d/%d, rate_limit=%s): %s; sleeping %.2fs",
                        attempt, policy.max_attempts, is_rate_limit, exc, sleep,
                    )
                    await asyncio.sleep(sleep)
                except OCRError:
                    raise
                except BaseException as exc:
                    if on_failure is not None:
                        on_failure(exc, attempt)
                    raise

        return wrapper

    return decorator
