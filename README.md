# Shadow Controller — Hermes Agent for the 420 Radio DJ

> **Autonomous operator for the [420 Radio DJ Music Bot](https://github.com/jayis1/the-Dj-music-bot-sidestepping-ollama).**
> 6 loops keep the station on the air: cookies fresh, queue full, stream live, music discovered.

This repo is a **standalone package** — clone it on a separate VM from the DJ bot. It communicates with the DJ bot **only** via the Mission Control HTTP API (`/api/hermes/*` with Bearer token auth). Zero imports from the parent project.

---

## What It Does

| Loop | What | How Often |
|------|------|-----------|
| **Cookie Fixer** | Detects stale/blocked YouTube cookies, extracts fresh ones from the Firefox cookie.txt plugin, injects them via the Mission Control API | Every 5 min |
| **Queue Watchdog** | Monitors queue depth, enables Auto-DJ and discovers playlists when the queue runs dry | Every 1 min |
| **Stream Monitor** | Watches the YouTube Live stream + OBS health, auto-restarts if the stream dies | Every 30 sec |
| **Playlist Finder** | Browses YouTube and discovers playlists matching the station vibe (lo-fi, rap, reggae, electro swing, EDM) | Every 30 min |
| **Discord Watcher** | *Optional* — Listens for fan-posted YouTube links in a Discord channel, queues them automatically | Disabled |
| **Suno Creator** | Hermes makes original music on Suno.com — reggae about life & weed, lo-fi chill, electro swing — tracks go straight into the DJ bot queue | Every 1 hr |

---

## Quick Start

### Install

```bash
# Clone this repo
git clone https://github.com/jayis1/the-Dj-music-bot-sidestepping-hermes-instructions.git
cd the-Dj-music-bot-sidestepping-hermes-instructions

# Run the one-shot setup wizard
chmod +x setup.sh run.sh
bash setup.sh
```

### Configure

```bash
nano config.yaml
```

Required settings:
- `guild_id` — Your Discord server ID
- `bot_api_url` — DJ bot Mission Control URL (e.g. `http://192.168.1.50:8080`)
- `hermes_api_key` — Shared API key (generate on the DJ bot with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` and put the same key in both the DJ bot's `.env` and this `config.yaml`)

### Run

```bash
./run.sh
# Or install as systemd service (auto-starts on boot)
sudo systemctl start shadow-controller
```

### Or install as a pip package

```bash
pip install -e .
shadow-controller  # Starts the controller
```

---

## Firefox Setup (on the same VM)

1. **Log into YouTube** — Open Firefox → youtube.com → sign in
2. **Log into Suno** — Open a tab → suno.com → sign in (for Suno Creator)
3. **Install the cookie.txt plugin** — [https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)
4. **Export cookies once** — Click the cookie.txt plugin button (it saves a `cookies.txt` file)
5. **Keep a YouTube Live tab open** — Navigate to your channel's live URL

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│  GUI VM (Debian + XFCE + Firefox)               │
│                                                  │
│  ┌────────────────┐   ┌──────────────────────┐  │
│  │ Firefox        │   │ Shadow Controller    │  │
│  │ (logged into   │◄──►│                      │  │
│  │  YouTube)      │   │  Ollama localhost    │  │
│  │                │   │  hermes3:8b          │  │
│  │  cookie.txt    │   │                      │  │
│  │  plugin ✅     │   │  6 autonomous loops  │  │
│  │                │   │  Playwright browser   │  │
│  │  YT Live tab   │   │  Mission Control API │  │
│  │  (monitoring)  │   │                      │  │
│  └────────────────┘   └──────────┬───────────┘  │
│                                  │ HTTP (LAN)   │
└──────────────────────────────────┼──────────────┘
                                   │
                   ┌───────────────▼───────────────┐
                   │  DJ Bot (LXC / another VM)     │
                   │  Mission Control API :8080      │
                   │  github.com/jayis1/             │
                   │  the-Dj-music-bot-sidestepping- │
                   │  ollama                         │
                   └─────────────────────────────────┘
```

---

## Configuration

Copy `config.example.yaml` → `config.yaml` and fill in your settings.

### Required

| Setting | What | Example |
|---------|------|---------|
| `guild_id` | Your Discord server ID | `"123456789012345678"` |
| `bot_api_url` | DJ bot Mission Control URL | `"http://192.168.1.50:8080"` |
| `hermes_api_key` | Shared Hermes API key (same as DJ bot's `.env`) | `"dGhpcyBpcyBhIHRlc3Q..."` |
| `discord_webhook_url` | Discord webhook for alerts | `"https://discord.com/api/webhooks/..."` |

### Ollama

| Setting | Default | What |
|---------|---------|------|
| `ollama_url` | `http://localhost:11434` | Ollama endpoint — Hermes runs here |
| `ollama_model` | `hermes3:8b` | Model Hermes uses for playlist decisions |

### Music

| Setting | Default | What |
|---------|---------|------|
| `genres` | lo-fi, rap, electro_swing, edm, chill_beats, reggae | Genres Hermes searches YouTube for |
| `min_playlist_songs` | `30` | Minimum track count for a playlist to be worth queuing |
| `queue_min_songs` | `3` | Refill queue when it drops below this |

### Stream

| Setting | Default | What |
|---------|---------|------|
| `stream_should_be_live` | `true` | Should the YouTube Live stream always be running? |
| `stream_check_interval` | `30` | How often to check stream health (seconds) |
| `stream_restart_max_attempts` | `3` | Max auto-restart tries before alerting you |

### Cookies

| Setting | Default | What |
|---------|---------|------|
| `cookie_check_interval` | `300` | How often to check cookie freshness (seconds) |
| `cookie_max_age_days` | `5` | Cookies older than this get auto-refreshed |

### Firefox

| Setting | Default | What |
|---------|---------|------|
| `firefox_profile_path` | auto-detect | Path to Firefox profile with YouTube login |
| `cookie_txt_path` | auto-detect | Where the cookie.txt plugin exports to |
| `youtube_live_url` | blank | Your YouTube Live URL to keep in a browser tab |
| `headless` | `false` | `false` = use GUI Firefox, `true` = invisible |

### Fan Requests (Optional — Disabled by Default)

| Setting | Default | What |
|---------|---------|------|
| `fan_request_enabled` | `false` | Enable Discord fan request watching |
| `discord_watcher_token` | blank | **Separate** Discord bot token (not the DJ bot's) |
| `fan_request_channel_id` | blank | Channel to watch for fan YouTube links |

### Suno Creator (Enabled by Default)

| Setting | Default | What |
|---------|---------|------|
| `suno_enabled` | `true` | Enable original music creation on Suno.com |
| `suno_creation_interval` | `3600` | How often to create a new track (1 hour) |
| `suno_max_pending` | `3` | Max tracks waiting for generation before pausing |
| `suno_auto_queue` | `true` | Auto-queue finished tracks into the DJ bot |

---

## How Each Loop Works

### Cookie Fixer

Hermes keeps the DJ bot's YouTube access alive. Cookies expire, YouTube blocks bots, the bot goes silent. Not on Hermes's watch.

```
Every 5 minutes:
  1. GET /api/hermes/cookies/health → how old are the cookies?
  2. GET /api/ytcookies/auth_status → is YouTube blocking the bot?
  3. If stale or blocked:
     a. Read cookies.txt from the Firefox cookie.txt plugin export
     b. Or extract cookies from the Playwright browser context
     c. POST /api/hermes/cookies/inject → fresh cookies into the DJ bot
     d. Verify auth block is cleared
  4. Alert via Discord webhook if fix succeeded or failed
```

### Queue Watchdog

The station never goes silent. When the queue dips below 3 songs:

```
Every 1 minute:
  1. Check queue depth via Hermes /api/hermes/queue
  2. If queue < 3 songs:
     a. Enable Auto-DJ if not already on
     b. Ask Playlist Finder for a playlist and set it as Auto-DJ source
     c. Load a saved preset as fallback
     d. Replay from recently-played history as last resort
  3. Alert if queue was refilled
```

### Stream Monitor

YouTube Live goes down, viewers leave. Hermes catches it in 30 seconds.

```
Every 30 seconds:
  1. GET /api/<guild_id>/youtube_stream/status → is the stream running?
  2. GET /api/obs/status → is OBS connected and streaming?
  3. If stream is down when it should be live:
     a. POST /api/obs/streaming/start → restart OBS streaming
     b. POST /api/obs/streaming/configure_and_start → full restart
     c. POST /api/<guild_id>/youtube_stream/toggle → toggle stream
  4. If OBS disconnected:
     a. POST /api/obs/reconnect → force reconnect
  5. Keep the YouTube Live browser tab alive
  6. Alert via Discord webhook on any recovery action
```

### Playlist Finder

Hermes browses YouTube like a music director, finding playlists that match your station's vibe.

```
Every 30 minutes:
  1. Pick a genre (rotate: lo-fi, rap, reggae, electro swing, EDM, chill beats)
  2. Navigate YouTube search in the Playwright browser
  3. Extract search results (playlist titles + URLs)
  4. Ask Hermes (via Ollama) to evaluate:
     - 30+ songs? ✅  - Matching genre? ✅  - Recent? ✅
  5. Set best playlist as Auto-DJ source
  6. Cache discovered playlists for the Queue Watchdog
```

### Discord Watcher (Optional)

Watch a Discord channel for fan-posted YouTube links and queue them.

```
On every message in the fan request channel:
  1. Extract YouTube URLs from message text
  2. POST /api/hermes/queue/add → queue it in the DJ bot
  3. React with 🎵 emoji to acknowledge
  4. Alert via Discord webhook
```

**Needs a separate Discord bot token** (not the DJ bot's token). Create one at [Discord Developer Portal](https://discord.com/developers/applications) with Message Content Intent enabled.

### Suno Creator

Hermes creates **original music** on Suno.com. The DJ bot already supports Suno URLs natively — so fresh originals go straight into the queue. Your station plays tracks that no other station has.

```
Every 1 hour:
  1. Generate a song idea:
     a. Ask Hermes for a creative concept (reggae, weed, life themes)
     b. Or pick from 15 preset ideas
  2. Open Suno.com/create in the browser
  3. Fill in prompt + style → click Create
  4. Extract track URL from the page
  5. POST /api/hermes/queue/add → queue the original in the DJ bot
```

---

## Alert System

Hermes keeps you in the loop without spamming:

| Alert | When | Level |
|-------|------|-------|
| 🔴 Cookies expired — auto-refreshing... | Cookies stale or auth blocked | Warning |
| 🟢 Cookies refreshed successfully | Cookie fix worked | Success |
| 🔴 Cookie refresh FAILED | Both extraction methods failed | Error |
| 🟡 Queue running low (N songs) | Queue below threshold | Warning |
| 🔵 Playlist queued (auto-discovery) | New playlist set as Auto-DJ source | Info |
| 🔴 YouTube Live stream is DOWN | Stream died, attempting restart | Error |
| 🟢 Stream restarted | Recovery succeeded | Success |
| 🔴 OBS disconnected | OBS went offline | Error |
| 🔵 Fan request queued | Fan link added to queue | Info |
| 🎵 Suno track submitted | Original track creating on Suno | Info |
| 🎶 Original Suno track queued | Finished Suno track added to DJ bot queue | Info |

Alerts go to **Discord webhook** (instant) + **local log file** (history). Same alert type won't fire twice within 30 seconds (configurable cooldown).

---

## API Endpoints Used

All communication goes through the DJ bot's Hermes Agent API. No modifications to the DJ bot are needed.

| Endpoint | Used By | Purpose |
|----------|---------|---------|
| `GET /api/hermes/state` | All loops | Full bot state |
| `GET /api/hermes/queue` | Queue Watchdog | Queue contents |
| `POST /api/hermes/queue/add` | Queue Watchdog, Discord Watcher, Suno Creator | Queue a song |
| `POST /api/hermes/queue/clear` | Queue Watchdog | Clear queue |
| `POST /api/hermes/skip` | Stream Monitor | Skip current track |
| `GET /api/hermes/cookies/health` | Cookie Fixer | Cookie health |
| `POST /api/hermes/cookies/inject` | Cookie Fixer | Inject fresh cookies |
| `GET /api/obs/status` | Stream Monitor | OBS status |
| `POST /api/obs/streaming/start` | Stream Monitor | Start OBS streaming |
| `POST /api/obs/reconnect` | Stream Monitor | Reconnect to OBS |
| `GET /api/<guild>/youtube_stream/status` | Stream Monitor | Stream status |

---

## File Structure

```
shadow_controller/
├── __init__.py               # Package — all modules exported
├── __main__.py               # Entry point (python -m shadow_controller)
├── main.py                   # Orchestrator — starts all 6 loops
├── api_client.py              # Mission Control API client (Bearer + session auth)
├── browser_manager.py         # Firefox + Playwright + cookie.txt plugin
├── alerts.py                  # Discord webhook + logging
├── cookie_fixer.py            # Loop 1: cookie health + refresh
├── queue_watchdog.py          # Loop 2: keep queue full
├── stream_monitor.py          # Loop 3: YouTube Live + OBS health
├── playlist_finder.py         # Loop 4: Hermes + YouTube discovery
├── discord_watcher.py         # Loop 5: fan requests (optional)
├── suno_creator.py            # Loop 6: Hermes makes original music on Suno
├── systemd/
│   └── shadow-controller.service  # Auto-start on boot
├── config.example.yaml         # Settings template
├── .env.example               # Secret overrides template
├── pyproject.toml              # Package metadata + install config
├── requirements.txt           # Python dependencies (for non-pip installs)
├── setup.sh                   # One-shot setup wizard
└── run.sh                     # Quick start script
```

---

## Related

- **DJ Bot repo:** [the-Dj-music-bot-sidestepping-ollama](https://github.com/jayis1/the-Dj-music-bot-sidestepping-ollama) — the radio station itself
- **Hermes Agent:** [docs.ollama.com/integrations/hermes](https://docs.ollama.com/integrations/hermes) — the AI agent framework
- **Ollama:** [ollama.com](https://ollama.com) — local LLM runtime

## License

MIT — see [LICENSE](LICENSE)