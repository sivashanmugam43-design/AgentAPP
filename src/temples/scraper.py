"""Polite HTTP client for temple.dinamalar.com (plain httpx; every page is server-rendered HTML).

- At most `concurrency` (<= 3) requests in flight.
- Each request slot waits a random delay_min..delay_max seconds after every request.
- Timeouts, connection errors and 5xx are retried with exponential backoff (+ jitter).
- HTTP 429 pauses *all* slots for Retry-After seconds (or the backoff, if the header is absent).
- Other 4xx fail immediately. Bodies are always decoded as UTF-8.
No attempt is made to get around any bot protection or rate limit.
"""

import asyncio
import logging
import random
import time
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx

from config.settings import settings

log = logging.getLogger("agentapp")


class FetchError(Exception):
    """A URL could not be fetched after all retries (or returned a non-retryable status)."""


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError):
            return None


class PoliteClient:
    def __init__(self, concurrency: int = settings.concurrency, delay_min: float = settings.delay_min,
                 delay_max: float = settings.delay_max, max_attempts: int = settings.max_attempts,
                 backoff_base: float = settings.backoff_base, timeout: float = settings.timeout,
                 transport: Optional[httpx.AsyncBaseTransport] = None):
        self.delay_min, self.delay_max = delay_min, delay_max
        self.max_attempts, self.backoff_base = max_attempts, backoff_base
        self._slots = asyncio.Semaphore(max(1, min(3, concurrency)))
        self._paused_until = 0.0  # monotonic time; set on HTTP 429
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ta,en-IN;q=0.9,en;q=0.8",
            },
            timeout=timeout, follow_redirects=True, transport=transport,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._client.aclose()

    def _backoff(self, attempt: int) -> float:
        return self.backoff_base * 2 ** (attempt - 1) + random.uniform(0, 1)

    async def _wait_if_paused(self) -> None:
        wait = self._paused_until - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)

    async def get_text(self, url: str) -> str:
        """GET url and return the body decoded as UTF-8. Raises FetchError when it gives up."""
        last_error = "unknown error"
        async with self._slots:
            for attempt in range(1, self.max_attempts + 1):
                await self._wait_if_paused()
                retry_in = self._backoff(attempt)
                try:
                    response = await self._client.get(url)
                except (httpx.TimeoutException, httpx.TransportError) as e:
                    last_error = f"{type(e).__name__}: {e}".rstrip(": ")
                else:
                    status = response.status_code
                    if status == 429:
                        retry_in = _retry_after_seconds(response) or retry_in
                        self._paused_until = max(self._paused_until, time.monotonic() + retry_in)
                        last_error = "HTTP 429 Too Many Requests"
                        log.warning(f"HTTP 429 on {url}; pausing all requests for {retry_in:.0f}s")
                    elif status >= 500:
                        last_error = f"HTTP {status}"
                    elif status >= 400:
                        raise FetchError(f"HTTP {status}")
                    else:
                        return self._decode(response, url)
                finally:
                    # Politeness gap after every request, success or not
                    await asyncio.sleep(random.uniform(self.delay_min, self.delay_max))
                if attempt < self.max_attempts:
                    log.debug(f"{last_error} on {url}; retry {attempt}/{self.max_attempts - 1} in {retry_in:.1f}s")
                    await asyncio.sleep(retry_in)
        raise FetchError(f"{last_error} (after {self.max_attempts} attempts)")

    @staticmethod
    def _decode(response: httpx.Response, url: str) -> str:
        try:
            return response.content.decode("utf-8")
        except UnicodeDecodeError:
            log.warning(f"{url} is not valid UTF-8; undecodable bytes were replaced")
            return response.content.decode("utf-8", errors="replace")
