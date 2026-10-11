# [GANTI TOTAL ISI FILE: bot/helpers/nhaccuatui/handler.py]

import os
import re
import copy
import asyncio
import aiohttp
import aiofiles
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime
from PIL import Image
from playwright.async_api import Page, BrowserContext

from config import Config
from bot.logger import LOGGER
from bot.settings import bot_set
from bot.helpers.message import edit_message
from bot.helpers.metadata import metadata as base_metadata, set_metadata
from bot.helpers.utils import (
    download_file,
    run_concurrent_tasks,
    post_art_poster,
    fetch_zip_settings,
)
from bot.helpers.uploder import (
    track_upload,
    album_upload,
    playlist_upload,
    artist_upload,
    batch_telegram_upload,
)
from .manager import nhaccuatui_manager, HEADERS

AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".flac")


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", str(name or ""))
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180] or "Unknown"


def get_url_type(url: str) -> str:
    path = urlparse(url).path
    if "/artist/" in path:
        return "artist"
    if "/playlist/" in path or "/danh-sach/" in path:
        return "playlist"
    if "/album/" in path:
        return "album"
    if "/bai-hat/" in path or "/song/" in path:
        return "song"
    return "unknown"


def extract_url_key(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        return ""
    last_part = path.split("/")[-1]
    if last_part.endswith(".html"):
        last_part = last_part[:-5]
    if "." in last_part:
        return last_part.split(".")[-1].strip()
    return last_part.strip()


def parse_nct_date(raw_val) -> tuple[str, str]:
    """Mengonversi Epoch timestamp (milidetik) menjadi YYYY-MM-DD dan YYYY."""
    if not raw_val:
        return "", ""
    s = str(raw_val).strip()

    if s.isdigit():
        ts = int(s)
        if ts > 10_000_000_000:
            ts = ts / 1000
        try:
            dt = datetime.fromtimestamp(ts)
            return dt.strftime("%Y-%m-%d"), str(dt.year)
        except Exception:
            pass

    m = re.search(r'(\d{4})[-/](\d{2})[-/](\d{2})', s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", m.group(1)

    m_year = re.search(r'\b(19\d{2}|20\d{2})\b', s)
    if m_year:
        return m_year.group(1), m_year.group(1)

    return s, s[:4] if len(s) >= 4 else ""


async def upgrade_cover_url(url: str) -> str:
    """Mencari cover resolusi tinggi (_1000, _800, _600, atau original) dari CDN NhacCuaTui."""
    if not url or not isinstance(url, str):
        return ""
    if not any(sub in url for sub in ("_130.", "_150.", "_300.", "_500.")):
        return url

    candidates = []
    for sz in ("_1000.", "_800.", "_600.", "_500."):
        new_url = re.sub(r'_(?:130|150|300|500)\.', sz, url)
        if new_url != url:
            candidates.append(new_url)

    orig_url = re.sub(r'_(?:130|150|300|500)\.', '.', url)
    if orig_url != url:
        candidates.append(orig_url)

    timeout = aiohttp.ClientTimeout(total=4)
    try:
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            for cand in candidates:
                try:
                    async with session.head(cand, allow_redirects=True) as resp:
                        if resp.status == 200:
                            return cand
                except Exception:
                    continue
    except Exception:
        pass

    return url


async def save_optimized_cover(url: str, dest_folder: str) -> str:
    """Mengunduh dan memastikan cover berformat JPEG RGB untuk Telegram thumbnail & tag audio."""
    if not url:
        return ""
    os.makedirs(dest_folder, exist_ok=True)
    raw_path = os.path.join(dest_folder, "cover_raw.tmp")
    final_path = os.path.join(dest_folder, "cover.jpg")

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    async with aiofiles.open(raw_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(65536):
                            await f.write(chunk)
                else:
                    return ""

        def _convert():
            with Image.open(raw_path) as img:
                img = img.convert("RGB")
                img.save(final_path, "JPEG", quality=95, optimize=True)
            if os.path.exists(raw_path):
                os.remove(raw_path)

        await asyncio.to_thread(_convert)
        if os.path.exists(final_path) and os.path.getsize(final_path) > 0:
            return final_path
    except Exception as e:
        LOGGER.warning(f"NhacCuaTui: Gagal memproses cover image: {e}")
        if os.path.exists(raw_path):
            try:
                os.rename(raw_path, final_path)
                return final_path
            except Exception:
                pass
    return ""


def best_stream(streams: list, quality_pref: str) -> dict | None:
    if not streams or not isinstance(streams, list):
        return None

    for pref in [quality_pref, None]:
        candidates = [
            s for s in streams
            if isinstance(s, dict)
            and s.get("status") == 1
            and not s.get("onlyVIP")
            and (pref is None or str(s.get("type")) == str(pref))
        ]
        if candidates:
            candidates.sort(key=lambda x: x.get("order", 0), reverse=True)
            return candidates[0]

    active = [s for s in streams if isinstance(s, dict) and s.get("status") == 1]
    if active:
        active.sort(key=lambda x: x.get("order", 0), reverse=True)
        return active[0]

    return None


def parse_song(song_data: dict, quality_pref: str) -> dict | None:
    name = (song_data.get("name") or song_data.get("title") or "").strip()
    if not name:
        return None
    stream = best_stream(song_data.get("streamURL", []), quality_pref)
    if not stream:
        return None

    audio_url = stream.get("download") or stream.get("stream")
    if not audio_url:
        return None

    artist_name = song_data.get("artistName", "")
    if not artist_name and isinstance(song_data.get("artists"), list):
        artist_name = ", ".join(
            a.get("name", "") for a in song_data["artists"] if isinstance(a, dict) and a.get("name")
        )

    cover_url = (
        song_data.get("image")
        or song_data.get("thumbURL")
        or song_data.get("avatar")
        or song_data.get("bgImage")
        or ""
    )

    return {
        "key": song_data.get("key") or name,
        "title": name,
        "artist": artist_name or "Unknown Artist",
        "audio_url": audio_url,
        "quality": stream.get("typeUI") or f"{stream.get('type', quality_pref)}kbps",
        "cover": cover_url,
        "duration": song_data.get("duration") or 0,
        "explicit": False,
    }


def _collect_candidate_dicts(data: dict) -> list[tuple[str, dict]]:
    candidates = []
    for k, v in data.items():
        if not isinstance(v, dict):
            continue
        candidates.append((str(k), v))
        for sub_k, sub_v in v.items():
            if isinstance(sub_v, dict) and ("listSong" in sub_v or "songs" in sub_v or "streamURL" in sub_v):
                candidates.append((f"{k}.{sub_k}", sub_v))
    return candidates


def score_candidate_dict(val: dict, url_key: str, page_title: str) -> int:
    """Memberikan skor kecocokan agar bot memilih playlist utama dan membuang rekomendasi."""
    score = 0
    songs_list = val.get("listSong") or val.get("songs") or []
    if not isinstance(songs_list, list) or len(songs_list) == 0:
        return -999

    title_val = str(val.get("name") or val.get("title") or "").lower()
    negative_words = ("recommend", "suggest", "chart", "ranking", "top", "hot", "gợi ý", "đề xuất", "maybe")
    for neg in negative_words:
        if neg in title_val:
            score -= 150

    url_key_lower = url_key.lower() if url_key else ""
    if url_key_lower:
        for k in ("key", "id", "playlistKey", "code", "link", "url", "shortURL"):
            if url_key_lower in str(val.get(k, "")).lower():
                score += 250
        for sub_k in ("playlist", "info", "data", "detail"):
            sub_dict = val.get(sub_k)
            if isinstance(sub_dict, dict):
                for k in ("key", "id", "playlistKey", "code"):
                    if url_key_lower in str(sub_dict.get(k, "")).lower():
                        score += 250

    if page_title:
        clean_page_title = page_title.lower()
        if title_val and (title_val in clean_page_title or clean_page_title in title_val):
            score += 100

    expected = val.get("numOfItems") or val.get("total") or val.get("totalSong")
    if isinstance(expected, int) and expected == len(songs_list):
        score += 50

    return score


async def extract_nuxt_data(page: Page, url: str, quality_pref: str) -> tuple[list[dict], dict]:
    url_key = extract_url_key(url)
    url_type = get_url_type(url)
    page_info = {
        "title": "",
        "artist": "",
        "cover": "",
        "release_date": "",
        "date": "",
        "expected_total": 0,
        "explicit": "No",
    }

    try:
        meta_tags = await page.evaluate("""() => {
            const getMeta = (prop) => {
                const el = document.querySelector(`meta[property="${prop}"], meta[name="${prop}"]`);
                return el ? el.getAttribute('content') : '';
            };
            return {
                title: getMeta('og:title') || document.title || '',
                image: getMeta('og:image') || ''
            };
        }""")
        if meta_tags.get("title"):
            clean_t = re.sub(r"\s*[-|]\s*NhacCuaTui.*$", "", meta_tags["title"], flags=re.I).strip()
            page_info["title"] = clean_t
        if meta_tags.get("image"):
            page_info["cover"] = meta_tags["image"]
    except Exception:
        pass

    try:
        nuxt = await page.evaluate("() => JSON.parse(JSON.stringify(window.__NUXT__ || {}))")
    except Exception as e:
        LOGGER.warning(f"NhacCuaTui: Gagal membaca __NUXT__: {e}")
        return [], page_info

    raw_data = nuxt.get("data", {})
    if isinstance(raw_data, list):
        data = {str(i): item for i, item in enumerate(raw_data) if isinstance(item, dict)}
    elif isinstance(raw_data, dict):
        data = raw_data
    else:
        return [], page_info

    candidates = _collect_candidate_dicts(data)

    best_dict = None
    best_score = -999

    for _, val in candidates:
        if url_type == "song" and "streamURL" in val and ("name" in val or "title" in val):
            best_dict = val
            break
        sc = score_candidate_dict(val, url_key, page_info["title"])
        if sc > best_score:
            best_score = sc
            best_dict = val

    if not best_dict and candidates:
        best_dict = candidates[0][1]

    songs = []
    if best_dict:
        if best_dict.get("name") or best_dict.get("title"):
            page_info["title"] = (best_dict.get("name") or best_dict.get("title") or "").strip()
        if best_dict.get("artistName"):
            page_info["artist"] = best_dict.get("artistName", "").strip()

        raw_cover = (
            best_dict.get("image")
            or best_dict.get("avatar")
            or best_dict.get("thumbURL")
            or best_dict.get("bgImage")
            or page_info.get("cover")
            or ""
        )
        page_info["cover"] = await upgrade_cover_url(raw_cover)

        raw_date = best_dict.get("dateCreate") or best_dict.get("dateRelease") or best_dict.get("publishDate")
        rel_date, year_date = parse_nct_date(raw_date)
        page_info["release_date"] = rel_date
        page_info["date"] = year_date

        total_items = best_dict.get("numOfItems") or best_dict.get("total") or best_dict.get("totalSong") or 0
        if isinstance(total_items, int) and total_items > 0:
            page_info["expected_total"] = total_items

        if "streamURL" in best_dict and ("name" in best_dict or "title" in best_dict):
            s = parse_song(best_dict, quality_pref)
            if s:
                songs.append(s)

        song_list = best_dict.get("listSong") or best_dict.get("songs") or []
        if isinstance(song_list, list):
            for song_data in song_list:
                if isinstance(song_data, dict):
                    s = parse_song(song_data, quality_pref)
                    if s:
                        songs.append(s)

    if page_info["expected_total"] > 0 and url_type in ("playlist", "album"):
        songs = songs[:page_info["expected_total"]]

    return songs, page_info


async def capture_via_click(context: BrowserContext, song_url: str) -> dict | None:
    loop = asyncio.get_running_loop()
    found_url: asyncio.Future = loop.create_future()
    page = await context.new_page()

    async def on_request(req):
        url = req.url
        if not found_url.done() and any(url.lower().split("?")[0].endswith(e) for e in AUDIO_EXTENSIONS):
            found_url.set_result(url)

    async def on_response(resp):
        url = resp.url
        ct = resp.headers.get("content-type", "")
        if not found_url.done():
            if any(url.lower().split("?")[0].endswith(e) for e in AUDIO_EXTENSIONS):
                found_url.set_result(url)
            elif "application/json" in ct:
                try:
                    body = await resp.text()
                    for ext in AUDIO_EXTENSIONS:
                        matches = re.findall(
                            r'https?://[^\s"\'<>]+' + re.escape(ext) + r'[^\s"\'<>]*', body
                        )
                        if matches and not found_url.done():
                            found_url.set_result(matches[0])
                            return
                except Exception:
                    pass

    page.on("request", on_request)
    page.on("response", on_response)

    result: dict = {}
    try:
        await page.goto(song_url, wait_until="networkidle", timeout=30_000)
        raw_title = await page.title()
        clean_title = re.sub(r"\s*[-|]\s*NhacCuaTui.*$", "", raw_title, flags=re.I).strip()
        result["title"] = clean_title or "Unknown Track"

        for selector in [".btn-play", ".ic-play", ".img-btn", '[class*="play"]']:
            try:
                await page.click(selector, timeout=3_000)
                break
            except Exception:
                continue

        try:
            audio_url = await asyncio.wait_for(found_url, timeout=15)
            result["audio_url"] = audio_url
            result["key"] = song_url
            result["artist"] = "Unknown Artist"
            result["quality"] = "Stream"
            result["cover"] = ""
            result["duration"] = 0
            result["explicit"] = False
        except asyncio.TimeoutError:
            pass
    except Exception as e:
        LOGGER.warning(f"NhacCuaTui click fallback warning: {e}")
    finally:
        await page.close()

    return result if result.get("audio_url") else None


async def collect_songs(url: str, quality_pref: str) -> tuple[list[dict], dict]:
    browser = await nhaccuatui_manager.get_browser()
    context = await browser.new_context(
        user_agent=HEADERS["User-Agent"],
        locale="vi-VN",
        viewport={"width": 1280, "height": 900},
    )
    await context.route(
        "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,eot,otf}",
        lambda r: r.abort(),
    )

    page = await context.new_page()
    songs = []
    page_info = {}
    url_type = get_url_type(url)

    try:
        await page.goto(url, wait_until="networkidle", timeout=60_000)
        songs, page_info = await extract_nuxt_data(page, url, quality_pref)

        # Halaman artist saja yang membutuhkan scroll lanjutan jika daftar lagu terpotong
        if url_type == "artist" and len(songs) < 50:
            for _ in range(8):
                prev = len(songs)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1.2)
                for selector in [".btn-more", ".btn-loadmore", '[class*="load-more"]']:
                    try:
                        btn = page.locator(selector).first
                        if await btn.is_visible(timeout=300):
                            await btn.click()
                            await asyncio.sleep(1.2)
                    except Exception:
                        pass
                new_songs, _ = await extract_nuxt_data(page, url, quality_pref)
                if len(new_songs) > prev:
                    songs = new_songs
                else:
                    break

        if not songs and url_type in ("song", "unknown"):
            info = await capture_via_click(context, url)
            if info:
                songs.append(info)
    finally:
        try:
            await page.close()
        except Exception:
            pass
        try:
            await context.close()
        except Exception:
            pass

    return songs, page_info


async def direct_http_download(url: str, filepath: str) -> bool:
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        timeout = aiohttp.ClientTimeout(total=600)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return False
                async with aiofiles.open(filepath, "wb") as f:
                    async for chunk in resp.content.iter_chunked(65536):
                        await f.write(chunk)
        return os.path.exists(filepath) and os.path.getsize(filepath) > 0
    except Exception as e:
        LOGGER.error(f"NhacCuaTui aiohttp fallback error: {e}")
        return False


async def download_single_nct_track(
    song: dict,
    index: int,
    total_tracks: int,
    folderpath: str,
    collection_meta: dict,
    user: dict,
    is_single: bool = False,
) -> dict | None:
    audio_url = song["audio_url"]
    url_path = urlparse(audio_url).path
    ext = Path(url_path).suffix.lower()
    if ext not in AUDIO_EXTENSIONS:
        ext = ".mp3"
    ext_clean = ext.lstrip(".")

    track_meta = copy.deepcopy(base_metadata)
    track_meta["itemid"] = song.get("key", str(index))
    track_meta["title"] = song["title"]
    track_meta["artist"] = song.get("artist") or collection_meta.get("artist") or "Unknown Artist"
    track_meta["albumartist"] = collection_meta.get("artist") or track_meta["artist"]
    track_meta["album"] = collection_meta.get("title") or song["title"]
    track_meta["tracknumber"] = str(index)
    track_meta["totaltracks"] = str(total_tracks)
    track_meta["volume"] = "1"
    track_meta["totalvolume"] = "1"
    track_meta["duration"] = song.get("duration") or 0
    track_meta["date"] = collection_meta.get("date", "")
    track_meta["release_date"] = collection_meta.get("release_date", "")
    track_meta["quality"] = song.get("quality") or f"{nhaccuatui_manager.get_user_quality(user['user_id'])}kbps"
    track_meta["extension"] = ext_clean
    track_meta["provider"] = "NhacCuaTui"
    track_meta["type"] = "track"
    track_meta["explicit"] = False
    track_meta["tempfolder"] = collection_meta.get("tempfolder", f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/")

    if collection_meta.get("cover") and os.path.exists(str(collection_meta["cover"])):
        track_meta["cover"] = collection_meta["cover"]
        track_meta["thumbnail"] = collection_meta["cover"]
    else:
        raw_song_cover = song.get("cover") or collection_meta.get("raw_cover") or ""
        if raw_song_cover:
            upgraded = await upgrade_cover_url(raw_song_cover)
            track_meta["cover"] = await save_optimized_cover(upgraded, track_meta["tempfolder"])
            track_meta["thumbnail"] = track_meta["cover"]

    safe_title = sanitize_filename(song["title"])
    safe_artist = sanitize_filename(track_meta["artist"])
    if is_single:
        fname = f"{safe_title} - {safe_artist}.{ext_clean}"
    else:
        fname = f"{index:02d}. {safe_title} - {safe_artist}.{ext_clean}"

    filepath = os.path.join(folderpath, sanitize_filename(fname))
    track_meta["filepath"] = filepath

    details = None
    if is_single and "bot_msg" in user:
        details = {
            "msg": user["bot_msg"],
            "title": track_meta["title"],
            "type": "Track",
            "action": "Download",
            "headers": HEADERS,
        }
    else:
        details = {"headers": HEADERS}

    err = await download_file(audio_url, filepath, details=details)
    if err or not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        ok = await direct_http_download(audio_url, filepath)
        if not ok:
            LOGGER.error(f"NhacCuaTui: Gagal mengunduh {track_meta['title']}")
            return None

    await set_metadata(track_meta, user["user_id"])
    return track_meta


async def start_nhaccuatui(link: str, user: dict):
    user_id = user["user_id"]
    qual_pref = nhaccuatui_manager.get_user_quality(user_id)
    url_type = get_url_type(link)

    if "bot_msg" in user:
        await edit_message(user["bot_msg"], "🔍 Memuat halaman NhacCuaTui & mengekstrak stream...")

    songs, page_info = await collect_songs(link, qual_pref)
    if not songs:
        raise Exception("Tidak ditemukan lagu yang dapat diunduh dari link NhacCuaTui tersebut (Mungkin khusus VIP atau link tidak valid).")

    temp_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/"
    os.makedirs(temp_folder, exist_ok=True)

    # Unduh cover resolusi tinggi berformat JPEG untuk poster, tag audio, dan thumbnail ZIP
    cover_file = ""
    raw_cover = page_info.get("cover") or songs[0].get("cover") or ""
    if raw_cover:
        high_res_cover = await upgrade_cover_url(raw_cover)
        cover_file = await save_optimized_cover(high_res_cover, temp_folder)

    # --- 1. SINGLE SONG ---
    if url_type == "song" or (len(songs) == 1 and url_type == "unknown"):
        song = songs[0]
        folderpath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/NhacCuaTui/"
        os.makedirs(folderpath, exist_ok=True)

        col_meta = {
            "title": song["title"],
            "artist": song.get("artist") or page_info.get("artist") or "Unknown Artist",
            "cover": cover_file,
            "raw_cover": raw_cover,
            "date": page_info.get("date", ""),
            "release_date": page_info.get("release_date", ""),
            "tempfolder": temp_folder,
        }
        track_meta = await download_single_nct_track(
            song, 1, 1, folderpath, col_meta, user, is_single=True
        )
        if not track_meta:
            raise Exception(f"Gagal mengunduh lagu: {song['title']}")

        await track_upload(track_meta, user)
        return

    # --- 2. ALBUM / PLAYLIST / ARTIST ---
    col_type = url_type if url_type in ("album", "playlist", "artist") else "playlist"
    col_title = page_info.get("title") or songs[0].get("artist") or "NhacCuaTui Collection"
    col_artist = page_info.get("artist") or songs[0].get("artist") or "Various Artists"

    folderpath = os.path.join(
        f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/NhacCuaTui",
        sanitize_filename(col_title),
    )
    os.makedirs(folderpath, exist_ok=True)

    collection_meta = copy.deepcopy(base_metadata)
    collection_meta["title"] = col_title
    collection_meta["album"] = col_title
    collection_meta["artist"] = col_artist
    collection_meta["albumartist"] = col_artist
    collection_meta["totaltracks"] = str(len(songs))
    collection_meta["totalvolume"] = "1"
    collection_meta["quality"] = songs[0].get("quality") or f"{qual_pref}kbps"
    collection_meta["provider"] = "NhacCuaTui"
    collection_meta["type"] = col_type
    collection_meta["folderpath"] = folderpath
    collection_meta["tempfolder"] = temp_folder
    collection_meta["raw_cover"] = raw_cover
    collection_meta["cover"] = cover_file
    collection_meta["thumbnail"] = cover_file
    collection_meta["release_date"] = page_info.get("release_date", "")
    collection_meta["date"] = page_info.get("date", "")
    collection_meta["explicit"] = False

    if cover_file:
        collection_meta["poster_msg"] = await post_art_poster(user, collection_meta)

    tasks = [
        download_single_nct_track(
            song, idx, len(songs), folderpath, collection_meta, user, is_single=False
        )
        for idx, song in enumerate(songs, 1)
    ]

    update_details = {
        "msg": user.get("bot_msg"),
        "title": col_title,
        "type": col_type.capitalize(),
        "action": "Download",
    }

    results = await run_concurrent_tasks(tasks, update_details)
    valid_tracks = [r for r in results if isinstance(r, dict) and r.get("filepath")]

    if not valid_tracks:
        raise Exception("Semua lagu dalam koleksi gagal diunduh.")

    collection_meta["tracks"] = valid_tracks
    collection_meta["albums"] = [{"tracks": valid_tracks}]

    if col_type == "album":
        await album_upload(collection_meta, user)
    elif col_type == "artist":
        _, _, artist_zip, _ = fetch_zip_settings(user)
        user_mode = bot_set.user_data.get(user_id, {}).get("upload_mode", bot_set.upload_mode)
        if not artist_zip and user_mode == "Telegram" and bot_set.upload_mode == "Telegram":
            await batch_telegram_upload(collection_meta, user)
        await artist_upload(collection_meta, user)
    else:
        await playlist_upload(collection_meta, user)
