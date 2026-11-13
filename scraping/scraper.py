"""
Scraping Utilities for Agentic Browser
Safe page and image scraping with human-like behavior

#105 StealthScraper bypass fix + scaffolding:
- Fixed confusing self.browser naming (always received a Page) -> self.page
- Added recovery: Optional param + _safe_goto that uses orchestrator recovery when attached
- attach_recovery() helper for post-init wiring (due to init ordering in AgentBrowser)
- Consumers can now avoid full bypass; MCP/AgentBrowser flows get recovery protection.
"""

import time
from typing import List, Dict, Optional, Any


class StealthScraper:
    """High-level scraping with built-in stealth and human behavior + optional recovery (#105)."""

    def __init__(
        self, page, human_behavior, orchestrator, recovery: Optional[Any] = None
    ):
        self.page = page  # Playwright Page (fixed naming from #105)
        self.human = human_behavior
        self.orchestrator = orchestrator
        self.recovery = recovery  # AntiBlockOrchestrator scaffolding to prevent bypass

    def _has_recovery(self) -> bool:
        """True when a usable recovery wrapper is attached.

        Single source of truth for the routing decision so scrape_page's
        provenance marker can never disagree with what _safe_goto actually
        did. An object without execute_with_recovery is treated as absent.
        """
        return bool(self.recovery and hasattr(self.recovery, "execute_with_recovery"))

    async def _safe_goto(self, url: str, platform: str = "scrape"):
        """Navigation preferring recovery wrapper if present (#105).

        When a recovery orchestrator is attached and it raises (e.g.
        MaxRetriesExceeded after a detected block), the failure propagates:
        falling back to a raw goto would send one more unprotected request
        and let scrape_page extract the challenge page as content. With no
        recovery attached, the plain goto path is used as before.

        Returns (ok, via_recovery): via_recovery is True only when the
        attached recovery wrapper actually carried the navigation, so the
        caller can mark the provenance of the extracted content.
        """
        if self._has_recovery():

            async def _nav():
                await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
                return True

            await self.recovery.execute_with_recovery(
                func=_nav, platform=platform, url=url
            )
            return True, True
        await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        return True, False

    async def scrape_page(
        self, url: str, extract_images: bool = False, platform: str = "unknown"
    ) -> Dict:
        """Scrape with natural behavior + recovery opt-in.

        The returned content dict carries a ``recovery_used`` boolean so
        callers can tell a genuine article apart from content that only
        arrived after the attached recovery flow (retries, rotation, ...).
        It is True only when navigation actually went through an attached
        recovery wrapper; direct navigation marks it False. When recovery is
        attached but raises (block confirmed, retries exhausted), the error
        propagates and no content is produced. title/url/text/headings keep
        their existing shape.
        """
        _, via_recovery = await self._safe_goto(url, platform=platform)
        if self.orchestrator:
            await self.orchestrator.read_page_naturally(2, 4)
        content = await self.page.evaluate("""
            () => {
                return {
                    title: document.title,
                    url: window.location.href,
                    text: document.body.innerText.substring(0, 8000),
                    headings: Array.from(document.querySelectorAll('h1,h2,h3')).map(h => h.innerText).slice(0, 10)
                }
            }
        """)
        # Provenance marker on the content itself: the nested content dict is
        # the canonical shape consumed by both the SDK client and MCP handler.
        content["recovery_used"] = bool(via_recovery)
        result = {"url": url, "timestamp": time.time(), "content": content}
        if extract_images:
            result["images"] = await self.extract_images()
        return result

    async def extract_images(self, max_images: int = 10) -> List[Dict]:
        # Validate before interpolation: max_images reaches the page script
        # via f-string below, so only a plain int may pass. Reject bools and
        # non-numeric values; clamp negatives to 0.
        if isinstance(max_images, bool):
            raise ValueError(f"max_images must be an int, got {max_images!r}")
        try:
            max_images = int(max_images)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"max_images must be an int, got {max_images!r}") from exc
        max_images = max(0, max_images)
        images = await self.page.evaluate(f"""
            () => {{
                return Array.from(document.images).slice(0, {max_images}).map(img => ({{
                    src: img.src, alt: img.alt || "", width: img.width, height: img.height
                }}));
            }}
        """)
        return images

    async def scrape_amazon_product(self, url: str, platform: str = "amazon") -> Dict:
        await self._safe_goto(url, platform=platform)
        if self.human:
            await self.human.think(1500, 3000)
            await self.human.scroll_naturally(200)
        data = await self.page.evaluate("""
            () => {
                const title = document.querySelector("#productTitle")?.innerText || "";
                const price = document.querySelector(".a-price .a-offscreen")?.innerText || "";
                const rating = document.querySelector(".a-icon-alt")?.innerText || "";
                return { title, price, rating, url: window.location.href };
            }
        """)
        if self.human:
            await self.human.think(800, 1500)
        return data

    def attach_recovery(self, recovery: Any):
        """Post-construction wiring for recovery (AgentBrowser init order workaround)."""
        self.recovery = recovery
