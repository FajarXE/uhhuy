# [GANTI ISI FILE: bot/helpers/nhaccuatui/handler.py]

import os
import re
import copy
import asyncio
import aiohttp
import aiofiles
from pathlib import Path
from urllib.parse import urlparse
from playwright.async_api import Page, BrowserContext

from config import Config
from bot.logger import LOGGER
from bot.settings import bot_set
from bot.helpers.message import edit_message
from bot.helpers.metadata import metadata as base_metadata, set_metadata, create_cover_file
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
IGNORE_DATA_KEYS = ("recommend", "suggest", "related", "chart", "ranking", "top", "hot", "maybe")


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
    """
    Mengekstrak ID/Key unik dari URL NhacCuaTui.
    Contoh:
    - https://www.nhaccuatui.com/playlist/TJaxsFXM11xj -> TJaxsFXM11xj
    - https://www.nhaccuatui.com/playlist/ten-playlist.TJaxsFXM11xj.html -> TJaxsFXM11xj
    """
    path = urlparse(url).path.strip("/")
    if not path:
        return ""
    last_part = path.split("/")[-1]
    if last_part.endswith(".html"):
        last_part = last_part[:-5]
    if "." in last_part:
        return last_part.split(".")[-1].strip()
    return last_part.strip()


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
    }


def _collect_candidate_dicts(data: dict) -> list[tuple[str, dict]]:
    """Mengumpulkan dictionary kandidat dari window.__NUXT__.data (termasuk 1 level nested)."""
    candidates = []
    for k, v in data.items():
        if not isinstance(v, dict):
            continue
        candidates.append((str(k), v))
        for sub_k, sub_v in v.items():
            if isinstance(sub_v, dict) and ("listSong" in sub_v or "songs" in sub_v or "streamURL" in sub_v):
                candidates.append((f"{k}.{sub_k}", sub_v))
    return candidates


async def extract_nuxt_data(page: Page, url: str, quality_pref: str) -> tuple[list[dict], dict]:
    """
    Mengekstrak daftar lagu hanya dari objek utama yang sesuai dengan URL,
    mencegah ikut terambilnya 50 lagu rekomendasi/chart di halaman yang sama.
    """
    url_key = extract_url_key(url)
    url_type = get_url_type(url)
    page_info = {"title": "", "artist": "", "cover": "", "release_date": "", "expected_total": 0}

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
    target_dicts = []

    # 1. Prioritas Utama: Cocokkan berdasarkan key/id dari URL (misal: TJaxsFXM11xj)
    if url_key:
        for d_key, val in candidates:
            val_key = str(val.get("key") or val.get("id") or "")
            has_tracks = bool(val.get("listSong") or val.get("songs") or "streamURL" in val)
            if has_tracks and (val_key == url_key or url_key in d_key):
                target_dicts.append(val)
                break

    # 2. Prioritas Kedua: Jika tidak cocok dengan key URL, ambil komponen utama pertama (bukan rekomendasi)
    if not target_dicts:
        for d_key, val in candidates:
            d_key_lower = d_key.lower()
            if any(ignored in d_key_lower for ignored in IGNORE_DATA_KEYS):
                continue

            if url_type == "song" and "streamURL" in val and ("name" in val or "title" in val):
                target_dicts.append(val)
                break
            elif url_type != "song" and (val.get("listSong") or val.get("songs")):
                target_dicts.append(val)
                # Untuk playlist/album, cukup ambil 1 objek koleksi utama agar tidak tercampur rekomendasi
                if url_type in ("playlist", "album"):
                    break

    # 3. Fallback Terakhir: Jika masih kosong, baru cek semua kandidat
    if not target_dicts:
        target_dicts = [val for _, val in candidates]

    songs: dict[str, dict] = {}

    for val in target_dicts:
        if (val.get("name") or val.get("title")):
            page_info["title"] = (val.get("name") or val.get("title") or "").strip()
        if val.get("artistName"):
            page_info["artist"] = val.get("artistName", "").strip()
        if val.get("image") or val.get("avatar") or val.get("thumbURL"):
            page_info["cover"] = val.get("image") or val.get("avatar") or val.get("thumbURL")
        if val.get("dateCreate") or val.get("dateRelease"):
            page_info["release_date"] = str(val.get("dateCreate") or val.get("dateRelease"))

        total_items = val.get("numOfItems") or val.get("total") or val.get("totalSong") or 0
        if isinstance(total_items, int) and total_items > 0:
            page_info["expected_total"] = total_items

        # Single song
        if "streamURL" in val and ("name" in val or "title" in val):
            s = parse_song(val, quality_pref)
            if s and s["key"] not in songs:
                songs[s["key"]] = s

        # Daftar lagu dalam playlist / album / artist
        song_list = val.get("listSong") or val.get("songs") or []
        if isinstance(song_list, list):
            for song_data in song_list:
                if not isinstance(song_data, dict):
                    continue
                s = parse_song(song_data, quality_pref)
                if s and s["key"] not in songs:
                    songs[s["key"]] = s

    result_list = list(songs.values())
    if page_info["expected_total"] > 0 and url_type in ("playlist", "album"):
        result_list = result_list[:page_info["expected_total"]]

    return result_list, page_info


