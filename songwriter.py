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
INDEX_PAGE = f"{SB_PREFIX}/Dashboard"

# SilverBullet push interval — how often the dashboard pusher
# flushes the outbox and updates the dashboard (seconds)
SB_PUSH_INTERVAL = 30
SB_DEFAULT_URL = "https://silverbullet.istealyourdomain.org"

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

HERMES_ENGLISH_LYRICS_PROMPT = """You are a songwriter and producer for a 24/7 chill radio station. Write a COMPLETE original song in English.

Genre: {genre}
Theme: {prompt}
Musical Style: {style}

Write the song as a FULL production script — not just lyrics. Include:
- Production cues in brackets [like this] describing instruments, sounds, effects
- Vocal samples, ad-libs, and spoken word bits in [Vocal sample: "..."] tags
- Sound effects and transitions like [Bass drops deep], [Vinyl crackle], [Drums kick in]
- Instrument directions like [Drums stay steady, guitar skanks soaked in reverb]
- Dynamics like [Bass swells and distorts slightly], [Rhythm slows down drastically]
- Section markers: [Intro], [Chorus], [Verse 1], [Bridge], [Outro], etc.
- Every lyric line should have musical context around it

Structure:
1. [Intro] — Set the mood with ambient sounds, establish the groove
2. [Chorus] — The hook (2-4 lines with production cues)
3. [Verse 1] — (4-8 lines with instrument/sound descriptions between lines)
4. [Chorus] — (reprise, maybe with a variation like [Vocal layers start to overlap])
5. [Verse 2] — (4-8 lines, maybe a beat switch or new instrument enters)
6. [Chorus] — (full energy)
7. [Verse 3] — (optional, maybe strip back the beat then crash back in)
8. [Outro] — Slow down, fade, or end with a signature sound

Be creative with production — this is a radio station, make it sound ALIVE.

Format:
# [Song Title]

[Intro:] Production sounds and mood setting
[First instrument enters]

[Chorus]
[Production cue]
Lyrics
[Sound effect or transition]

[Verse 1]
[Instrument direction]
Lyrics
[Sound effect between lines]
Lyrics
[Transition or bass drop]

[Chorus]
Lyrics [Effect like Echo]
[Production variation]

[Verse 2]
[Beat change or new instrument]
Lyrics
[Pause or breakdown]
Lyrics
[Bass swells]

[Chorus]
Lyrics
[Full energy production]

[Outro]
[Rhythm slows down]
[Final vocal or sample]
[Last sound effect to finish]
"""

