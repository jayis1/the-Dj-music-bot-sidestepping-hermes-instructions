"""
SilverBullet Documenter — Loop 7: Document station events to a SilverBullet PKM.

This loop periodically pushes a station dashboard update to SilverBullet,
ensuring the knowledge base always has recent state. It also listens for
incidents from other loops and documents them in real-time.

The actual documentation calls go through the Hermes Agent API
(/api/hermes/silverbullet/*), which handles the SilverBullet Space API writes.
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("shadow.sb_documenter")


class SilverBulletDocumenter:
    """
    Keeps the SilverBullet knowledge base up to date.
    
    Periodically pushes:
      - Dashboard page (live status overview with queries)
    
    And reacts to events from other loops:
      - Cookie auth blocks → incident page
      - Queue dry → incident page
      - Stream disconnect → incident page
      - Stream recovery → update incident (resolved)
    """

    def __init__(self, config: dict, api_client, alert_system):
        self.api = api_client
        self.alerts = alert_system
        self.config = config
        
        self.interval = config.get("silverbullet_dashboard_interval", 300)
        self._running = False
        self._last_dashboard_push = 0

    async def start(self):
        """Start the SilverBullet documentation loop."""
        self._running = True
        
        # Check connectivity first
        status = await self.api.sb_status()
        if not status.get("enabled"):
            logger.info("SilverBullet not enabled — skipping documenter loop")
            return
        
        if not status.get("connected"):
            logger.warning(
                "SilverBullet at %s is not reachable — will retry each cycle",
                status.get("url", "?"),
            )
        else:
            writeable = status.get("writable", False)
            logger.info(
                "SilverBullet connected ✅ (url=%s, writable=%s, prefix=%s)",
                status.get("url", "?"),
                writeable,
                self.config.get("silverbullet_prefix", "station"),
            )
        
        logger.info(
            "SilverBullet documenter started (dashboard push every %ds)",
            self.interval,
        )
        
        while self._running:
            try:
                await self._push_dashboard()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("SilverBullet dashboard push failed: %s", e, exc_info=True)
            
            await asyncio.sleep(self.interval)

    def stop(self):
        """Stop the documentation loop."""
        self._running = False
        logger.info("SilverBullet documenter stopped")

    async def _push_dashboard(self):
        """Push a dashboard update to SilverBullet via the Hermes API."""
        result = await self.api.sb_dashboard()
        if result.get("ok"):
            logger.debug("SilverBullet dashboard updated → %s", result.get("page_path", ""))
        else:
            logger.warning(
                "SilverBullet dashboard update failed: %s",
                result.get("error", "unknown"),
            )

    # ── Event documenters (called by other loops) ──────────────────

    async def document_incident(self, title: str, severity: str = "warning",
                                category: str = "general", body: str = "",
                                resolved: bool = False):
        """Document an incident to SilverBullet. Called by other loops."""
        result = await self.api.sb_incident(
            title=title, severity=severity, category=category,
            body=body, resolved=resolved,
        )
        if result.get("ok"):
            logger.info("SilverBullet: incident documented → %s", result.get("page_path", ""))
        else:
            logger.debug("SilverBullet: incident doc failed: %s", result.get("error", ""))

    async def document_track(self, title: str, url: str = "",
                             duration: Optional[int] = None,
                             source: str = "hermes"):
        """Document a track play to SilverBullet."""
        result = await self.api.sb_track(
            title=title, url=url, duration=duration, source=source,
        )
        if result.get("ok"):
            logger.debug("SilverBullet: track documented → %s", result.get("page_path", ""))

    async def document_stream_health(self, healthy: bool = True,
                                     keyframes_ok: bool = True,
                                     bitrate: int = 0,
                                     audio_ok: bool = True,
                                     details: str = ""):
        """Document stream health to SilverBullet."""
        result = await self.api.sb_stream_health(
            healthy=healthy, keyframes_ok=keyframes_ok,
            bitrate=bitrate, audio_ok=audio_ok, details=details,
        )
        if result.get("ok"):
            logger.debug("SilverBullet: stream health documented")