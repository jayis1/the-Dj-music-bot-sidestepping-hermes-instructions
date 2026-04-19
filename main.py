"""
Shadow Controller — Main Orchestrator

The silent operator behind the 420 Radio DJ.
Runs 5 autonomous loops that keep the station on the air:
  1. Cookie Fixer     — fresh YouTube cookies, always
  2. Queue Watchdog   — never run dry
  3. Stream Monitor    — YouTube Live stays live
  4. Playlist Finder   — discover music via Hermes
  5. Discord Watcher   — fan requests flow in

Powered by Hermes Agent + Ollama + Playwright
"""

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

import yaml

# Module paths
HERE = Path(__file__).parent.resolve()

# Configure logging
def setup_logging(level: str = "INFO"):
    """Set up logging to file + console."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)-22s │ %(message)s",
        datefmt="%H:%M:%S",
    )
    
    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(log_level)
    console.setFormatter(formatter)
    
    # File handler
    log_file = HERE / "shadow_controller.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    
    root = logging.getLogger("shadow")
    root.setLevel(logging.DEBUG)
    root.addHandler(console)
    root.addHandler(file_handler)
    
    # Quieten noisy libraries
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    return root


def load_config() -> dict:
    """Load and merge configuration from config.yaml + .env overrides."""
    config_path = HERE / "config.yaml"
    env_path = HERE / ".env"
    
    # Load base config
    if config_path.exists():
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
    else:
        print(f"❌ No config.yaml found at {config_path}")
        print(f"   Copy config.example.yaml → config.yaml and fill in your settings")
        sys.exit(1)
    
    # Load .env overrides (KEY=VALUE format, no quotes)
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    # Only override if not set in config.yaml
                    env_keys = {
                        "BOT_API_URL": "bot_api_url",
                        "GUILD_ID": "guild_id",
                        "DISCORD_WEBHOOK_URL": "discord_webhook_url",
                        "DISCORD_WATCHER_TOKEN": "discord_watcher_token",
                        "FAN_REQUEST_CHANNEL_ID": "fan_request_channel_id",
                        "WEB_PASSWORD": "web_password",
                        "OLLAMA_URL": "ollama_url",
                        "OLLAMA_MODEL": "ollama_model",
                        "YOUTUBE_LIVE_URL": "youtube_live_url",
                    }
                    config_key = env_keys.get(key.upper())
                    if config_key and not config.get(config_key):
                        config[config_key] = value
    
    # Defaults
    config.setdefault("bot_api_url", "http://localhost:8080")
    config.setdefault("guild_id", "")
    config.setdefault("ollama_url", "http://localhost:11434")
    config.setdefault("ollama_model", "hermes3:8b")
    config.setdefault("web_password", "")
    config.setdefault("log_level", "INFO")
    
    # Loop intervals
    config.setdefault("cookie_check_interval", 300)
    config.setdefault("queue_check_interval", 60)
    config.setdefault("stream_check_interval", 30)
    config.setdefault("playlist_discovery_interval", 1800)
    
    # Thresholds
    config.setdefault("cookie_max_age_days", 5)
    config.setdefault("queue_min_songs", 3)
    config.setdefault("min_playlist_songs", 30)
    config.setdefault("stream_should_be_live", True)
    config.setdefault("stream_restart_max_attempts", 3)
    config.setdefault("stream_restart_cooldown", 120)
    
    # Genres
    config.setdefault("genres", ["lo-fi", "rap", "electro_swing", "edm", "chill_beats", "reggae"])
    
    # Feature flags
    config.setdefault("fan_request_enabled", False)
    config.setdefault("alert_to_mission_control", True)
    config.setdefault("alert_cooldown_seconds", 30)
    
    # Browser
    config.setdefault("firefox_profile_path", "")
    config.setdefault("cookie_txt_path", "")
    config.setdefault("youtube_live_url", "")
    config.setdefault("headless", False)
    
    return config


class ShadowController:
    """
    The main orchestrator. Starts and manages all 5 agent loops.
    """

    def __init__(self, config: dict):
        self.config = config
        self.log = logging.getLogger("shadow.main")
        self._tasks: list = []
        self._running = False
        
        # Components (initialized in start())
        self.api_client = None
        self.browser_manager = None
        self.alert_system = None
        self.cookie_fixer = None
        self.queue_watchdog = None
        self.stream_monitor = None
        self.playlist_finder = None
        self.discord_watcher = None

    async def start(self):
        """Initialize all components and start all loops."""
        self.log.info("╔══════════════════════════════════════════════════╗")
        self.log.info("║   Shadow Controller v1.0 — Starting Up           ║")
        self.log.info("║   The silent operator behind the 420 Radio DJ   ║")
        self.log.info("╚══════════════════════════════════════════════════╝")
        
        self._running = True
        
        # ── Step 1: Initialize API client ────────────────────────
        from .api_client import MissionControlClient
        
        self.api_client = MissionControlClient(
            base_url=self.config["bot_api_url"],
            web_password=self.config.get("web_password", ""),
        )
        await self.api_client.start()
        self.log.info("Mission Control API client connected → %s", self.config["bot_api_url"])
        
        # Quick connectivity test
        try:
            status = await self.api_client.cookie_status()
            self.log.info("Mission Control reachable — cookie source: %s",
                         status.get("cookie_source", "unknown"))
        except Exception as e:
            self.log.warning("Mission Control connectivity test failed: %s", e)
        
        # ── Step 2: Initialize alert system ─────────────────────
        from .alerts import AlertSystem
        
        self.alert_system = AlertSystem(self.config, self.api_client)
        await self.alert_system.start()
        self.log.info("Alert system ready (webhook: %s)",
                     "✅" if self.config.get("discord_webhook_url") else "❌ no webhook")
        
        # ── Step 3: Initialize browser manager ─────────────────
        from .browser_manager import BrowserManager
        
        self.browser_manager = BrowserManager(self.config)
        try:
            await self.browser_manager.start()
            self.log.info("Browser: Firefox + YouTube tab ready")
        except Exception as e:
            self.log.warning("Browser startup failed (some features will be degraded): %s", e)
        
        # ── Step 4: Initialize playlist finder (needs browser + Ollama) ──
        from .playlist_finder import PlaylistFinder
        
        self.playlist_finder = PlaylistFinder(
            self.config, self.api_client, self.browser_manager, self.alert_system,
        )
        self.log.info("Playlist finder ready (Ollama: %s, model: %s)",
                     self.config["ollama_url"], self.config["ollama_model"])
        
        # ── Step 5: Initialize all loops ────────────────────────
        from .cookie_fixer import CookieFixer
        from .queue_watchdog import QueueWatchdog
        from .stream_monitor import StreamMonitor
        from .discord_watcher import DiscordWatcher
        
        self.cookie_fixer = CookieFixer(
            self.config, self.api_client, self.browser_manager, self.alert_system,
        )
        
        self.queue_watchdog = QueueWatchdog(
            self.config, self.api_client, self.alert_system, self.playlist_finder,
        )
        
        self.stream_monitor = StreamMonitor(
            self.config, self.api_client, self.browser_manager, self.alert_system,
        )
        
        self.discord_watcher = DiscordWatcher(
            self.config, self.api_client, self.alert_system, self.queue_watchdog,
        )
        
        # ── Step 6: Launch active loops as async tasks ────────────
        self.log.info("Launching agent loops...")
        
        self._tasks = [
            asyncio.create_task(self.cookie_fixer.start(), name="cookie-fixer"),
            asyncio.create_task(self.queue_watchdog.start(), name="queue-watchdog"),
            asyncio.create_task(self.stream_monitor.start(), name="stream-monitor"),
            asyncio.create_task(self.playlist_finder.start(), name="playlist-finder"),
        ]
        
        fan_requests = self.config.get("fan_request_enabled", False) and bool(self.config.get("discord_watcher_token", ""))
        if fan_requests:
            self._tasks.append(
                asyncio.create_task(self.discord_watcher.start(), name="discord-watcher")
            )
        
        # ── Step 7: Startup notification ─────────────────────────
        self.log.info("┌─────────────────────────────────────────────────┐")
        self.log.info("│  Loop 1: Cookie Fixer    — every %5ds         │", self.config["cookie_check_interval"])
        self.log.info("│  Loop 2: Queue Watchdog  — every %5ds         │", self.config["queue_check_interval"])
        self.log.info("│  Loop 3: Stream Monitor  — every %5ds         │", self.config["stream_check_interval"])
        self.log.info("│  Loop 4: Playlist Finder — every %5ds         │", self.config["playlist_discovery_interval"])
        if fan_requests:
            self.log.info("│  Loop 5: Discord Watcher — event-driven        │")
        else:
            self.log.info("│  Loop 5: Discord Watcher — DISABLED            │")
        self.log.info("└─────────────────────────────────────────────────┘")
        
        loop_count = len(self._tasks)
        await self.alert_system.success(
            f"Shadow Controller online — {loop_count} loops active, genres: {', '.join(self.config['genres'])}",
            force=True,
        )
        
        # ── Step 8: Keep alive ────────────────────────────────────
        try:
            await self._keep_alive()
        except asyncio.CancelledError:
            pass

    async def _keep_alive(self):
        """Main keep-alive loop — monitors task health and restarts failed loops."""
        while self._running:
            await asyncio.sleep(60)
            
            # Check if any tasks died
            for task in self._tasks:
                if task.done() and not task.cancelled():
                    exc = task.exception()
                    if exc:
                        self.log.error("Loop %s crashed: %s", task.get_name(), exc)
                        # Restart the failed loop
                        new_task = await self._restart_loop(task.get_name(), exc)
                        if new_task:
                            idx = self._tasks.index(task)
                            self._tasks[idx] = new_task

    async def _restart_loop(self, name: str, error: Exception) -> asyncio.Task | None:
        """Restart a failed loop."""
        self.log.warning("Restarting loop: %s (error was: %s)", name, error)
        
        try:
            if name == "cookie-fixer":
                from .cookie_fixer import CookieFixer
                self.cookie_fixer = CookieFixer(
                    self.config, self.api_client, self.browser_manager, self.alert_system,
                )
                return asyncio.create_task(self.cookie_fixer.start(), name="cookie-fixer")
            
            elif name == "queue-watchdog":
                from .queue_watchdog import QueueWatchdog
                self.queue_watchdog = QueueWatchdog(
                    self.config, self.api_client, self.alert_system, self.playlist_finder,
                )
                return asyncio.create_task(self.queue_watchdog.start(), name="queue-watchdog")
            
            elif name == "stream-monitor":
                from .stream_monitor import StreamMonitor
                self.stream_monitor = StreamMonitor(
                    self.config, self.api_client, self.browser_manager, self.alert_system,
                )
                return asyncio.create_task(self.stream_monitor.start(), name="stream-monitor")
            
            elif name == "playlist-finder":
                from .playlist_finder import PlaylistFinder
                self.playlist_finder = PlaylistFinder(
                    self.config, self.api_client, self.browser_manager, self.alert_system,
                )
                return asyncio.create_task(self.playlist_finder.start(), name="playlist-finder")
            
            elif name == "discord-watcher":
                from .discord_watcher import DiscordWatcher
                self.discord_watcher = DiscordWatcher(
                    self.config, self.api_client, self.alert_system, self.queue_watchdog,
                )
                return asyncio.create_task(self.discord_watcher.start(), name="discord-watcher")
        
        except Exception as e:
            self.log.error("Failed to restart loop %s: %s", name, e)
        
        return None

    async def stop(self):
        """Gracefully shut down all loops and components."""
        self._running = False
        self.log.info("Shutting down Shadow Controller...")
        
        # Stop loops
        if self.cookie_fixer:
            self.cookie_fixer.stop()
        if self.queue_watchdog:
            self.queue_watchdog.stop()
        if self.stream_monitor:
            self.stream_monitor.stop()
        if self.playlist_finder:
            self.playlist_finder.stop()
        if self.discord_watcher:
            self.discord_watcher.stop()
        
        # Cancel async tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        # Wait for tasks to finish
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        # Close components
        if self.browser_manager:
            await self.browser_manager.stop()
        if self.alert_system:
            await self.alert_system.close()
        if self.api_client:
            await self.api_client.close()
        
        self.log.info("Shadow Controller shut down complete")


def main():
    """Entry point."""
    config = load_config()
    setup_logging(config.get("log_level", "INFO"))
    
    log = logging.getLogger("shadow.main")
    log.info("Config loaded from %s", HERE / "config.yaml")
    
    controller = ShadowController(config)
    
    # Handle signals for graceful shutdown
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    def signal_handler(sig, frame):
        log.info("Received signal %s — shutting down...", sig)
        loop.create_task(controller.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        loop.run_until_complete(controller.start())
    except KeyboardInterrupt:
        log.info("Keyboard interrupt — shutting down...")
    finally:
        loop.run_until_complete(controller.stop())
        loop.close()
        log.info("Goodbye. The station goes on.")


if __name__ == "__main__":
    main()