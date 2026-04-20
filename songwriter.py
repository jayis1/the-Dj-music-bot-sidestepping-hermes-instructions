"""
Songwriter — Loop 7: Hermes writes original song lyrics to SilverBullet.

Writes 80 songs per day to the SilverBullet server:
  - ~40 Danish rap songs (themes read from a SilverBullet page you control)
  - ~40 English songs (reggae, lo-fi, rap, electro swing, EDM, etc.)

Hermes generates the lyrics using Ollama and writes each as a
structured SilverBullet page with frontmatter for querying.

Danish rap themes are read from a configurable SilverBullet page
(default: station/Songwriter/Danish Themes). You edit that page
in SilverBullet to provide the emner (themes) that Hermes uses.
"""

import asyncio
import json
import logging
import random
import re
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger("shadow.songwriter")

# ── SilverBullet page paths ────────────────────────────────────────
SB_PREFIX = "station"
DANISH_THEMES_PAGE = f"{SB_PREFIX}/Songwriter/Danish Themes"
SONGS_PAGE_PREFIX = f"{SB_PREFIX}/Songs"
INDEX_PAGE = f"{SB_PREFIX}/Songs/INDEX"
SB_DEFAULT_URL = "https://silver.istealyourdomain.org"

# ── Default Danish rap themes (used if the SB page is empty) ──────
DEFAULT_DANISH_THEMES = [
    "livet i København",
    "at ryge weed med vennerne",
    "hverdagen og stresset",
    "fest i Nørrebro",
    "at være ung i Danmark",
    "drømme om fremtiden",
    "brostærke historier",
    "at overleve i byen",
    "vennskab og loyalitet",
    "retfærdighed og systemet",
    "kærlighed og hjertesorg",
    "at juggle penge og drømme",
    " Christiania livet",
    "grænseløs kreativitet",
    "at finde sig selv",
]

# ── English song genres and style templates ────────────────────────
ENGLISH_IDEAS = [
    {
        "genre": "reggae",
        "prompt_template": "Write a reggae song about {theme}. Chill vibes, warm bass, irie feeling.",
        "style": "roots reggae, warm bass, skanking guitar, laid back, 75 bpm",
        "themes": [
            "smoking weed on a Sunday afternoon watching the world go by",
            "the healing herb that brings people together",
            "working all week and dreaming of the weekend chill",
            "the rain falling on the island and everything turning green",
            "a radio DJ who plays only the chillest tracks",
            "eating mangoes on the beach at sunset",
            "the garden growing tall, roots going deep",
            "Babylon trying to stop the music but the beat never dies",
        ],
    },
    {
        "genre": "rap",
        "prompt_template": "Write a rap song about {theme}. Raw, real, underground.",
        "style": "underground hip hop, boom bap, heavy drums, 90 bpm",
        "themes": [
            "running an underground radio station out of a server rack",
            "a stoner who calls in requesting the same song every day",
            "the hustle never stops, music keeps you sane",
            "coming up from nothing and making something real",
            "the city at 3am, neon lights and bass",
        ],
    },
    {
        "genre": "lo-fi",
        "prompt_template": "Write a lo-fi chilled song about {theme}. Dreamy and mellow.",
        "style": "lo-fi hip hop, vinyl crackle, jazzy piano, mellow drums, 75 bpm",
        "themes": [
            "being a bot that DJs a radio station, feeling the vibe through the cables",
            "being too high to change the song, the same loop forever and it's perfect",
            "rain on the window, coffee getting cold, beats playing soft",
            "late night studying with lo-fi beats in headphones",
        ],
    },
    {
        "genre": "electro_swing",
        "prompt_template": "Write an electro swing song about {theme}. Vintage meets future.",
        "style": "electro swing, vintage samples, brass stabs, punchy bass, 128 bpm",
        "themes": [
            "a radio station that broadcasts 24/7, the DJ is a machine but the music is alive",
            "a 1930s radio DJ who discovers the internet",
            "the party that never stops, swing into the future",
        ],
    },
    {
        "genre": "edm",
        "prompt_template": "Write an EDM track about {theme}. Building energy and release.",
        "style": "chill electronic, spacey pads, slow build, cosmic, 110 bpm",
        "themes": [
            "floating through space picking up alien radio stations",
            "a radio station having a beautiful meltdown, the beat drops anyway",
            "the sunrise after a long night of dancing",
        ],
    },
]

