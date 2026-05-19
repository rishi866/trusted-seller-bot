"""
Playwright-based Gemini offer-link checker.

Uses Google account cookies (exported from browser) to load each link in a
headless Chromium window and decide whether it has been claimed/redeemed.

Statuses
--------
unclaimed      – offer page visible, link is still valid
claimed        – "already redeemed" / "no longer available" page
invalid        – HTTP 404 / 410 (token doesn't exist)
cookie_expired – cookie is no longer authenticated (lands on Google login)
error          – navigation timeout or unexpected exception
"""

import asyncio
import logging
import shutil
from typing import Callable, Literal

logger = logging.getLogger(__name__)


def _system_chromium() -> str | None:
    """
    Find a system-installed Chromium/Chrome binary.
    Returns path on Railway/Linux (Nix), None on Windows (uses Playwright's own Chromium).
    """
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(name)
        if path:
            logger.info("Using system Chromium: %s", path)
            return path
    return None

LinkStatus = Literal["unclaimed", "claimed", "invalid", "cookie_expired", "error"]

# ── Signal lists ──────────────────────────────────────────────────────────────

_CLAIMED_SIGNALS = [
    "already been redeemed",
    "already redeemed",
    "offer is no longer",
    "offer has expired",
    "offer not available",
    "offer unavailable",
    "offer expired",
    "no longer available",
    "redemption limit",
    "offer limit reached",
    "link is no longer valid",
    "promotion has ended",
    "this offer has been used",
    "this offer has already",
    "offer is invalid",
    "link has expired",
]

_UNCLAIMED_SIGNALS = [
    "activate your",
    "get started",
    "try google one",
    "try google gemini",
    "claim your",
    "redeem your",
    "subscribe now",
    "start your",
    "free trial",
    "activate now",
    "activate plan",
    "start free",
    "get gemini",
]


# ── Single-link checker ───────────────────────────────────────────────────────

async def _check_one(page, link: str) -> LinkStatus:
    """Navigate to *link* using an already-authenticated page and return its status."""
    try:
        resp = await page.goto(link, wait_until="domcontentloaded", timeout=30_000)
        # Allow JS redirects to settle
        await asyncio.sleep(2)

        final_url: str = page.url
        content: str   = (await page.content()).lower()
        title: str     = (await page.title()).lower()

        # 1. HTTP 404 / 410 → token doesn't exist at all
        if resp and resp.status in (404, 410):
            return "invalid"

        # 2. Still on Google sign-in page → cookies not authenticated
        if "accounts.google.com" in final_url and (
            "signin" in final_url or "ServiceLogin" in final_url
        ):
            return "cookie_expired"

        # 3. Check page text / title for "claimed" phrases
        for signal in _CLAIMED_SIGNALS:
            if signal in content or signal in title:
                return "claimed"

        # 4. Check for "unclaimed" phrases
        for signal in _UNCLAIMED_SIGNALS:
            if signal in content or signal in title:
                return "unclaimed"

        # 5. Still on offer domain with no error → treat as unclaimed
        if "one.google.com" in final_url or "serviceactivation.google.com" in final_url:
            return "unclaimed"

        return "error"

    except Exception as exc:
        logger.warning("_check_one error (%s): %s", link, exc)
        return "error"


# ── Batch checker (public API) ────────────────────────────────────────────────

async def check_links_batch(
    links: list[dict],
    cookies: list[dict],
    delay: float = 1.5,
    progress_callback: Callable | None = None,
) -> dict[int, LinkStatus]:
    """
    Check a list of links using a Playwright headless browser.

    Parameters
    ----------
    links : list of {"id": int, "link": str}
    cookies : Playwright-format cookie dicts (from _normalize_cookies in bot.py)
    delay : seconds to wait between requests (avoids Google rate-limiting)
    progress_callback : async callable(done, total, link_id, status)

    Returns
    -------
    dict mapping link_id → LinkStatus
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error(
            "playwright is not installed.\n"
            "Run:  pip install playwright\n"
            "Then: playwright install chromium"
        )
        return {item["id"]: "error" for item in links}

    results: dict[int, LinkStatus] = {}
    cookie_dead = False

    async with async_playwright() as pw:
        launch_kwargs: dict = {"headless": True}
        sys_chrome = _system_chromium()
        if sys_chrome:
            launch_kwargs["executable_path"] = sys_chrome
        browser = await pw.chromium.launch(**launch_kwargs)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )

        try:
            await ctx.add_cookies(cookies)
        except Exception as exc:
            logger.error("add_cookies failed: %s", exc)

        page = await ctx.new_page()

        for i, item in enumerate(links):
            lid  = item["id"]
            lurl = item["link"]

            if cookie_dead:
                # Cookie is gone — no point checking remaining links
                results[lid] = "cookie_expired"
                if progress_callback:
                    await progress_callback(i + 1, len(links), lid, "cookie_expired")
                continue

            status = await _check_one(page, lurl)
            results[lid] = status

            if status == "cookie_expired":
                cookie_dead = True
                logger.warning("Cookie expired at link #%d — skipping rest.", lid)

            if progress_callback:
                await progress_callback(i + 1, len(links), lid, status)

            # Delay between requests (skip after last item)
            if i < len(links) - 1 and not cookie_dead:
                await asyncio.sleep(delay)

        await ctx.close()
        await browser.close()

    return results