HERMES_DANISH_LYRICS_PROMPT = """Du er en dansk rapper, producer og sangskriver for en 24/7 radio station. Skriv en KOMPLET dansk rapsang som et fuldt produktionsscript.

Emne/Tema: {theme}
Musikstil: {style}

Skriv sangen som et FULDT produktionsscript — ikke kun tekst. Inkluder:
- Produktion cues i parenteser [som her] der beskriver instrumenter, lyde, effekter
- Vokal samples, ad-libs og talt tekst i [Vokal sample: "..."] tags
- Lydeffekter og overgange som [Bas dropper dybt], [Vinyl krøs], [Trommer kicker ind]
- Instrument retninger som [Trommer holder stødt, guitar skanker i reverb]
- Dynamik som [Bas svulmer og forvrænger let], [Rytmen sænker drastisk]
- Sektion markører: [Intro], [Omkvæd], [Vers 1], [Bridge], [Outro] osv.
- Hver tekstlinje skal have musikalsk kontekst omkring sig

Struktur:
1. [Intro] — Skab stemningen med ambient lyde, etabler grooven
2. [Omkvæd] — Hjørnet (2-4 linjer med produktion cues)
3. [Vers 1] — (4-8 linjer med instrument/lyd beskrivelser mellem linjerne)
4. [Omkvæd] — (reprise, måske med en variation som [Vokal lag begynder at overlappe])
5. [Vers 2] — (4-8 linjer, måske et beat skift eller nyt instrument kommer ind)
6. [Omkvæd] — (fuld energi)
7. [Vers 3] — (valgfrit, måske strip beats ned og crash tilbage)
8. [Outro] — Slå ned, fade, eller afslut med en signatur lyd

Vær kreativ med produktionen — dette er en radiostation, få det til at lyde LEVENDE.

Format:
# [Sangtitel]

[Intro:] Produktion lyde og stemning
[Første instrument kommer ind]

[Omkvæd]
[Produktion cue]
Tekst
[Lydeffekt eller overgang]

[Vers 1]
[Instrument retning]
Tekst
[Lydeffekt mellem linjerne]
Tekst
[Overgang eller bas drop]

[Omkvæd]
Tekst [Effekt som Ekko]
[Produktion variation]

[Vers 2]
[Beat ændring eller nyt instrument]
Tekst
[Pause eller breakdown]
Tekst
[Bas svulmer]

[Omkvæd]
Tekst
[Fuld energi produktion]

[Outro]
[Rytmen sænkes]
[Sidste vokal eller sample]
[Sidste lydeffekt for at afslutte]
"""


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

        # Outbox: songs queued for SilverBullet push
        # Each entry: {"page_path": str, "content": str, "song_data": dict}
        self._outbox: list = []

        # Background task for the dashboard pusher loop
        self._push_task = None

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

        # Build the Dashboard at startup
        await self._update_index()

        # Start the dashboard pusher — flushes outbox to SilverBullet
        # and updates the dashboard on a regular cadence
        self._push_task = asyncio.create_task(
            self._push_loop(), name="songwriter-push"
        )

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
        """Stop the songwriting loop and the dashboard pusher."""
        self._running = False
        if self._push_task and not self._push_task.done():
            self._push_task.cancel()
        # Final flush — push any remaining songs to SilverBullet
        if self._outbox:
            logger.info("Flushing %d remaining songs to SilverBullet", len(self._outbox))
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
            "Du er en dansk rapper, producer og sangskriver. Skriv kreative, originale sange med godt flow og rim. "
            "Inkluder altid produktion cues [i parenteser] med instrument retninger, lydeffekter, dynamik og overgange. "
            "Sangen skal lyde som et færdigt produktionsscript — ikke kun tekst."
            if language == "danish"
            else "You are a creative songwriter and producer for a chill radio station. Write original, fun, well-crafted songs "
            "with FULL production scripts. Always include production cues [in brackets] describing instruments, sounds, "
            "effects, dynamics, and transitions. The song should read like a complete production script — not just lyrics."
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
                    "options": {"temperature": 0.85, "num_predict": 1200},
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
        """Queue a song for the dashboard pusher to write to SilverBullet.

        Instead of writing directly, this puts the song into an outbox
        queue. The dashboard pusher loop (_push_loop) flushes the outbox
        periodically — writing all queued songs as individual pages and
        then refreshing the Dashboard.
        """
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

        # Enqueue for the dashboard pusher
        self._outbox.append({
            "page_path": page_path,
            "content": content,
            "song_data": song_data,
            "title": title,
            "queued_at": now.isoformat(),
        })

        logger.info("Song queued for SilverBullet: %s", page_path)
        return True

    async def _push_loop(self):
        """Background loop that flushes the outbox to SilverBullet.

        Every SB_PUSH_INTERVAL seconds, this loop:
        1. Writes all queued songs as individual SilverBullet pages
        2. Updates the Dashboard with new stats

        This centralizes all SilverBullet writes through one pipeline,
        so the songwriting loop never blocks on network I/O.
        """
        while self._running:
            await asyncio.sleep(SB_PUSH_INTERVAL)

            if not self._outbox:
                continue

            # Drain the outbox
            batch = self._outbox.copy()
            self._outbox.clear()

            logger.info("Dashboard pusher: flushing %d songs to SilverBullet", len(batch))

            for item in batch:
                success = await self._write_page_to_sb(
                    item["page_path"], item["content"]
                )
                if success:
                    logger.info("Wrote song page: %s", item["page_path"])
                else:
                    # Re-queue failed writes at the front
                    logger.warning("Failed to write song page, re-queuing: %s", item["page_path"])
                    self._outbox.insert(0, item)

            # Update the Dashboard after flushing songs
            await self._update_index()

    async def _write_page_to_sb(self, page_path: str, content: str) -> bool:
        """Write a single page to SilverBullet using the FS API."""
        if not self.sb_url:
            return False

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
                        return True
                    else:
                        error_text = await resp.text()
                        logger.error(
                            "SilverBullet write failed for %s: HTTP %d — %s",
                            page_path, resp.status, error_text[:200],
                        )
                        return False
        except Exception as e:
            logger.error("SilverBullet connection error writing %s: %s", page_path, e)
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
        """Rebuild the SilverBullet Dashboard — the landing page.

        This is the first page you see when opening SilverBullet.
        It's both a navigation guide for the human operator and a
        context map that the Hermes agent references when deciding
        where to write, what themes to use, and what exists already.

        The page uses SilverBullet [[wiki links]] for clickable
        navigation and query directives for live song tables.
        """
        if not self.sb_url:
            return

        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M")

        frontmatter_data = {
            "type": "dashboard",
            "updated": now.isoformat(),
            "total_written": self._songs_written,
            "danish_written": self._danish_written,
            "english_written": self._english_written,
            "target_per_day": self.songs_per_day,
            "tags": ["station/dashboard"],
        }

        content = self._render_frontmatter(frontmatter_data)
        content += """

# 🎙️ The 420 Radio — SilverBullet Server

> *This is the Hermes agent's home base. Everything the station needs
> lives here — songs, themes, logs, incidents. Navigate by clicking
> the [[wiki links]] below or use the SilverBullet sidebar.*

---

## 🧭 How to Navigate This Server

This SilverBullet workspace is organized into sections. Each section
is a folder of pages. Click any link below to jump there.

### For the Human Operator (You)

| Where | What | Link |
|-------|------|------|
| **Dashboard** | You are here. Overview of everything. | [[station/Dashboard]] |
| **Danish Themes** | Edit this page to set the emner (themes) for Danish rap songs. Add one theme per line or as a bullet list. Hermes reads it automatically. | [[station/Songwriter/Danish Themes]] |
| **Today's Songs** | All songs written today, newest first. | [[station/Songs/INDEX]] |
| **Danish Rap Songs** | Every dansk rap song with full lyrics and production cues. | see query below |
| **English Songs** | Every English song with full lyrics and production cues. | see query below |
| **Song Stats** | How many songs written today, targets, progress. | see stats below |

### For the Hermes Agent

When Hermes writes a song, it follows this workflow:

1. **Read themes** → [[station/Songwriter/Danish Themes]] for Danish emner, or picks from built-in English themes
2. **Pick language** → Alternates Danish/English to hit the daily target ratio
3. **Generate lyrics** → Uses Ollama with a production-script prompt (intros, sound effects, instrument cues)
4. **Write the page** → Creates `station/Songs/YYYY-MM-DD/Title-HHMM.md` with frontmatter tags
5. **Update this dashboard** → Rebuilds this page every 5 songs to reflect current stats

Hermes tags every song page so queries can find them:
- `station/song` — all songs
- `station/song/danish` — Danish rap only
- `station/song/english` — English only

---

## 📊 Today's Stats

| Metric | Value |
|--------|-------|
| Total Songs Written | **{total_written}** |
| 🇩🇰 Danish Rap | **{danish_written}** / {danish_target} |
| 🇬🇧 English | **{english_written}** / {english_target} |
| Target per Day | **{songs_per_day}** |
| Danish Themes Available | **{themes_count}** |
| Last Updated | {date_str} {time_str} UTC |

---

## 🗂️ Server Structure

```
station/
├── Dashboard.md              ← 📍 You are here
│
├── Songwriter/
│   └── Danish Themes.md      ← ✏️ EDIT THIS to set Danish rap emner
│                                 Add one theme per line, e.g.:
│                                 - livet i København
│                                 - at ryge weed med vennerne
│                                 - brostærke historier
│
├── Songs/
│   ├── INDEX.md              ← Quick link to all songs (query view)
│   ├── {date_str}/
│   │   ├── dansk-rap-*.md    ← Danish rap (each song = its own page)
│   │   └── english-*.md      ← English songs (each song = its own page)
│   └── YYYY-MM-DD/           ← Previous days, organized by date
│
├── Incidents/                ← Station incidents and alerts
├── Tracks/                   ← Auto-discovered tracks log
├── Sessions/                 ← Broadcast session logs
└── Daily Log/                ← Daily operational summaries
```

Each song is **its own page** with structured frontmatter:

```yaml
---
type: song_lyrics
title: Rygen Stiger Over Nørrebro
language: danish
genre: dansk rap
theme: at ryge weed med vennerne
style: dansk rap, boom bap, tung bas, rå vokal, 85-95 bpm
written_at: 2026-04-20T14:30:00Z
date: 2026-04-20
tags:
  - station/song
  - station/song/danish
---

# Rygen Stiger Over Nørrebro

[Intro:] Vinyl krøs, tung bas creeps ind
[Vers 1]
Lyrics here...
[Omkvæd]
Lyrics here...
[Outro]
[Bass sustains for 10 seconds]
[Vinyl needle scratch]
```

---

## ✏️ Setting Danish Rap Themes

To control what Hermes writes Danish rap songs about, edit the
[[station/Songwriter/Danish Themes]] page. Add your emner as a list:

```
- livet i København
- at ryge weed med vennerne
- hverdagen og stresset
- fest i Nørrebro
- kærlighed og hjertesorg
```

Hermes reloads this page every 10 songs, so changes take effect quickly.
If the page is empty or missing, Hermes uses a built-in default list.

---

## 🇩🇰 Danish Rap Songs

```query
from p = tags["station/song/danish"]
order by p.written_at desc
limit 50
select {{|p.written_at|[[${{p.name}}|${{p.title}}]]|p.genre|p.theme|}}
```

---

## 🇬🇧 English Songs

```query
from p = tags["station/song/english"]
order by p.written_at desc
limit 50
select {{|p.written_at|[[${{p.name}}|${{p.title}}]]|p.genre|p.theme|}}
```

---

## 📅 Today's Songs

```query
from p = tags["station/song"]
where p.date = "{date_str}"
order by p.written_at desc
limit 80
select {{|p.written_at|[[${{p.name}}|${{p.title}}]]|p.language|p.genre|p.theme|}}
```

---

## 🎵 All Songs by Genre

```query
from p = tags["station/song"]
order by p.genre, p.written_at desc
limit 200
select {{|p.genre|[[${{p.name}}|${{p.title}}]]|p.language|p.date|}}
```

---

## 📝 Recent Song Pages

""".format(
            total_written=self._songs_written,
            danish_written=self._danish_written,
            danish_target=self._danish_count_target,
            english_written=self._english_written,
            english_target=self._english_count_target,
            songs_per_day=self.songs_per_day,
            themes_count=len(self._danish_themes),
            date_str=date_str,
            time_str=time_str,
        )

        # Static fallback list of recent songs
        recent_pages = await self._list_song_pages(limit=20)
        if recent_pages:
            content += "| # | Date | Language | Genre | Page |\n|---|------|----------|-------|------|\n"
            for i, page in enumerate(recent_pages, 1):
                name = page.get("name", "unknown")
                page_link = f"[[{name}]]"
                date_part = name.split("/")[3] if len(name.split("/")) > 3 else "?"
                lang_part = "🇩🇰 danish" if "dansk" in name.lower() or "danish" in name.lower() else "🇬🇧 english"
                content += f"| {i} | {date_part} | {lang_part} | — | {page_link} |\n"
            content += "\n"

        content += """
---

*This page is auto-generated by the Hermes songwriter agent. It updates every 5 songs. To change Danish rap themes, edit [[station/Songwriter/Danish Themes]].*
"""

        # Write the dashboard page
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
                        logger.info("SilverBullet Dashboard updated")
                    else:
                        error_text = await resp.text()
                        logger.warning(
                            "Dashboard update failed: HTTP %d — %s",
                            resp.status,
                            error_text[:200],
                        )
        except Exception as e:
            logger.warning("Dashboard update error: %s", e)

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
            "outbox_pending": len(self._outbox),
        }

    async def push_page(self, page_path: str, content: str) -> bool:
        """Push an arbitrary page to SilverBullet through the dashboard pusher.

        Other modules (SunoCreator, sb_documenter, etc.) can use this
        to write any page to SilverBullet. The page gets queued in the
        outbox and flushed on the next push cycle along with the
        dashboard update.

        Args:
            page_path: SilverBullet page path, e.g. "station/Tracks/Suno-2026-04-20"
            content: Full page content including frontmatter

        Returns:
            True if queued successfully (will be written on next push cycle)
        """
        self._outbox.append({
            "page_path": page_path,
            "content": content,
            "song_data": {},
            "title": page_path.split("/")[-1],
            "queued_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("External page queued for SilverBullet: %s", page_path)
        return True

    async def write_page_now(self, page_path: str, content: str) -> bool:
        """Write a page to SilverBullet immediately (bypasses the outbox).

        Use this for urgent writes that can't wait for the push cycle.
        """
        return await self._write_page_to_sb(page_path, content)

    async def reload_themes(self):
        """Force-reload Danish themes from SilverBullet."""
        await self._load_danish_themes()
        logger.info("Danish themes reloaded: %d themes", len(self._danish_themes))
        return len(self._danish_themes)