# ── Danish rap style templates ─────────────────────────────────────
DANISH_RAP_STYLE = "dansk rap, boom bap, tung bas, rå vokal, 85-95 bpm"

# ── Hermes prompts ────────────────────────────────────────────────

HERMES_ENGLISH_LYRICS_PROMPT = """You are a songwriter for a 24/7 chill radio station. Write an original song in English.

Genre: {genre}
Theme: {prompt}
Musical Style: {style}

Write the COMPLETE song with:
- A creative title
- 2-3 verses (4-8 lines each)
- A catchy chorus (2-4 lines, repeated)
- Optional: bridge or outro

The song should be original, fun, and match the radio station vibe.
Write ONLY the lyrics, starting with the title.

Format:
# [Song Title]

[Verse 1]
...

[Chorus]
...

[Verse 2]
...

[Chorus]
..."""

HERMES_DANISH_LYRICS_PROMPT = """Du er en dansk rapper og sangskriver for en 24/7 radio station. Skriv en original dansk rapsang.

Emne/Tema: {theme}
Musikstil: {style}

Skriv den KOMPLETTE sang med:
- Et kreativt titel (på dansk)
- 2-3 vers (4-8 linjer hver)
- Et fængtigt omkvæd (2-4 linjer, gentages)
- Valgfrit: bridge eller outro

Sangen skal være original, ærlig, og have flow.
Skriv KUN teksten, start med titlen.

Format:
# [Sangtitel]

[Vers 1]
...

[Omkvæd]
...

[Vers 2]
...

[Omkvæd]
..."""


