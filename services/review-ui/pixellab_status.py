"""On-demand PixelLab connectivity / auth / quota checks.

Three concurrent checks, each with a tight timeout so the modal stays
snappy. Returns a structured payload the JS can render as three status
dots without any "is the field null vs absent" branching.

Why so defensive about errors:
  This runs every time the user opens the account modal. It MUST NOT
  raise. A 4xx/5xx, a TLS hiccup, a DNS failure — all surface as a
  red dot with a short reason string, never as a 500 to the browser.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass

import httpx


_BASE_URL = "https://api.pixellab.ai/v1"
_HOST_URL = "https://api.pixellab.ai"
_TIMEOUT_SEC = 5.0


@dataclass
class CheckResult:
    ok: bool
    detail: str = ""


@dataclass
class StatusReport:
    reachable: CheckResult
    authenticated: CheckResult
    quota: CheckResult
    quota_remaining: float | None = None
    quota_unit: str | None = None  # "credits", "USD", etc — opaque

    def to_dict(self) -> dict:
        return {
            "reachable": asdict(self.reachable),
            "authenticated": asdict(self.authenticated),
            "quota": asdict(self.quota),
            "quota_remaining": self.quota_remaining,
            "quota_unit": self.quota_unit,
        }


async def _check_reachable(client: httpx.AsyncClient) -> CheckResult:
    try:
        # We don't expect 200 from a bare GET on the root — anything that
        # returns from the host (even 404) means the network path is up.
        r = await client.get(_HOST_URL, timeout=_TIMEOUT_SEC)
        return CheckResult(ok=True, detail=f"HTTP {r.status_code}")
    except httpx.ConnectError as e:
        return CheckResult(ok=False, detail=f"Connect failed: {e!s}")
    except httpx.TimeoutException:
        return CheckResult(ok=False, detail="Timed out")
    except Exception as e:
        return CheckResult(ok=False, detail=f"Network error: {e!s}")


async def _check_auth(client: httpx.AsyncClient, api_key: str) -> CheckResult:
    if not api_key:
        return CheckResult(ok=False, detail="No API key set")
    try:
        # Cheapest known authed endpoint is /balance. If PixelLab returns
        # 401/403, the key is bad. Anything else 2xx-4xx (except auth) is
        # treated as authed since we got past the bouncer.
        r = await client.get(
            f"{_BASE_URL}/balance",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_TIMEOUT_SEC,
        )
        if r.status_code in (401, 403):
            return CheckResult(ok=False, detail="Key rejected by API")
        if r.status_code == 404:
            # /balance not present — try a HEAD on a generation endpoint as
            # a last-ditch auth check. We don't actually generate.
            r2 = await client.head(
                f"{_BASE_URL}/generate-image-pixflux",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=_TIMEOUT_SEC,
            )
            if r2.status_code in (401, 403):
                return CheckResult(ok=False, detail="Key rejected by API")
            return CheckResult(ok=True, detail="Key accepted (balance endpoint unavailable)")
        if r.status_code >= 500:
            return CheckResult(ok=False, detail=f"API error HTTP {r.status_code}")
        return CheckResult(ok=True, detail="Key accepted")
    except httpx.TimeoutException:
        return CheckResult(ok=False, detail="Timed out")
    except Exception as e:
        return CheckResult(ok=False, detail=f"Error: {e!s}")


async def _check_quota(client: httpx.AsyncClient, api_key: str) -> tuple[CheckResult, float | None, str | None]:
    if not api_key:
        return CheckResult(ok=False, detail="No API key set"), None, None
    try:
        r = await client.get(
            f"{_BASE_URL}/balance",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_TIMEOUT_SEC,
        )
        if r.status_code == 404:
            return CheckResult(ok=True, detail="Quota endpoint unavailable"), None, None
        if r.status_code in (401, 403):
            return CheckResult(ok=False, detail="Unauthorized"), None, None
        if r.status_code >= 400:
            return CheckResult(ok=False, detail=f"HTTP {r.status_code}"), None, None
        try:
            data = r.json()
        except Exception:
            return CheckResult(ok=False, detail="Bad response shape"), None, None
        # PixelLab's exact field name for balance varies between docs revisions.
        # Look for the most common shapes; if we miss, surface the raw value.
        remaining = (
            data.get("balance")
            or data.get("credits")
            or data.get("remaining")
            or data.get("usd_balance")
        )
        unit = "credits"
        if "usd" in str(data).lower():
            unit = "USD"
        if remaining is None:
            return CheckResult(ok=True, detail="No balance reported"), None, None
        try:
            remaining_f = float(remaining)
        except Exception:
            return CheckResult(ok=True, detail=str(remaining)), None, None
        return CheckResult(ok=True, detail=f"{remaining_f:g} {unit}"), remaining_f, unit
    except httpx.TimeoutException:
        return CheckResult(ok=False, detail="Timed out"), None, None
    except Exception as e:
        return CheckResult(ok=False, detail=f"Error: {e!s}"), None, None


async def run_status_checks(api_key: str) -> StatusReport:
    """Run all three checks concurrently. Never raises."""
    async with httpx.AsyncClient() as client:
        reach_t = asyncio.create_task(_check_reachable(client))
        auth_t = asyncio.create_task(_check_auth(client, api_key))
        quota_t = asyncio.create_task(_check_quota(client, api_key))

        reach = await reach_t
        # If the host is unreachable, short-circuit auth/quota — they'd just
        # echo the same connect failure.
        if not reach.ok:
            for t in (auth_t, quota_t):
                t.cancel()
            return StatusReport(
                reachable=reach,
                authenticated=CheckResult(ok=False, detail="Skipped — host unreachable"),
                quota=CheckResult(ok=False, detail="Skipped — host unreachable"),
            )

        auth = await auth_t
        quota_result, remaining, unit = await quota_t

        return StatusReport(
            reachable=reach,
            authenticated=auth,
            quota=quota_result,
            quota_remaining=remaining,
            quota_unit=unit,
        )
