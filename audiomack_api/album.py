import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from fastapi import APIRouter, FastAPI, HTTPException, Query
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


# ============================================================
# CONFIG
# ============================================================

AUDIO_URL_MARKERS = (
    ".mp3",
    ".m4a",
    ".m3u8",
    "/streaming/",
    "/hq/",
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ============================================================
# FASTAPI
# ============================================================

router = APIRouter()
app = FastAPI(
    title="Audiomack Album API",
    version="1.0.0",
)


# ============================================================
# GENERAL HELPERS
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    value = str(value)
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def clean_audiomack_url(url):
    url = clean_text(url)
    if not url:
        return ""
    return url


def ordinal_day(day):
    day = int(day)
    if 10 <= (day % 100) <= 20:
        suffix = "th"
    else:
        suffix = {
            1: "st",
            2: "nd",
            3: "rd",
        }.get(day % 10, "th")

    return f"{day}{suffix}"


def format_release_date(date_value):
    if not date_value:
        return "", ""

    value = clean_text(date_value)
    value = re.sub(r"[®™©‡]", "", value)
    value = clean_text(value)

    patterns = [
        "%B %d, %Y",
        "%b %d, %Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ]

    for pattern in patterns:
        try:
            dt = datetime.strptime(value, pattern)
            return (
                f"{dt.strftime('%B')} {ordinal_day(dt.day)}",
                str(dt.year),
            )
        except ValueError:
            pass

    if value.isdigit():
        try:
            timestamp = int(value)
            if timestamp > 100000000:
                dt = datetime.fromtimestamp(
                    timestamp,
                    tz=timezone.utc,
                )
                return (
                    f"{dt.strftime('%B')} {ordinal_day(dt.day)}",
                    str(dt.year),
                )
        except Exception:
            pass

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        return (
            f"{dt.strftime('%B')} {ordinal_day(dt.day)}",
            str(dt.year),
        )
    except Exception:
        pass

    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    if match:
        try:
            dt = datetime(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
            )
            return (
                f"{dt.strftime('%B')} {ordinal_day(dt.day)}",
                str(dt.year),
            )
        except Exception:
            pass

    match = re.search(
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+"
        r"(\d{1,2}),\s*(\d{4})",
        value,
        re.IGNORECASE,
    )

    if match:
        try:
            month = match.group(1)
            day = int(match.group(2))
            year = int(match.group(3))

            dt = datetime.strptime(
                f"{month} {day}, {year}",
                "%B %d, %Y",
            )
            return (
                f"{dt.strftime('%B')} {ordinal_day(dt.day)}",
                str(dt.year),
            )
        except Exception:
            pass

    year_match = re.search(r"\b(19|20)\d{2}\b", value)
    year = year_match.group(0) if year_match else ""

    return value, year


def parse_duration(value):
    """
    Converts common Audiomack duration formats to seconds.
    Supports HH:MM:SS, MM:SS, numeric seconds, and ISO 8601 PT#M#S strings.
    """
    if value is None:
        return 0

    if isinstance(value, bool):
        return 0

    if isinstance(value, (int, float)):
        return max(0, int(value))

    value = clean_text(value)
    if not value:
        return 0

    # Handle ISO 8601 duration e.g. PT3M25S
    iso_match = re.search(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value, re.IGNORECASE)
    if iso_match and any(iso_match.groups()):
        h = int(iso_match.group(1) or 0)
        m = int(iso_match.group(2) or 0)
        s = int(iso_match.group(3) or 0)
        return h * 3600 + m * 60 + s

    # HH:MM:SS or MM:SS
    if re.fullmatch(r"\d+:\d{1,2}:\d{1,2}", value):
        parts = value.split(":")
        try:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except Exception:
            return 0

    if re.fullmatch(r"\d+:\d{1,2}", value):
        parts = value.split(":")
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except Exception:
            return 0

    try:
        number = float(value)
        if number >= 0:
            return int(number)
    except Exception:
        pass

    return 0


def format_duration(seconds):
    seconds = int(seconds or 0)
    if seconds < 0:
        seconds = 0

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"

    return f"{minutes}:{secs:02d}"


def get_first_value(obj, keys):
    if not isinstance(obj, dict):
        return ""

    for key in keys:
        value = obj.get(key)
        if value not in (None, "", [], {}):
            return value

    return ""


def extract_slug_from_url(url):
    try:
        path = urlparse(url).path.strip("/")
        parts = path.split("/")
        if len(parts) >= 3:
            return parts[-1]
    except Exception:
        pass
    return ""


def clean_og_title(title):
    title = clean_text(title)
    if not title:
        return ""

    title = re.sub(
        r"\s*:\s*Listen on Audiomack.*$",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return clean_text(title)


def extract_next_data(page):
    result = {}
    try:
        element = page.query_selector("script#__NEXT_DATA__")
        if not element:
            return result

        raw = element.inner_text()
        if not raw:
            return result

        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    return result


def extract_page_props(next_data):
    if not isinstance(next_data, dict):
        return {}

    props = next_data.get("props", {})
    if not isinstance(props, dict):
        return {}

    page_props = props.get("pageProps", {})
    if not isinstance(page_props, dict):
        return {}

    return page_props


def find_music_object(page_props):
    if not isinstance(page_props, dict):
        return {}

    music = page_props.get("music")
    if isinstance(music, dict):
        return music

    redux = page_props.get("initialReduxState", {})
    if isinstance(redux, dict):
        redux_music = redux.get("music", {})
        if isinstance(redux_music, dict):
            if "title" in redux_music:
                return redux_music

            for _, value in redux_music.items():
                if isinstance(value, dict) and "title" in value:
                    return value

    return {}


# ============================================================
# DOM METADATA
# ============================================================

def extract_music_card_info(page):
    result = {
        "genre": "",
        "producer": "",
        "release_date": "",
    }

    try:
        rows = page.query_selector_all(
            "ul.SinglePageMusicCardInfo "
            "li.SinglePageMusicCardInfo-row"
        )

        for row in rows:
            title_elem = row.query_selector(".SinglePageMusicCardInfo-title")
            value_elem = row.query_selector(".SinglePageMusicCardInfo-value")

            if not title_elem or not value_elem:
                continue

            row_title = clean_text(title_elem.inner_text()).lower()
            row_value = clean_text(value_elem.inner_text())

            if not row_value:
                continue

            if "genre" in row_title:
                result["genre"] = row_value
            elif "producer" in row_title:
                result["producer"] = row_value
            elif "release date" in row_title:
                result["release_date"] = re.sub(
                    r"[®™©‡]",
                    "",
                    row_value,
                ).strip()

    except Exception:
        pass

    return result


def extract_duration_from_meta(page):
    """
    Looks for music:duration meta property on page.
    """
    try:
        val = page.get_attribute('meta[property="music:duration"]', "content")
        if val:
            return parse_duration(val)
    except Exception:
        pass
    return 0


# ============================================================
# ALBUM TRACK LINKS
# ============================================================

def extract_track_links(page, album_url):
    tracks = []
    seen = set()

    try:
        elements = page.locator('meta[property="music:song"]')
        count = elements.count()

        for i in range(count):
            try:
                content = elements.nth(i).get_attribute("content")
                if not content:
                    continue

                content = urljoin(album_url, content)
                if "/song/" not in content:
                    continue

                if content not in seen:
                    seen.add(content)
                    tracks.append(content)

            except Exception:
                continue

    except Exception:
        pass

    try:
        links = page.locator('a[href*="/song/"]')
        count = links.count()

        for i in range(count):
            try:
                href = links.nth(i).get_attribute("href")
                if not href:
                    continue

                href = urljoin(album_url, href)
                if "/song/" not in href:
                    continue

                parsed = urlparse(href)
                href = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

                if href not in seen:
                    seen.add(href)
                    tracks.append(href)

            except Exception:
                continue

    except Exception:
        pass

    if not tracks:
        try:
            html = page.content()
            matches = re.findall(
                r'https?://(?:www\.)?audiomack\.com/[^"\']+/song/[^"\']+',
                html,
                flags=re.IGNORECASE,
            )

            for match in matches:
                match = match.replace("\\/", "/")
                match = match.split('"')[0].split("'")[0]

                if "/song/" in match:
                    parsed = urlparse(match)
                    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

                    if clean_url not in seen:
                        seen.add(clean_url)
                        tracks.append(clean_url)

        except Exception:
            pass

    return tracks


# ============================================================
# SONG ID
# ============================================================

def extract_song_id_from_text(text):
    if not text:
        return ""

    patterns = [
        r'"(?:songId|song_id|trackId|track_id|id)"\s*:\s*"(\d+)"',
        r'"(?:songId|song_id|trackId|track_id|id)"\s*:\s*(\d+)',
        r'["\']songId["\']\s*[:=]\s*["\']?(\d+)',
        r'["\']trackId["\']\s*[:=]\s*["\']?(\d+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)

    return ""


def extract_song_id(page, track_obj, streaming_url=""):

    # 1. Track object
    if isinstance(track_obj, dict):
        value = get_first_value(
            track_obj,
            ["songId", "song_id", "trackId", "track_id", "id", "id_music"],
        )
        if value is not None:
            value = str(value).strip()
            if value.isdigit():
                return value

    # 2. Extract from Intercepted Streaming URL
    if streaming_url:
        match = re.search(r"_audtrk__(\d+)", streaming_url)
        if match:
            return match.group(1)

        match = re.search(r"/(\d+)(?:\.[a-zA-Z0-9]+|\?)", streaming_url)
        if match:
            return match.group(1)

    # 3. DOM attributes
    selectors = [
        "[data-song-id]",
        "[data-track-id]",
        "[data-songid]",
        "[data-trackid]",
        "[data-amlabs-music-id]",
    ]

    for selector in selectors:
        try:
            elements = page.locator(selector)
            count = elements.count()

            for i in range(count):
                element = elements.nth(i)
                for attribute in [
                    "data-song-id",
                    "data-track-id",
                    "data-songid",
                    "data-trackid",
                    "data-amlabs-music-id",
                ]:
                    try:
                        value = element.get_attribute(attribute)
                        if value and str(value).strip().isdigit():
                            return str(value).strip()
                    except Exception:
                        pass
        except Exception:
            pass

    # 4. Page HTML / Meta
    try:
        html = page.content()
        song_id = extract_song_id_from_text(html)
        if song_id:
            return song_id

    except Exception:
        pass

    # 5. Page URL or song links
    try:
        match = re.search(r"-(\d+)(?:[/?#]|$)", page.url)
        if match:
            return match.group(1)
    except Exception:
        pass

    return ""


# ============================================================
# TRACK EXTRACTION
# ============================================================

def extract_track_page(
    page,
    track_url,
    track_number,
):
    print(f"[*] Extracting track {track_number}: {track_url}")

    track_info = {
        "songId": "",
        "title": "",
        "artist": "",
        "featuringArtists": "",
        "duration": "0:00",
        "genre": "",
        "producer": "",
        "releaseDate": "",
        "year": "",
        "trackNumber": track_number,
        "streamingUrl": "",
        "trackImageUrl": "",
    }

    streaming_url = {"value": ""}

    def handle_response(response):
        try:
            response_url = response.url
            lower_url = response_url.lower()

            is_audio = any(
                marker in lower_url for marker in AUDIO_URL_MARKERS
            )

            if not is_audio:
                return

            if "audiomack.com" not in lower_url:
                return

            if not streaming_url["value"]:
                streaming_url["value"] = response_url
                print(f"[✓] Audiomack streaming URL intercepted:\n{response_url}")

        except Exception:
            pass

    # Attach network listener BEFORE navigation
    page.on("response", handle_response)

    try:
        print(f"[*] Opening track: {track_url}")
        page.goto(
            track_url,
            wait_until="domcontentloaded",
            timeout=20000,
        )

        # PHASE 1 — Full React hydration wait (3 seconds)
        page.wait_for_timeout(3000)

        # PHASE 2 — React-compatible full mouse event chain
        try:
            page.evaluate("""() => {
                const selectors = [
                    'button[data-amlabs-play-button="true"]',
                    'button[aria-label="Play"]',
                    'button[aria-label*="Play"]',
                    '[class*="PlayButton"]',
                    '[class*="play-button"]',
                    'button.button--play',
                    '.play-button'
                ];
                const events = [
                    'pointerover','pointerenter','mouseover','mouseenter',
                    'pointermove','mousemove','pointerdown','mousedown',
                    'pointerup','mouseup','click'
                ];
                for (const sel of selectors) {
                    const btns = document.querySelectorAll(sel);
                    for (const btn of btns) {
                        const rect = btn.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            events.forEach(evName => {
                                btn.dispatchEvent(new MouseEvent(evName, {
                                    bubbles: true, cancelable: true, view: window
                                }));
                            });
                            return sel;
                        }
                    }
                }
                return 'not_found';
            }""")
        except Exception:
            pass

        # PHASE 3 — Playwright force-click as backup
        try:
            play_btn = page.query_selector(
                'button[data-amlabs-play-button="true"], '
                'button[aria-label*="Play"], '
                '[class*="PlayButton"], .play-button'
            )
            if play_btn:
                play_btn.click(force=True)
        except Exception:
            pass

        # PHASE 4 — Spacebar fallback
        try:
            page.keyboard.press("Space")
        except Exception:
            pass

        # PHASE 5 — Reactive wait up to 6 seconds, exits immediately on capture
        for _ in range(60):
            if streaming_url["value"]:
                break
            page.wait_for_timeout(100)

        if not streaming_url["value"]:
            print(f"[!] streamingUrl not captured for track {track_number}.")

        # Parse Page Data
        next_data = extract_next_data(page)
        page_props = extract_page_props(next_data)
        track_obj = find_music_object(page_props)

        card_info = extract_music_card_info(page)
        dom_genre = card_info.get("genre", "")
        dom_producer = card_info.get("producer", "")
        dom_release_date = card_info.get("release_date", "")

        og_title = page.get_attribute('meta[property="og:title"]', "content") or ""
        og_image = page.get_attribute('meta[property="og:image"]', "content") or ""

        # Title
        track_info["title"] = clean_text(
            get_first_value(track_obj, ["title", "name"])
        )
        if not track_info["title"]:
            clean_title = clean_og_title(og_title)
            if " by " in clean_title:
                track_info["title"] = clean_title.split(" by ", 1)[0].strip()
            elif "Audiomack" not in clean_title:
                track_info["title"] = clean_title

        if not track_info["title"] or "Audiomack" in track_info["title"]:
            try:
                h1 = page.query_selector("h1")
                if h1:
                    h1_text = clean_text(h1.inner_text())
                    if h1_text and "Audiomack" not in h1_text:
                        track_info["title"] = h1_text
            except Exception:
                pass

        # Artist
        artist = clean_text(
            get_first_value(track_obj, ["artist", "artistName", "artist_name"])
        )
        if not artist:
            clean_title = clean_og_title(og_title)
            if " by " in clean_title:
                artist = clean_title.split(" by ", 1)[1].split(":", 1)[0].strip()

        artist = artist.replace("Listen on Audiomack", "").strip()

        # Featuring
        featuring = clean_text(
            get_first_value(
                track_obj,
                ["featuring", "feat", "featuredArtists", "featured_artists"],
            )
        )

        if not featuring and " & " in artist:
            parts = [p.strip() for p in artist.split("&") if p.strip()]
            if len(parts) > 1:
                artist = parts[0]
                featuring = ", ".join(parts[1:])

        track_info["artist"] = artist
        track_info["featuringArtists"] = featuring

        # Genre & Producer
        track_info["genre"] = dom_genre or clean_text(
            get_first_value(track_obj, ["genre", "genres"])
        )
        track_info["producer"] = clean_text(
            get_first_value(track_obj, ["producer", "producers", "credits"])
            or dom_producer
        )

        # Track Number
        track_info["trackNumber"] = track_number

        # Image
        image = get_first_value(
            track_obj,
            ["image", "cover", "imageUrl", "image_url", "coverImage"],
        )
        track_info["trackImageUrl"] = clean_text(image) or clean_text(og_image)

        # Release Date
        released = dom_release_date or get_first_value(
            track_obj,
            ["released", "releaseDate", "release_date", "uploaded", "released_at"],
        )
        release_date, year = format_release_date(released)
        track_info["releaseDate"] = release_date
        track_info["year"] = year

        # DURATION
        duration_seconds = extract_duration_from_meta(page)
        if not duration_seconds:
            duration_value = get_first_value(
                track_obj, ["duration", "durationSeconds", "duration_seconds", "rawDuration"]
            )
            duration_seconds = parse_duration(duration_value)

        track_info["duration"] = format_duration(duration_seconds)

        # STREAMING URL & SONG ID FALLBACKS
        if not streaming_url["value"]:
            next_streaming = get_first_value(
                track_obj,
                ["streaming_url", "streamingUrl", "signedUrl", "signed_url", "url"],
            )
            if next_streaming and any(m in str(next_streaming) for m in AUDIO_URL_MARKERS):
                streaming_url["value"] = str(next_streaming)

        track_info["streamingUrl"] = streaming_url["value"]
        track_info["songId"] = extract_song_id(page, track_obj, streaming_url["value"])

    except PlaywrightTimeoutError:
        print("[!] Track page timed out.")
    except Exception as exc:
        print(f"[!] Track extraction error: {exc}")

    return track_info

def extract_album_info(
    album_url,
    selected_track=None,
):
    album_url = clean_audiomack_url(album_url)

    if not album_url:
        raise ValueError("Album URL is required.")

    # --- [PERBAIKAN: IZINKAN URL PLAYLIST] ---
    if "/album/" not in album_url.lower() and "/playlist/" not in album_url.lower():
        raise ValueError("URL must be an Audiomack album or playlist URL.")
    # -----------------------------------------

    print(f"[*] Extracting Audiomack album/playlist: {album_url}")

    album_data = {
        "albumId": extract_slug_from_url(album_url),
        "albumTitle": "",
        "albumArtist": "",
        "albumFeaturingArtists": "",
        "albumReleaseDate": "",
        "albumTotalDuration": "0:00",
        "albumGenre": "",
        "albumYear": "",
        "albumImageUrl": "",
        "albumTotalTracks": 0,
        "producer": "",
        "description": "",
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        context = browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            viewport={"width": 1440, "height": 900},
        )

        page = context.new_page()

        try:
            page.goto(
                album_url,
                wait_until="domcontentloaded",
                timeout=20000,
            )

            # --- [PERBAIKAN: KOLEKTOR LINK DINAMIS SAAT SCROLL] ---
            all_track_urls = []
            seen_urls = set()

            def _collect_visible_tracks():
                try:
                    hrefs = page.evaluate('''() => {
                        return Array.from(document.querySelectorAll('a[href*="/song/"]')).map(a => a.href);
                    }''')
                    for href in hrefs:
                        if href and "/song/" in href:
                            parsed = urlparse(href)
                            clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                            if clean not in seen_urls:
                                seen_urls.add(clean)
                                all_track_urls.append(clean)
                except Exception:
                    pass

            print("[*] Menggulir halaman dan mengekstrak link lagu bertahap...")
            last_height = page.evaluate("document.body.scrollHeight")
            
            # Kumpulkan lagu pertama kali halaman dimuat
            _collect_visible_tracks()
            
            for _ in range(50):  # Maksimal 50 scroll (cukup untuk 500+ lagu)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1500) # Beri waktu render
                
                # Kumpulkan lagu yang baru muncul
                _collect_visible_tracks()
                
                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight - 600)")
                    page.wait_for_timeout(500)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1500)
                    
                    # Kumpulkan lagi setelah pancingan
                    _collect_visible_tracks()
                    
                    new_height = page.evaluate("document.body.scrollHeight")
                    if new_height == last_height:
                        break # Sudah mencapai bawah halaman
                last_height = new_height
                
            print(f"[*] Selesai menggulir. Sukses mengamankan: {len(all_track_urls)} lagu.")
            # ------------------------------------------------------

            # Brief pause for album meta tags and track links
            page.wait_for_timeout(600)

            og_title = page.get_attribute('meta[property="og:title"]', "content") or ""
            og_image = page.get_attribute('meta[property="og:image"]', "content") or ""
            album_data["albumImageUrl"] = clean_text(og_image)

            def meta_content(property_name):
                try:
                    return clean_text(
                        page.get_attribute(
                            f'meta[property="{property_name}"]', "content"
                        )
                        or ""
                    )
                except Exception:
                    return ""

            music_musician = meta_content("music:musician")
            music_release_date = meta_content("music:release_date")

            title = clean_og_title(og_title)
            album_title = title.split(" by ", 1)[0].strip() if " by " in title else title
            if "Audiomack" in album_title:
                try:
                    h1 = page.query_selector("h1")
                    if h1:
                        h1_text = clean_text(h1.inner_text())
                        if h1_text and "Audiomack" not in h1_text:
                            album_title = h1_text
                except Exception:
                    pass
            album_data["albumTitle"] = album_title

            artist = music_musician
            if not artist and " by " in title:
                artist = title.split(" by ", 1)[1].strip()

            artist = re.sub(
                r"\s*:\s*Listen on Audiomack.*$", "", artist, flags=re.IGNORECASE
            )
            album_data["albumArtist"] = clean_text(artist)

            release_date, year = format_release_date(music_release_date)
            album_data["albumReleaseDate"] = release_date
            album_data["albumYear"] = year

            card_info = extract_music_card_info(page)
            album_data["albumGenre"] = clean_text(card_info.get("genre", ""))
            album_data["producer"] = clean_text(card_info.get("producer", ""))

            description = meta_content("og:description")
            if not description:
                try:
                    description = clean_text(
                        page.get_attribute('meta[name="description"]', "content") or ""
                    )
                except Exception:
                    description = ""

            album_data["description"] = description

            # Parse album page Next.js data
            album_next_data = extract_next_data(page)
            album_props = extract_page_props(album_next_data)
            album_music_obj = find_music_object(album_props)

            track_urls = extract_track_links(page, album_url)
            if not track_urls and "tracks" in album_music_obj and isinstance(album_music_obj["tracks"], list):
                for t in album_music_obj["tracks"]:
                    if isinstance(t, dict):
                        t_url = get_first_value(t, ["url", "canonical_url", "link"])
                        if t_url:
                            track_urls.append(urljoin(album_url, str(t_url)))

            # --- [GABUNGKAN HASIL SCROLL DENGAN DOM BAWAAN] ---
            for url in all_track_urls:
                if url not in track_urls:
                    track_urls.append(url)
            # --------------------------------------------------

            album_data["albumTotalTracks"] = len(track_urls)
            print(f"[✓] Total Final {len(track_urls)} tracks terdeteksi.")

            # Fast album total duration extraction
            total_seconds = 0

            # 1. Check direct duration on album music object
            direct_dur = get_first_value(
                album_music_obj,
                ["duration", "durationSeconds", "duration_seconds", "total_duration", "totalDuration"],
            )
            if direct_dur:
                total_seconds = parse_duration(direct_dur)

            # 2. Sum durations from tracks in album_music_obj
            if not total_seconds and "tracks" in album_music_obj and isinstance(album_music_obj["tracks"], list):
                for t in album_music_obj["tracks"]:
                    if isinstance(t, dict):
                        t_sec = parse_duration(
                            get_first_value(t, ["duration", "durationSeconds", "duration_seconds"])
                        )
                        total_seconds += t_sec

            # 3. Extract durations from page JSON/scripts using regex
            if not total_seconds:
                try:
                    html_content = page.content()
                    raw_durations = re.findall(r'"duration"\s*:\s*"?(\d+)"?', html_content)
                    if raw_durations:
                        valid_durations = [int(d) for d in raw_durations if 30 <= int(d) <= 1800]
                        if valid_durations:
                            if len(track_urls) > 0 and len(valid_durations) >= len(track_urls):
                                total_seconds = sum(valid_durations[:len(track_urls)])
                            else:
                                total_seconds = sum(valid_durations)
                except Exception:
                    pass

            # 4. Extract track durations from DOM elements matching MM:SS pattern
            if not total_seconds:
                try:
                    dom_durations = page.evaluate("""() => {
                        const regex = /^\\d{1,2}:\\d{2}$/;
                        const matches = [];
                        const nodes = document.querySelectorAll('*');
                        for (const node of nodes) {
                            if (node.children.length === 0) {
                                const text = node.textContent.trim();
                                if (regex.test(text)) {
                                    matches.push(text);
                                }
                            }
                        }
                        return matches;
                    }""")
                    if dom_durations:
                        total_seconds = sum(parse_duration(d) for d in dom_durations[:len(track_urls)])
                except Exception:
                    pass

            album_data["albumTotalDuration"] = format_duration(total_seconds)

            selected_track_data = None
            if selected_track is not None:
                if selected_track < 1:
                    raise ValueError("Track number must be 1 or greater.")

                if selected_track > len(track_urls):
                    raise ValueError(
                        f"Track {selected_track} not found. Album contains {len(track_urls)} tracks."
                    )

                selected_url = track_urls[selected_track - 1]
                print(f"[*] Selected track {selected_track}: {selected_url}")

                track_page = context.new_page()
                try:
                    selected_track_data = extract_track_page(
                        track_page,
                        selected_url,
                        selected_track,
                    )
                finally:
                    track_page.close()

        finally:
            browser.close()

    result = {
        "albumId": album_data["albumId"],
        "albumTitle": album_data["albumTitle"],
        "albumArtist": album_data["albumArtist"],
        "albumFeaturingArtists": album_data["albumFeaturingArtists"],
        "albumReleaseDate": album_data["albumReleaseDate"],
        "albumTotalDuration": album_data["albumTotalDuration"],
        "albumGenre": album_data["albumGenre"],
        "albumYear": album_data["albumYear"],
        "albumImageUrl": album_data["albumImageUrl"],
        "albumTotalTracks": album_data["albumTotalTracks"],
        "producer": album_data["producer"],
        "description": album_data["description"],
    }

    if selected_track_data is not None:
        result["track"] = selected_track_data

    return result


# ============================================================
# API ENDPOINT
# ============================================================

@router.get("/album")
def album_endpoint(
    url: str = Query(
        ...,
        description="Audiomack album URL",
    ),
    track: int | None = Query(
        None,
        description="Optional track number, e.g. 1, 2, 3",
    ),
):
    try:
        data = extract_album_info(
            url,
            selected_track=track,
        )

        return {
            "success": True,
            "data": data,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        print(f"[!] Album endpoint error: {exc}")

        raise HTTPException(
            status_code=500,
            detail=f"Failed to extract album: {exc}",
        )


app.include_router(router)


# ============================================================
# LOCAL TEST
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print('python app/album.py "https://audiomack.com/udumakahle/album/21-questions"')
        print("\nWith track:")
        print('python app/album.py "https://audiomack.com/udumakahle/album/21-questions" 1')
        raise SystemExit(1)

    album_url = sys.argv[1]
    selected_track = None

    if len(sys.argv) >= 3:
        try:
            selected_track = int(sys.argv[2])
        except ValueError:
            print("Track number must be an integer.")
            raise SystemExit(1)

    try:
        result = extract_album_info(
            album_url,
            selected_track=selected_track,
        )

        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
        )

    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": str(exc),
                },
                indent=2,
            )
        )