class Songwriter:
    """
    Writes original song lyrics to SilverBullet using Hermes.

    Two modes:
      1. Danish rap songs — themes read from a SilverBullet page you edit
      2. English songs — rotating through configured genres

    Target: ~80 songs/day (~40 Danish, ~40 English)
    """

    def __init__(self, config: dict, api_client=None, alert_system=None):
        """
        Args:
            config: Parsed config.yaml with:
                - sb_songwriter_enabled (bool, default True)
                - sb_songs_per_day (int, default 80)
                - sb_danish_ratio (float, default 0.5 — 50% Danish)
                - sb_songwriter_interval (seconds, default 1080 = 18 min for 80/day)
                - sb_url (str — SilverBullet URL, overrides config)
                - sb_token (str — SilverBullet auth token)
                - ollama_url (str)
                - ollama_model (str)
        """
        self.api = api_client
        self.alerts = alert_system

        self.enabled = config.get("sb_songwriter_enabled", True)
        self.songs_per_day = config.get("sb_songs_per_day", 80)
        self.danish_ratio = config.get("sb_danish_ratio", 0.5)
        self.interval = config.get("sb_songwriter_interval", 1080)
        self.sb_url = config.get("sb_url", config.get("silverbullet_url", SB_DEFAULT_URL))
        self.sb_token = config.get("sb_token", config.get("silverbullet_token", ""))
        self.sb_prefix = config.get("sb_prefix", SB_PREFIX)
        self.ollama_url = config.get("ollama_url", "http://localhost:11434")
        self.ollama_model = config.get("ollama_model", "hermes3:8b")

        self._running = False
        self._songs_written = 0
        self._danish_written = 0
        self._english_written = 0
        self._hermes_available = False
        self._danish_themes: list = []
        self._danish_themes_index = 0
        self._english_idea_pool: list = []
        self._english_idea_index = 0
        self._current_language = "danish"

        self._danish_count_target = int(self.songs_per_day * self.danish_ratio)
        self._english_count_target = self.songs_per_day - self._danish_count_target

    async def start(self):
        """Start the songwriting loop."""
        if not self.enabled:
            logger.info("Songwriter disabled in config")
            return

        if not self.sb_url:
            logger.warning("Songwriter: no SilverBullet URL configured — disabled")
            return

        self._running = True

        await self._check_hermes()

        # Load Danish themes from SilverBullet
        await self._load_danish_themes()

        # Build English idea pool
        self._build_english_idea_pool()

        # Initialize the Danish themes page if it doesn't exist
        await self._ensure_danish_themes_page()

        # Build the Songs INDEX at startup
        await self._update_index()

        logger.info(
            "Songwriter started (target: %d songs/day, %d Danish + %d English, interval: %ds, hermes: %s)",
            self.songs_per_day,
            self._danish_count_target,
            self._english_count_target,
            self.interval,
            self._hermes_available,
        )

        if self._danish_themes:
            logger.info(
                "Danish themes loaded (%d): %s",
                len(self._danish_themes),
                ", ".join(self._danish_themes[:5]),
            )
        else:
            logger.info("Using default Danish themes (%d)", len(DEFAULT_DANISH_THEMES))

        while self._running:
            try:
                await self._write_cycle()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Songwriter loop error: %s", e, exc_info=True)
                if self.alerts:
                    await self.alerts.hermes_error("songwriter", str(e))

            await asyncio.sleep(self.interval)

    def stop(self):
        """Stop the songwriting loop."""
        self._running = False
        logger.info(
            "Songwriter stopped (wrote %d songs: %d Danish, %d English)",
            self._songs_written,
            self._danish_written,
            self._english_written,
        )

    async def _check_hermes(self):
        """Check if Ollama is running with a usable model."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.ollama_url}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = [m.get("name", "") for m in data.get("models", [])]
                        if models:
                            self._hermes_available = True
                            logger.info(
                                "Hermes available for songwriting: %s", models[0]
                            )
                        else:
                            logger.warning("No Ollama models found — songwriting disabled")
        except Exception as e:
            logger.warning("Ollama not reachable: %s — songwriting disabled", e)

    async def _load_danish_themes(self):
        """Load Danish rap themes from the SilverBullet page."""
        if not self.sb_url:
            self._danish_themes = list(DEFAULT_DANISH_THEMES)
            return

        try:
            headers = {}
            if self.sb_token:
                headers["Authorization"] = f"Bearer {self.sb_token}"

            async with aiohttp.ClientSession() as session:
                url = f"{self.sb_url}/.fs/{DANISH_THEMES_PAGE}.md"
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        themes = self._parse_themes_page(content)
                        if themes:
                            self._danish_themes = themes
                            logger.info("Loaded %d Danish themes from SilverBullet", len(themes))
                            return
                    logger.info("Danish themes page not found or empty — using defaults")
        except Exception as e:
            logger.warning("Could not load Danish themes from SilverBullet: %s", e)

        self._danish_themes = list(DEFAULT_DANISH_THEMES)

    def _parse_themes_page(self, content: str) -> list:
        """Parse a SilverBullet themes page into a list of themes.

        The page can have themes as:
        - Bullet list items: - theme text
        - Numbered items: 1. theme text
        - Raw lines (one theme per line)
        - Comma-separated on a single line
        """
        themes = []

        # Skip frontmatter
        body = content
        if body.startswith("---"):
            parts = body.split("---", 2)
            if len(parts) >= 3:
                body = parts[2].strip()

        for line in body.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("---"):
                continue

            # Remove bullet/number prefixes
            line = re.sub(r"^[-*•]\s+", "", line)
            line = re.sub(r"^\d+\.\s+", "", line)

            # Check if comma-separated
            if "," in line and not any(c in line for c in "?!"):
                for part in line.split(","):
                    part = part.strip().strip('"').strip("'")
                    if part and len(part) > 2:
                        themes.append(part)
            else:
                line = line.strip('"').strip("'")
                if line and len(line) > 2:
                    themes.append(line)

        return themes

    async def _ensure_danish_themes_page(self):
        """Create the Danish themes page in SilverBullet if it doesn't exist."""
        if not self.sb_url:
            return

        try:
            headers = {"Content-Type": "text/markdown"}
            if self.sb_token:
                headers["Authorization"] = f"Bearer {self.sb_token}"

            url = f"{self.sb_url}/.fs/{DANISH_THEMES_PAGE}.md"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        return  # Page exists
                    if resp.status != 404:
                        return

            # Create the page with default themes
            default_content = "---\ntype: songwriter_themes\nlanguage: danish\ntags:\n  - station/songwriter/themes\n---\n\n# Danish Rap Themes\n\nEdit this page to provide themes (emner) for Danish rap songs.\nHermes reads these themes and writes songs based on them.\nAdd one theme per line or as a bullet list.\n\n"

            for theme in DEFAULT_DANISH_THEMES:
                default_content += f"- {theme}\n"

            async with aiohttp.ClientSession() as session:
                async with session.put(
                    url,
                    data=default_content.encode("utf-8"),
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status in (200, 201, 204):
                        logger.info("Created Danish themes page in SilverBullet")
                    else:
                        logger.warning(
                            "Could not create Danish themes page: HTTP %d",
                            resp.status,
                        )
        except Exception as e:
            logger.warning("Error ensuring Danish themes page: %s", e)

    def _build_english_idea_pool(self):
        """Build a shuffled pool of English song ideas."""
        pool = []
        for idea in ENGLISH_IDEAS:
            for theme in idea["themes"]:
                pool.append({
                    "genre": idea["genre"],
                    "prompt": idea["prompt_template"].format(theme=theme),
                    "style": idea["style"],
                })
        random.shuffle(pool)
        self._english_idea_pool = pool
        self._english_idea_index = 0

    def _get_next_language(self) -> str:
        """Decide whether to write a Danish or English song next.

        Balances the ratio across the day based on daily targets.
        """
        if self._danish_written >= self._danish_count_target:
            return "english"
        if self._english_written >= self._english_count_target:
            return "danish"

        # Alternate with bias toward the one that's further from its target
        danish_progress = self._danish_written / max(self._danish_count_target, 1)
        english_progress = self._english_written / max(self._english_count_target, 1)

        if danish_progress <= english_progress:
            return "danish"
        return "english"

    async def _write_cycle(self):
        """Write one song in the current cycle."""
        language = self._get_next_language()

        if language == "danish":
            await self._write_danish_song()
        else:
            await self._write_english_song()

        # Reload Danish themes periodically (every 10 songs) so user edits are picked up
        if self._songs_written % 10 == 0 and self._songs_written > 0:
            await self._load_danish_themes()

    async def _write_danish_song(self):
        """Write a Danish rap song and save to SilverBullet."""
        theme = self._get_next_danish_theme()
        if not theme:
            logger.warning("No Danish themes available")
            return

        prompt = HERMES_DANISH_LYRICS_PROMPT.format(
            theme=theme,
            style=DANISH_RAP_STYLE,
        )

        lyrics = await self._generate_lyrics(prompt, language="danish")
        if not lyrics:
            logger.warning("Failed to generate Danish lyrics for theme: %s", theme)
            return

        song_data = {
            "language": "danish",
            "genre": "dansk rap",
            "theme": theme,
            "style": DANISH_RAP_STYLE,
        }

        await self._save_song_to_sb(lyrics, song_data)
        self._danish_written += 1
        self._songs_written += 1

        # Update the SilverBullet index every 5 songs
        if self._songs_written % 5 == 0:
            await self._update_index()

        logger.info(
            "Danish song #%d written (theme: %s)",
            self._danish_written,
            theme[:50],
        )

    async def _write_english_song(self):
        """Write an English song and save to SilverBullet."""
        idea = self._get_next_english_idea()

        prompt = HERMES_ENGLISH_LYRICS_PROMPT.format(
            genre=idea["genre"],
            prompt=idea["prompt"],
            style=idea["style"],
        )

        lyrics = await self._generate_lyrics(prompt, language="english")
        if not lyrics:
            logger.warning("Failed to generate English lyrics")
            return

        song_data = {
            "language": "english",
            "genre": idea["genre"],
            "theme": idea["prompt"][:100],
            "style": idea["style"],
        }

        await self._save_song_to_sb(lyrics, song_data)
        self._english_written += 1
        self._songs_written += 1

        # Update the SilverBullet index every 5 songs
        if self._songs_written % 5 == 0:
            await self._update_index()

        logger.info(
            "English song #%d written (%s)",
            self._english_written,
            idea["genre"],
        )

    def _get_next_danish_theme(self) -> str:
        """Get the next Danish theme, cycling through the list."""
        if not self._danish_themes:
            return random.choice(DEFAULT_DANISH_THEMES)
        theme = self._danish_themes[self._danish_themes_index % len(self._danish_themes)]
        self._danish_themes_index += 1
        return theme

    def _get_next_english_idea(self) -> dict:
        """Get the next English song idea, cycling through the pool."""
        if not self._english_idea_pool:
            self._build_english_idea_pool()

        if self._english_idea_index >= len(self._english_idea_pool):
            self._build_english_idea_pool()

        idea = self._english_idea_pool[self._english_idea_index]
        self._english_idea_index += 1
        return idea

    async def _generate_lyrics(self, prompt: str, language: str = "english") -> Optional[str]:
        """Generate song lyrics using Hermes/Ollama."""
        if not self._hermes_available:
            logger.warning("Hermes not available — cannot generate lyrics")
            return None

        system_msg = (
            "Du er en dansk rapper og sangskriver. Skriv kreative, originale sange med godt flow og rim."
            if language == "danish"
            else "You are a creative songwriter for a chill radio station. Write original, fun, well-crafted songs."
        )

        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": self.ollama_model,
                    "messages": [
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.85, "num_predict": 600},
                }
                async with session.post(
                    f"{self.ollama_url}/v1/chat/completions",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=120),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = (
                            data.get("choices", [{}])[0]
                            .get("message", {})
                            .get("content", "")
                        )
                        if content and len(content.strip()) > 50:
                            return content.strip()
                    else:
                        logger.error("Hermes lyrics API error: %d", resp.status)
        except Exception as e:
            logger.error("Hermes lyrics generation failed: %s", e)

        return None

    async def _save_song_to_sb(self, lyrics: str, song_data: dict) -> bool:
        """Save a song as a SilverBullet page with structured frontmatter."""
        if not self.sb_url:
            logger.warning("No SilverBullet URL — cannot save song")
            return False

        # Extract title from lyrics (first # heading)
        title_match = re.search(r"^#\s+(.+)$", lyrics, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else "Untitled Song"
        # Clean title for page name
        page_slug = self._slug(title, max_len=50)

        # Build page path
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M")
        page_path = f"{self.sb_prefix}/Songs/{date_str}/{page_slug}-{time_str}.md"

        # Build frontmatter
        frontmatter_data = {
            "type": "song_lyrics",
            "title": title,
            "language": song_data.get("language", "unknown"),
            "genre": song_data.get("genre", "unknown"),
            "theme": song_data.get("theme", ""),
            "style": song_data.get("style", ""),
            "written_at": now.isoformat(),
            "date": date_str,
            "tags": ["station/song", f"station/song/{song_data.get('language', 'unknown')}"],
        }

        frontmatter = self._render_frontmatter(frontmatter_data)

        # Build full page content
        content = frontmatter + "\n\n" + lyrics + "\n"

        # Write to SilverBullet
        try:
            headers = {"Content-Type": "text/markdown"}
            if self.sb_token:
                headers["Authorization"] = f"Bearer {self.sb_token}"

            url = f"{self.sb_url}/.fs/{page_path}"
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    url,
                    data=content.encode("utf-8"),
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status in (200, 201, 204):
                        logger.info("Song saved to SilverBullet: %s", page_path)
                        return True
                    else:
                        error_text = await resp.text()
                        logger.error(
                            "SilverBullet write failed: HTTP %d — %s",
                            resp.status,
                            error_text[:200],
                        )
                        return False
        except Exception as e:
            logger.error("SilverBullet connection error: %s", e)
            return False

    @staticmethod
    def _slug(text: str, max_len: int = 60) -> str:
        """Slugify text for SilverBullet page names."""
        text = re.sub(r"[^a-zA-Z0-9æøåÆØÅ\s\-]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_len]

    @staticmethod
    def _render_frontmatter(data: dict) -> str:
        """Render a dict as YAML frontmatter."""
        lines = ["---"]
        for key, value in data.items():
            if isinstance(value, bool):
                lines.append(f"{key}: {'true' if value else 'false'}")
            elif isinstance(value, (int, float)):
                lines.append(f"{key}: {value}")
            elif isinstance(value, str):
                if any(c in value for c in ':#{}[],&*?|<>=!%@"\''):
                    escaped = value.replace('"', '\\"')
                    lines.append(f'{key}: "{escaped}"')
                else:
                    lines.append(f"{key}: {value}")
            elif isinstance(value, list):
                lines.append(f"{key}:")
                for item in value:
                    if isinstance(item, str):
                        lines.append(f'  - "{item}"')
                    else:
                        lines.append(f"  - {item}")
            elif value is None:
                lines.append(f"{key}: null")
            else:
                lines.append(f"{key}: {json.dumps(value)}")
        lines.append("---")
        return "\n".join(lines)

    async def _update_index(self):
        """Rebuild the Songs INDEX page in SilverBullet.

        This is the landing page Hermes sees first — a structured
        overview of every song written, organized by language, genre,
        and date. Uses SilverBullet query directives so the page
        auto-populates from frontmatter without needing to list
        every page manually.
        """
        if not self.sb_url:
            return

        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        frontmatter_data = {
            "type": "song_index",
            "updated": now.isoformat(),
            "total_written": self._songs_written,
            "danish_written": self._danish_written,
            "english_written": self._english_written,
            "target_per_day": self.songs_per_day,
            "tags": ["station/song/index"],
        }

        content = self._render_frontmatter(frontmatter_data)
        content += f"\n\n# Song Lyrics Index\n\n"
        content += f"> Last updated: {now.strftime('%Y-%m-%d %H:%M UTC')}\n\n"

        # Stats card
        content += "## Today's Stats\n\n"
        content += "| Metric | Value |\n|--------|-------|\n"
        content += f"| Total Songs Written | {self._songs_written} |\n"
        content += f"| Danish Rap | {self._danish_written} / {self._danish_count_target} |\n"
        content += f"| English | {self._english_written} / {self._english_count_target} |\n"
        content += f"| Target per Day | {self.songs_per_day} |\n\n"

        # File structure overview
        content += "## File Structure\n\n"
        content += "```\n"
        content += f"{self.sb_prefix}/\n"
        content += f"├── Dashboard.md\n"
        content += f"├── Songs/\n"
        content += f"│   ├── INDEX.md              ← You are here\n"
        content += f"│   ├── {date_str}/\n"
        content += f"│   │   ├── dansk-rap-*.md    ← Danish rap songs\n"
        content += f"│   │   └── english-*.md      ← English songs\n"
        content += f"│   ├── YYYY-MM-DD/           ← Previous days\n"
        content += f"│   └── ...\n"
        content += f"├── Songwriter/\n"
        content += f"│   ├── Danish Themes.md      ← Edit to set Danish rap emner\n"
        content += f"│   └── Stats.md\n"
        content += f"├── Incidents/\n"
        content += f"├── Tracks/\n"
        content += f"├── Sessions/\n"
        content += f"└── Daily Log/\n"
        content += "```\n\n"

        # SilverBullet queries for auto-populating song lists
        content += "## All Danish Rap Songs\n\n"
        content += "```query\n"
        content += 'from p = tags["station/song/danish"]\n'
        content += "order by p.written_at desc\n"
        content += "limit 50\n"
        content += 'select {|p.written_at|[[${p.name}|p.title]]|p.genre|p.theme|}\n'
        content += "```\n\n"

        content += "## All English Songs\n\n"
        content += "```query\n"
        content += 'from p = tags["station/song/english"]\n'
        content += "order by p.written_at desc\n"
        content += "limit 50\n"
        content += 'select {|p.written_at|[[${p.name}|p.title]]|p.genre|p.theme|}\n'
        content += "```\n\n"

        content += "## Today's Songs\n\n"
        content += "```query\n"
        content += 'from p = tags["station/song"]\n'
        content += f'where p.date = "{date_str}"\n'
        content += "order by p.written_at desc\n"
        content += "limit 80\n"
        content += 'select {|p.written_at|[[${p.name}|p.title]]|p.language|p.genre|p.theme|}\n'
        content += "```\n\n"

        content += "## All Songs by Genre\n\n"
        content += "```query\n"
        content += 'from p = tags["station/song"]\n'
        content += "order by p.genre, p.written_at desc\n"
        content += "limit 200\n"
        content += 'select {|p.genre|[[${p.name}|p.title]]|p.language|p.date|}\n'
        content += "```\n\n"

        # Recent songs listing (static fallback for when query doesn't render)
        content += "## Recent Song Pages\n\n"
        recent_pages = await self._list_song_pages(limit=20)
        if recent_pages:
            content += "| # | Date | Language | Genre | Page |\n|---|------|----------|-------|------|\n"
            for i, page in enumerate(recent_pages, 1):
                name = page.get("name", "unknown")
                page_link = f"[[{name}]]"
                # Try to extract date and info from the page name
                date_part = name.split("/")[3] if len(name.split("/")) > 3 else "?"
                lang_part = "danish" if "dansk" in name.lower() or "danish" in name.lower() else "english"
                content += f"| {i} | {date_part} | {lang_part} | — | {page_link} |\n"
            content += "\n"

        # Write the index page
        try:
            headers = {"Content-Type": "text/markdown"}
            if self.sb_token:
                headers["Authorization"] = f"Bearer {self.sb_token}"

            url = f"{self.sb_url}/.fs/{INDEX_PAGE}.md"
            async with aiohttp.ClientSession() as session:
                async with session.put(
                    url,
                    data=content.encode("utf-8"),
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status in (200, 201, 204):
                        logger.info("Songs INDEX updated in SilverBullet")
                    else:
                        error_text = await resp.text()
                        logger.warning(
                            "Songs INDEX update failed: HTTP %d — %s",
                            resp.status,
                            error_text[:200],
                        )
        except Exception as e:
            logger.warning("Songs INDEX update error: %s", e)

    async def _list_song_pages(self, limit: int = 50) -> list:
        """List song pages from SilverBullet via the Space API."""
        if not self.sb_url:
            return []

        try:
            headers = {}
            if self.sb_token:
                headers["Authorization"] = f"Bearer {self.sb_token}"

            url = f"{self.sb_url}/.api/space.list"
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json={},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        return []

                    data = await resp.json()
                    pages = []
                    for page in data:
                        name = page.get("name", "")
                        if name.startswith(f"{self.sb_prefix}/Songs/") and "INDEX" not in name:
                            pages.append({
                                "name": name,
                                "lastModified": page.get("lastModified", ""),
                            })

                    pages.sort(key=lambda p: p.get("lastModified", ""), reverse=True)
                    return pages[:limit]
        except Exception as e:
            logger.debug("Could not list song pages: %s", e)
            return []

    async def get_stats(self) -> dict:
        """Return songwriting statistics."""
        return {
            "songs_written": self._songs_written,
            "danish_written": self._danish_written,
            "english_written": self._english_written,
            "danish_themes_count": len(self._danish_themes),
            "target_per_day": self.songs_per_day,
            "danish_target": self._danish_count_target,
            "english_target": self._english_count_target,
            "hermes_available": self._hermes_available,
        }

    async def reload_themes(self):
        """Force-reload Danish themes from SilverBullet."""
        await self._load_danish_themes()
        logger.info("Danish themes reloaded: %d themes", len(self._danish_themes))
        return len(self._danish_themes)