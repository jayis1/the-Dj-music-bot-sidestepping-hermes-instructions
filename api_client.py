"""
Thin HTTP client for the DJ Bot's Mission Control API.

All calls go through this module so the rest of the agent
doesn't need to know about URLs, headers, or error handling.
"""

import logging
from typing import Any, Optional
from urllib.parse import urljoin

import aiohttp

logger = logging.getLogger("shadow.api")


class MissionControlClient:
    """Async client for the DJ Bot Mission Control REST API."""

    def __init__(self, base_url: str, web_password: str = ""):
        """
        Args:
            base_url: e.g. "http://192.168.1.50:8080"
            web_password: Optional Mission Control login password
        """
        self.base_url = base_url.rstrip("/")
        self.web_password = web_password
        self._session: Optional[aiohttp.ClientSession] = None
        self._csrf_token: Optional[str] = None

    # ── Session lifecycle ──────────────────────────────────────────

    async def start(self):
        """Create the HTTP session and authenticate."""
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"Accept": "application/json"},
        )
        if self.web_password:
            await self._authenticate()

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Auth ───────────────────────────────────────────────────────

    async def _authenticate(self):
        """Log into Mission Control and store session + CSRF token."""
        login_url = f"{self.base_url}/login"
        async with self._session.post(
            login_url,
            data={"password": self.web_password},
            allow_redirects=False,
        ) as resp:
            # Session cookie is set automatically by aiohttp
            if resp.status not in (200, 302):
                logger.warning("Login may have failed (status %d)", resp.status)

        # Fetch any page to extract CSRF token from meta tag
        try:
            async with self._session.get(f"{self.base_url}/") as as resp:
                text = await as resp.text()
                import re
                match = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', text)
                if match:
                    self._csrf_token = match.group(1)
                    logger.info("CSRF token acquired")
        except Exception as e:
            logger.warning("Could not fetch CSRF token: %s", e)

    def _headers(self) -> dict:
        """Return headers with CSRF token if available."""
        h = {}
        if self._csrf_token:
            h["X-CSRFToken"] = self._csrf_token
        return h

    # ── Generic request helpers ────────────────────────────────────

    async def _get(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        try:
            async with self._session.get(url) as resp:
                if resp.content_type == "application/json":
                    return await resp.json()
                return {"status": resp.status, "text": await resp.text()}
        except aiohttp.ClientError as e:
            logger.error("GET %s failed: %s", path, e)
            return {"error": str(e)}

    async def _post(self, path: str, json: Optional[dict] = None, data: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            async with self._session.post(url, json=json, data=data, headers=self._headers()) as resp:
                if resp.content_type == "application/json":
                    return await resp.json()
                return {"status": resp.status, "text": await resp.text()}
        except aiohttp.ClientError as e:
            logger.error("POST %s failed: %s", path, e)
            return {"error": str(e)}

    # ── Cookie endpoints ──────────────────────────────────────────

    async def cookie_health(self) -> dict:
        """GET /api/ytcookies/health — cookie age, source, needs_injection."""
        return await self._get("/api/ytcookies/health")

    async def cookie_auth_status(self) -> dict:
        """GET /api/ytcookies/auth_status — auth_blocked flag + recent errors."""
        return await self._get("/api/ytcookies/auth_status")

    async def cookie_inject(self, cookie_text: str, source: str = "shadow-controller") -> dict:
        """
        POST /api/ytcookies/inject — inject fresh Netscape-format cookies.
        
        The bot accepts: Netscape text, raw Cookie headers, or JSON arrays.
        We always send Netscape format (from the Firefox cookie.txt plugin).
        """
        return await self._post(
            "/api/ytcookies/inject",
            json={"cookies": cookie_text, "format": "netscape", "source": source},
        )

    async def cookie_status(self) -> dict:
        """GET /api/ytcookies/status — current cookie auth status overview."""
        return await self._get("/api/ytcookies/status")

    # ── Playback endpoints ─────────────────────────────────────────

    async def play(self, guild_id: str, query: str) -> dict:
        """POST /api/<guild_id>/play — queue a song/playlist by URL or search."""
        return await self._post(f"/api/{guild_id}/play", json={"query": query})

    async def skip(self, guild_id: str) -> dict:
        """POST /api/<guild_id>/skip — skip current track."""
        return await self._post(f"/api/{guild_id}/skip")

    async def stop(self, guild_id: str) -> dict:
        """POST /api/<guild_id>/stop — stop playback, clear queue."""
        return await self._post(f"/api/{guild_id}/stop")

    async def volume(self, guild_id: str, vol: int) -> dict:
        """POST /api/<guild_id>/volume — set volume 0-200."""
        return await self._post(f"/api/{guild_id}/volume", json={"volume": vol})

    # ── Queue endpoints ───────────────────────────────────────────

    async def queue_clear(self, guild_id: str) -> dict:
        """POST /api/<guild_id>/queue/clear — clear entire queue."""
        return await self._post(f"/api/{guild_id}/queue/clear")

    async def queue_remove(self, guild_id: str, index: int) -> dict:
        """DELETE /api/<guild_id>/queue/<index> — remove item by index."""
        url = f"{self.base_url}/api/{guild_id}/queue/{index}"
        try:
            async with self._session.delete(url, headers=self._headers()) as resp:
                if resp.content_type == "application/json":
                    return await resp.json()
                return {"status": resp.status}
        except aiohttp.ClientError as e:
            logger.error("DELETE /api/%s/queue/%d failed: %s", guild_id, index, e)
            return {"error": str(e)}

    # ── Auto-DJ endpoints ──────────────────────────────────────────

    async def autodj_toggle(self, guild_id: str) -> dict:
        """POST /api/<guild_id>/autodj_toggle — toggle Auto-DJ on/off."""
        return await self._post(f"/api/{guild_id}/autodj_toggle")

    async def autodj_source(self, guild_id: str, source: str) -> dict:
        """POST /api/<guild_id>/autodj_source — set Auto-DJ source (playlist URL or preset)."""
        return await self._post(f"/api/{guild_id}/autodj_source", json={"source": source})

    # ── DJ mode endpoints ──────────────────────────────────────────

    async def dj_toggle(self, guild_id: str) -> dict:
        """POST /api/<guild_id>/dj_toggle — toggle DJ mode."""
        return await self._post(f"/api/{guild_id}/dj_toggle")

    async def ai_dj_toggle(self, guild_id: str) -> dict:
        """POST /api/<guild_id>/ai_dj_toggle — toggle AI side host."""
        return await self._post(f"/api/{guild_id}/ai_dj_toggle")

    # ── Stream endpoints ──────────────────────────────────────────

    async def youtube_stream_status(self, guild_id: str) -> dict:
        """GET /api/<guild_id>/youtube_stream/status — stream active/running/title."""
        return await self._get(f"/api/{guild_id}/youtube_stream/status")

    async def youtube_stream_toggle(self, guild_id: str) -> dict:
        """POST /api/<guild_id>/youtube_stream/toggle — start/stop stream."""
        return await self._post(f"/api/{guild_id}/youtube_stream/toggle")

    # ── OBS endpoints ──────────────────────────────────────────────

    async def obs_status(self) -> dict:
        """GET /api/obs/status — OBS connection/streaming/recording status."""
        return await self._get("/api/obs/status")

    async def obs_reconnect(self) -> dict:
        """POST /api/obs/reconnect — force reconnect to OBS."""
        return await self._post("/api/obs/reconnect")

    async def obs_streaming_start(self) -> dict:
        """POST /api/obs/streaming/start — start OBS streaming."""
        return await self._post("/api/obs/streaming/start")

    async def obs_streaming_configure_and_start(self) -> dict:
        """POST /api/obs/streaming/configure_and_start — configure + start in one call."""
        return await self._post("/api/obs/streaming/configure_and_start")

    async def obs_streaming_stop(self) -> dict:
        """POST /api/obs/streaming/stop — stop OBS streaming."""
        return await self._post("/api/obs/streaming/stop")

    # ── History / presets ──────────────────────────────────────────

    async def history(self, guild_id: str) -> dict:
        """GET /api/<guild_id>/history — recently played tracks."""
        return await self._get(f"/api/{guild_id}/history")

    async def presets_list(self) -> dict:
        """GET /api/presets — list saved presets."""
        return await self._get("/api/presets")

    async def preset_load(self, guild_id: str, name: str) -> dict:
        """POST /api/<guild_id>/presets/load — load a preset into queue."""
        return await self._post(f"/api/{guild_id}/presets/load", json={"name": name})

    # ── System endpoints ───────────────────────────────────────────

    async def ollama_status(self) -> dict:
        """GET /api/ollama/status — check Ollama availability."""
        return await self._get("/api/ollama/status")

    async def restart_bot(self) -> dict:
        """POST /api/restart — restart the DJ bot."""
        return await self._post("/api/restart")

    async def shutdown_bot(self) -> dict:
        """POST /api/shutdown — shut down the DJ bot."""
        return await self._post("/api/shutdown")

    # ── Dashboard scrape (fallback for queue depth) ──────────────

    async def dashboard_html(self) -> str:
        """GET / — fetch the full dashboard HTML for parsing queue state."""
        try:
            async with self._session.get(f"{self.base_url}/") as resp:
                return await resp.text()
        except aiohttp.ClientError as e:
            logger.error("Dashboard HTML fetch failed: %s", e)
            return ""

    async def queue_status_scrape(self, guild_id: str) -> dict:
        """
        Scrape queue info from the dashboard page.
        Returns {queue_length, playing, current_title, autodj_enabled}.
        
        This is a fallback until the bot has a /api/<guild_id>/queue/status endpoint.
        """
        html = await self.dashboard_html()
        if not html:
            return {"error": "could not fetch dashboard"}

        import re
        result = {
            "queue_length": 0,
            "playing": False,
            "current_title": "",
            "autodj_enabled": False,
        }

        # Try to extract queue length from the guild card
        # The dashboard renders queue items as <li> inside the guild card
        queue_items = re.findall(r'data-queue-item|class="queue-item"', html)
        result["queue_length"] = len(queue_items)

        # Current title
        title_match = re.search(r'data-current-title="([^"]*)"', html)
        if not title_match:
            title_match = re.search(r'class="now-playing[^"]*"[^>]*>([^<]+)<', html)
        if title_match:
            result["current_title"] = title_match.group(1)

        # Playing state
        if "Now Playing" in html or "data-playing" in html:
            result["playing"] = True

        # Auto-DJ state
        if "autodj" in html.lower() and "enabled" in html.lower():
            result["autodj_enabled"] = True

        return result