async def capture_via_click(context: BrowserContext, song_url: str) -> dict | None:
    """Fallback untuk halaman lagu tunggal jika __NUXT__ tidak memuat streamURL."""
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
    songs: dict[str, dict] = {}
    page_info = {"title": "", "artist": "", "cover": "", "release_date": "", "expected_total": 0}
    url_type = get_url_type(url)

    try:
        await page.goto(url, wait_until="networkidle", timeout=60_000)

        async def harvest():
            nonlocal page_info
            extracted, p_info = await extract_nuxt_data(page, url, quality_pref)
            for k, v in p_info.items():
                if v and not page_info.get(k):
                    page_info[k] = v
            for s in extracted:
                if s["key"] not in songs:
                    songs[s["key"]] = s

        await harvest()

        # Lakukan scroll HANYA untuk halaman artist (atau jika lagu belum memenuhi expected_total)
        should_scroll = (
            url_type == "artist"
            or (page_info["expected_total"] > len(songs))
        )

        if should_scroll:
            for _ in range(15):
                if page_info["expected_total"] > 0 and len(songs) >= page_info["expected_total"]:
                    break

                prev = len(songs)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1.2)

                for selector in [
                    ".btn-more", ".btn-loadmore", ".btn-xem-them",
                    '[class*="load-more"]', '[class*="loadmore"]',
                ]:
                    try:
                        btn = page.locator(selector).first
                        if await btn.is_visible(timeout=400):
                            await btn.click()
                            await asyncio.sleep(1.5)
                    except Exception:
                        pass

                await harvest()
                if len(songs) == prev:
                    break

        if not songs and url_type in ("song", "unknown"):
            info = await capture_via_click(context, url)
            if info:
                songs[info["key"]] = info
    finally:
        try:
            await page.close()
        except Exception:
            pass
        try:
            await context.close()
        except Exception:
            pass

    final_songs = list(songs.values())
    if page_info["expected_total"] > 0 and url_type in ("playlist", "album"):
        final_songs = final_songs[:page_info["expected_total"]]

    return final_songs, page_info


async def direct_http_download(url: str, filepath: str) -> bool:
    """Fallback pengunduhan langsung via aiohttp jika Aria2 gagal."""
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
    track_meta["tempfolder"] = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/"

    cover_url = song.get("cover") or collection_meta.get("raw_cover") or ""
    if collection_meta.get("cover") and os.path.exists(str(collection_meta["cover"])):
        track_meta["cover"] = collection_meta["cover"]
        track_meta["thumbnail"] = collection_meta["cover"]
    elif cover_url:
        track_meta["cover"] = await create_cover_file(cover_url, track_meta)
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

    # --- 1. SINGLE SONG ---
    if url_type == "song" or (len(songs) == 1 and url_type == "unknown"):
        song = songs[0]
        folderpath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/NhacCuaTui/"
        os.makedirs(folderpath, exist_ok=True)

        col_meta = {
            "title": song["title"],
            "artist": song.get("artist") or page_info.get("artist") or "Unknown Artist",
            "raw_cover": song.get("cover") or page_info.get("cover") or "",
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
    raw_cover = page_info.get("cover") or songs[0].get("cover") or ""

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
    collection_meta["tempfolder"] = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/"
    collection_meta["raw_cover"] = raw_cover
    collection_meta["release_date"] = page_info.get("release_date", "")
    collection_meta["date"] = page_info.get("release_date", "")[:4] if page_info.get("release_date") else ""

    if raw_cover:
        collection_meta["cover"] = await create_cover_file(raw_cover, collection_meta)
        collection_meta["thumbnail"] = collection_meta["cover"]

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
