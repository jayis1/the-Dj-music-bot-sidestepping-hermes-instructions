# Shadow Controller — Hermes-powered DJ Bot Operator

> **The silent operator behind the 420 Radio DJ.**

A Python service that autonomously manages the DJ bot — fixing cookies,
keeping the queue full, watching the stream, picking up fan requests —
all through the DJ bot's existing Mission Control API.

## What It Does

| Loop | What | Interval |
|------|------|----------|
| **Cookie Fixer** | Detects stale/blocked YouTube cookies, extracts fresh ones from Firefox cookie.txt plugin, injects via API | 5 min |
| **Queue Watchdog** | Monitors queue depth, enables Auto-DJ and discovers playlists when queue runs dry | 1 min |
| **Stream Monitor** | Watches YouTube Live stream + OBS health, auto-restarts if stream dies | 30 sec |
| **Playlist Finder** | Uses Hermes (Ollama) to browse YouTube and discover playlists matching your station vibe | 30 min |
| **Discord Watcher** | *Optional* — Listens for fan YouTube links in Discord, queues them automatically | Disabled by default |

## Architecture

```
┌──────────────────────────────────────────────┐
│  GUI VM (Debian + XFCE + Firefox)            │
│                                              │
│  Firefox ←── logged into YouTube            │
│  Firefox ←── cookie.txt plugin installed     │
│  Firefox ←── YT Live tab open                │
│                                              │
│  Ollama ←── hermes3:8b model (cloud-signed)  │
│                                              │
│  shadow_controller/                          │
│    main.py          orchestrator             │
│    cookie_fixer.py  Loop 1                   │
│    queue_watchdog.py Loop 2                  │
│    stream_monitor.py Loop 3                 │
│    playlist_finder.py Loop 4                │
│    discord_watcher.py Loop 5                 │
│    api_client.py    Mission Control API      │
│    browser_manager.py  Firefox + Playwright   │
│    alerts.py        Discord webhook + logs   │
└──────────────┬───────────────────────────────┘
               │ HTTP (LAN)
               ▼
┌──────────────────────────────────────────────┐
│  DJ Bot LXC (Proxmox)                        │
│  Mission Control API :8080                    │
└──────────────────────────────────────────────┘
```

## Quick Setup

```bash
cd shadow_controller/

# 1. Run the setup wizard
bash setup.sh

# 2. Edit config.yaml with your settings
nano config.yaml

# 3. Log into YouTube in Firefox
#    Open Firefox → youtube.com → log in

# 4. Install the cookie.txt Firefox plugin
#    https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/

# 5. Export cookies once (click the plugin button)

# 6. Start the shadow controller
./run.sh
```

## Or as a systemd service

```bash
# Install (done by setup.sh if you answer yes)
sudo systemctl enable --now shadow-controller

# Check status
sudo systemctl status shadow-controller

# View logs
sudo journalctl -u shadow-controller -f
```

## Configuration

All settings live in `config.yaml`. See `config.example.yaml` for the full list.

### Required

| Setting | What |
|---------|------|
| `guild_id` | Your Discord server ID |
| `bot_api_url` | DJ bot Mission Control URL (e.g. `http://192.168.1.50:8080`) |
| `discord_webhook_url` | Discord webhook URL for alerts |

### Optional (Fan Requests — Disabled by Default)

| Setting | What |
|---------|------|
| `fan_request_enabled` | Set to `true` to enable Discord fan request watching |
| `discord_watcher_token` | Separate Discord bot token (not the DJ bot's token) |
| `fan_request_channel_id` | Channel ID to watch for fan YouTube links |

### Key Optional

| Setting | Default | What |
|---------|---------|------|
| `ollama_url` | `http://localhost:11434` | Ollama endpoint (same VM) |
| `ollama_model` | `hermes3:8b` | Model for playlist discovery reasoning |
| `genres` | lo-fi, rap, electro_swing, edm, chill_beats | Music discovery targets |
| `stream_should_be_live` | `true` | Monitor YouTube Live stream |
| `cookie_max_age_days` | `5` | Refresh cookies older than this |
| `queue_min_songs` | `3` | Refill queue when below this |

## Cookie Flow

```
Cookie Fixer detects stale cookies
    │
    ├──► Method 1: Read cookies.txt from Firefox plugin
    │    (plugin exports Netscape-format file when you click it)
    │
    ├──► Method 2: Extract from Playwright browser context
    │    (navigates to YouTube, grabs cookies via Playwright API)
    │
    └──► POST /api/ytcookies/inject → DJ bot reloads cookies
         → yt-dlp uses fresh cookies → music plays again
```

## Alert Flow

```
Something needs attention
    │
    ├──► Discord webhook (instant notification to your phone)
    │    🔵 Info / 🟡 Warning / 🔴 Error / 🟢 Success
    │
    └──► shadow_controller.log (persistent local log)
```

## Music Discovery

The Playlist Finder uses Hermes (via Ollama) to decide which YouTube
playlists are worth queuing:

1. Search YouTube for playlists matching configured genres
2. Extract search results (titles + URLs)
3. Ask Hermes to pick the best ones (30+ songs, matching genre, recent)
4. Set as Auto-DJ source or queue directly

## Fan Requests (Optional — Disabled by Default)

The Discord Watcher can listen to a specific channel for YouTube links.
**Needs a separate Discord bot token** — the DJ bot's token can't be reused.

To enable:
1. Create a new Discord bot at https://discord.com/developers/applications
2. Enable Message Content Intent (Privileged Intents)
3. Set `fan_request_enabled: true` in config.yaml
4. Fill in `discord_watcher_token` and `fan_request_channel_id`

When a fan posts a link:

1. Extract YouTube URL from message
2. Validate it's a video or playlist
3. Queue via `POST /api/<guild_id>/play`
4. React with 🎵 emoji to acknowledge
5. Send alert via Discord webhook