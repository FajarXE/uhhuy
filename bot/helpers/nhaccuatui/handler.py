# [GANTI TOTAL ISI FILE: bot/helpers/nhaccuatui/handler.py]

import os
import re
import copy
import shutil
import asyncio
import aiohttp
import aiofiles
from pathlib import Path
from urllib.parse import urlparse, quote_plus
from datetime import datetime
from PIL import Image
from playwright.async_api import Page, BrowserContext

from config import Config
from bot.logger import LOGGER
from bot.settings import bot_set
from bot.helpers.metadata import metadata as base_metadata, set_metadata
from bot.helpers.utils import (
    download_file,
    run_concurrent_tasks,
    post_art_poster,
)
from bot.helpers.uploder import (
    track_upload,
    album_upload,
    playlist_upload,
)
from .manager import nhaccuatui_manager, HEADERS

AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".flac")


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", str(name or ""))
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180] or "Unknown"


def get_url_type(url: str) -> str:
    path = urlparse(url).path.lower()
    if "/album/" in path:
        return "album"
    if "/bai-hat/" in path or "/song/" in path:
        return "song"
    if "/chart/" in path or "/bxh/" in path:
        return "chart"
    return "unsupported"


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

    # Format DD/MM/YYYY atau DD-MM-YYYY
    m_dmy = re.search(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', s)
    if m_dmy:
        day = m_dmy.group(1).zfill(2)
        month = m_dmy.group(2).zfill(2)
        year = m_dmy.group(3)
        return f"{year}-{month}-{day}", year

    # Format YYYY-MM-DD atau YYYY/MM/DD
    m_ymd = re.search(r'(\d{4})[-/](\d{2})[-/](\d{2})', s)
    if m_ymd:
        return f"{m_ymd.group(1)}-{m_ymd.group(2)}-{m_ymd.group(3)}", m_ymd.group(1)

    m_year = re.search(r'\b(19\d{2}|20\d{2})\b', s)
    if m_year:
        return m_year.group(1), m_year.group(1)

    return s, s[:4] if len(s) >= 4 else ""


async def fetch_itunes_cover(title: str, artist: str) -> str:
    clean_title = re.sub(r'\(.*?\)|\[.*?\]', '', title).strip()
    clean_artist = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip()
    query = f"{clean_title} {clean_artist}".strip()
    if not query:
        return ""

    url = f"https://itunes.apple.com/search?term={quote_plus(query)}&entity=song&limit=3"
    timeout = aiohttp.ClientTimeout(total=5)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results", [])
                    if results:
                        art = results[0].get("artworkUrl100", "")
                        if art:
                            high_res = re.sub(r'\d+x\d+bb', '3000x3000bb', art)
                            LOGGER.info(f"NhacCuaTui: Cover resolusi tinggi ditemukan di iTunes -> {high_res}")
                            return high_res
    except Exception as e:
        LOGGER.debug(f"NhacCuaTui: iTunes cover fallback gagal: {e}")

    return ""


async def upgrade_cover_url(url: str) -> str:
    if not url or not isinstance(url, str):
        return ""

    clean_url = url.split("?")[0].strip()

    clean_base = re.sub(r'_(?:\d+x\d+|\d+_\d+|\d+|thumb|small|medium|large|avatar)\.([a-zA-Z0-9]+)$', r'.\1', clean_url, flags=re.I)
    m = re.search(r'^(.*?)\.([a-zA-Z0-9]+)$', clean_base)
    if not m:
        return clean_url

    raw_base = m.group(1)
    ext = m.group(2)

    base_variants = [raw_base]
    if "/song/" in raw_base:
        base_variants.append(raw_base.replace("/song/", "/playlist/"))
    if "/playlist/" in raw_base:
        base_variants.append(raw_base.replace("/playlist/", "/song/"))

    desired_sizes = (
        "_2000.", "_1500.", "_1200.", "_1000.", "_800.",
        "_600.", "_500.", "_600x600.", "_500x500.",
        "_org.", "_original.",
        "_300.", "_300x300."
    )

    candidates = []
    for sz in desired_sizes:
        for b in base_variants:
            candidates.append(f"{b}{sz}{ext}")

    for b in base_variants:
        candidates.append(f"{b}.{ext}")

    async def verify_candidate(session, cand_url):
        try:
            timeout = aiohttp.ClientTimeout(total=3.0)
            async with session.get(cand_url, timeout=timeout, allow_redirects=True) as resp:
                if resp.status == 200:
                    ct = resp.headers.get("content-type", "").lower()
                    if "image" in ct or "octet-stream" in ct:
                        await resp.content.read(64)
                        return cand_url
        except Exception:
            pass
        return None

    try:
        connector = aiohttp.TCPConnector(ssl=False)
        timeout_session = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(headers=HEADERS, connector=connector, timeout=timeout_session) as session:
            tasks = [verify_candidate(session, c) for c in candidates]
            results = await asyncio.gather(*tasks)
            valid_urls = set(r for r in results if r)

            for c in candidates:
                if c in valid_urls:
                    LOGGER.info(f"NhacCuaTui: Cover resolusi tinggi ditemukan di NixCDN -> {c}")
                    return c
    except Exception as e:
        LOGGER.warning(f"NhacCuaTui: Gagal memeriksa varian cover: {e}")

    return clean_url


async def save_optimized_cover(url: str, dest_folder: str, title: str = "", artist: str = "") -> tuple[str, str]:
    if not url:
        return "", ""
    os.makedirs(dest_folder, exist_ok=True)
    raw_path = os.path.join(dest_folder, "cover_raw.tmp")
    full_path = os.path.join(dest_folder, "cover.jpg")
    thumb_path = os.path.join(dest_folder, "cover_thumb.jpg")

    async def download_to_raw(target_url):
        try:
            connector = aiohttp.TCPConnector(ssl=False)
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(headers=HEADERS, connector=connector, timeout=timeout) as session:
                async with session.get(target_url) as resp:
                    if resp.status == 200:
                        async with aiofiles.open(raw_path, "wb") as f:
                            async for chunk in resp.content.iter_chunked(65536):
                                await f.write(chunk)
                        return True
        except Exception:
            pass
        return False

    downloaded = await download_to_raw(url)

    need_itunes_fallback = False
    if downloaded and os.path.exists(raw_path):
        try:
            with Image.open(raw_path) as test_img:
                w, h = test_img.size
                if w < 500 or h < 500:
                    need_itunes_fallback = True
        except Exception:
            need_itunes_fallback = True
    else:
        need_itunes_fallback = True

    if need_itunes_fallback and title:
        itunes_url = await fetch_itunes_cover(title, artist)
        if itunes_url:
            ok = await download_to_raw(itunes_url)
            if ok:
                downloaded = True

    if not downloaded or not os.path.exists(raw_path):
        return "", ""

    try:
        def _process():
            with Image.open(raw_path) as img:
                img_rgb = img.convert("RGB")
                w, h = img_rgb.size
                LOGGER.info(f"NhacCuaTui: Cover final tersimpan dengan resolusi {w}x{h}")

                img_rgb.save(full_path, "JPEG", quality=95, optimize=True)

                thumb = img_rgb.copy()
                thumb.thumbnail((320, 320), Image.Resampling.LANCZOS)
                thumb.save(thumb_path, "JPEG", quality=85, optimize=True)

            if os.path.exists(raw_path):
                os.remove(raw_path)

        await asyncio.to_thread(_process)
        if os.path.exists(full_path) and os.path.getsize(full_path) > 0:
            return full_path, thumb_path
    except Exception as e:
        LOGGER.warning(f"NhacCuaTui: Gagal memproses cover: {e}")
        if os.path.exists(raw_path):
            try:
                os.rename(raw_path, full_path)
                return full_path, full_path
            except Exception:
                pass
    return "", ""


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
        song_data.get("coverImage")
        or song_data.get("image")
        or song_data.get("avatar")
        or song_data.get("thumbURL")
        or song_data.get("bgImage")
        or ""
    )

    genre = (
        song_data.get("genreName")
        or song_data.get("genreTitle")
        or (song_data.get("genre", {}).get("name") if isinstance(song_data.get("genre"), dict) else song_data.get("genre"))
        or (song_data.get("genres")[0].get("name") if isinstance(song_data.get("genres"), list) and song_data.get("genres") and isinstance(song_data.get("genres")[0], dict) else "")
        or song_data.get("categoryName")
        or ""
    )

    # Ambil album dan tanggal rilis asli milik lagu
    album_name = (
        song_data.get("albumName")
        or song_data.get("albumTitle")
        or (song_data.get("album", {}).get("name") if isinstance(song_data.get("album"), dict) else song_data.get("album"))
        or ""
    )

    raw_song_date = song_data.get("dateCreate") or song_data.get("dateRelease") or song_data.get("publishDate")
    rel_date, year_val = parse_nct_date(raw_song_date)

    return {
        "key": song_data.get("key") or name,
        "title": name,
        "artist": artist_name or "Unknown Artist",
        "album": str(album_name).strip(),
        "date": year_val,
        "release_date": rel_date,
        "audio_url": audio_url,
        "quality": stream.get("typeUI") or f"{stream.get('type', quality_pref)}kbps",
        "cover": cover_url,
        "duration": song_data.get("duration") or 0,
        "explicit": False,
        "genre": str(genre).strip(),
    }


async def extract_nuxt_data(page: Page, url: str, quality_pref: str) -> tuple[list[dict], dict]:
    url_key = extract_url_key(url)
    url_type = get_url_type(url)

    extracted_payload = await page.evaluate(r"""(args) => {
        const { urlKey, urlType } = args;
        const nuxt = window.__NUXT__ || {};

        const getMeta = (prop) => {
            const el = document.querySelector(`meta[property="${prop}"], meta[name="${prop}"]`);
            return el ? el.getAttribute('content') : '';
        };

        const pageTitle = (getMeta('og:title') || document.title || '').replace(/\s*[-|]\s*NhacCuaTui.*$/i, '').trim();
        const pageImage = getMeta('og:image') || getMeta('twitter:image') || '';
        const pageGenre = getMeta('music:genre') || getMeta('genre') || '';

        const collections = [];
        const singleSongs = [];
        const seen = new Set();

        function search(obj, depth = 0, path = "") {
            if (!obj || typeof obj !== "object" || depth > 8 || seen.has(obj)) return;
            seen.add(obj);

            if (Array.isArray(obj)) {
                obj.forEach((item, idx) => search(item, depth + 1, `${path}[${idx}]`));
                return;
            }

            if (obj.streamURL && (obj.name || obj.title)) {
                singleSongs.push(obj);
            }

            const list = obj.listSong || obj.songs || obj.songList || obj.items;
            if (Array.isArray(list) && list.length > 0) {
                const sample = list[0];
                if (sample && (sample.name || sample.title || sample.streamURL || sample.key)) {
                    collections.push({
                        key: String(obj.key || obj.id || obj.albumKey || obj.chartKey || ''),
                        name: String(obj.name || obj.title || obj.chartName || ''),
                        artistName: String(obj.artistName || ''),
                        image: obj.coverImage || obj.image || obj.avatar || obj.thumbURL || obj.bgImage || '',
                        date: obj.dateCreate || obj.dateRelease || obj.publishDate || '',
                        genre: obj.genreName || obj.genreTitle || (obj.genre && obj.genre.name) || obj.categoryName || '',
                        total: obj.numOfItems || obj.total || obj.totalSong || list.length,
                        listSong: list,
                        path: path
                    });
                }
            }

            for (const k of Object.keys(obj)) {
                if (k !== 'listSong' && k !== 'songs' && k !== 'songList') {
                    search(obj[k], depth + 1, `${path}.${k}`);
                }
            }
        }

        search(nuxt);

        let bestCol = null;
        if (collections.length > 0) {
            let bestScore = -9999;
            const negWords = ['recommend', 'suggest', 'gợi ý', 'đề xuất', 'maybe'];
            const boostWords = urlType === 'chart' 
                ? ['chart', 'ranking', 'bxh', 'bảng xếp hạng', 'top'] 
                : [];

            for (const col of collections) {
                let score = 0;
                const colName = col.name.toLowerCase();
                const colPath = col.path.toLowerCase();

                for (const neg of negWords) {
                    if (colName.includes(neg) || colPath.includes(neg)) score -= 200;
                }

                for (const boost of boostWords) {
                    if (colName.includes(boost) || colPath.includes(boost)) score += 250;
                }

                if (urlKey) {
                    const uKey = urlKey.toLowerCase();
                    if (col.key.toLowerCase() === uKey) score += 500;
                    if (colPath.includes(uKey)) score += 300;
                }

                if (pageTitle && col.name) {
                    const cTitle = pageTitle.toLowerCase();
                    if (cTitle.includes(colName) || colName.includes(cTitle)) score += 150;
                }

                if (urlType === 'chart' && col.listSong.length >= 10) {
                    score += 150;
                }

                if (score > bestScore) {
                    bestScore = score;
                    bestCol = col;
                }
            }
        }

        return {
            pageTitle,
            pageImage,
            pageGenre,
            bestCol,
            singleSongs
        };
    }""", {"urlKey": url_key, "urlType": url_type})

    page_info = {
        "title": extracted_payload.get("pageTitle", ""),
        "artist": "",
        "cover": extracted_payload.get("pageImage", ""),
        "genre": extracted_payload.get("pageGenre", ""),
        "release_date": "",
        "date": "",
        "explicit": False,
    }

    best_col = extracted_payload.get("bestCol")
    songs = []

    if url_type == "song":
        for raw_s in extracted_payload.get("singleSongs", []):
            s = parse_song(raw_s, quality_pref)
            if s:
                songs.append(s)
                if not page_info["title"]:
                    page_info["title"] = s["title"]
                if not page_info["artist"]:
                    page_info["artist"] = s["artist"]
                if not page_info["genre"] and s.get("genre"):
                    page_info["genre"] = s["genre"]
                if not page_info["cover"] and s.get("cover"):
                    page_info["cover"] = s["cover"]
                break

    elif url_type in ("album", "chart") and best_col:
        col_name = best_col.get("name", "").strip()

        # Jangan gunakan nama koleksi jika hanya berupa tanggal (misal 12/10/2026)
        is_just_date = bool(re.match(r'^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$', col_name))
        if col_name and not is_just_date:
            page_info["title"] = col_name
        elif not page_info["title"]:
            page_info["title"] = "BXH NhacCuaTui" if url_type == "chart" else "NhacCuaTui Album"

        if best_col.get("artistName"):
            page_info["artist"] = best_col["artistName"].strip()
        if best_col.get("genre"):
            page_info["genre"] = best_col["genre"].strip()

        raw_cov = page_info.get("cover") or best_col.get("image") or ""
        page_info["cover"] = await upgrade_cover_url(raw_cov)

        rel_date, year_date = parse_nct_date(best_col.get("date"))
        page_info["release_date"] = rel_date
        page_info["date"] = year_date

        for raw_s in best_col.get("listSong", []):
            s = parse_song(raw_s, quality_pref)
            if s:
                if not s.get("genre") and page_info.get("genre"):
                    s["genre"] = page_info["genre"]
                songs.append(s)

        expected_total = best_col.get("total")
        if isinstance(expected_total, int) and expected_total > 0 and url_type == "album":
            songs = songs[:expected_total]

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
            result["genre"] = "Pop"
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

        if not songs and url_type == "song":
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
    
    # Pengaturan Album: jika chart, utamakan album asli lagu atau jadikan judul lagu itu sendiri (bukan tanggal chart)
    is_chart = collection_meta.get("type") == "playlist"
    if is_chart:
        track_meta["album"] = song.get("album") or song["title"]
        track_meta["date"] = song.get("date") or ""
        track_meta["release_date"] = song.get("release_date") or ""
    else:
        track_meta["album"] = collection_meta.get("title") or song["title"]
        track_meta["date"] = song.get("date") or collection_meta.get("date", "")
        track_meta["release_date"] = song.get("release_date") or collection_meta.get("release_date", "")

    track_meta["tracknumber"] = str(index)
    track_meta["totaltracks"] = str(total_tracks)
    track_meta["volume"] = "1"
    track_meta["totalvolume"] = "1"
    track_meta["duration"] = song.get("duration") or 0
    track_meta["quality"] = song.get("quality") or f"{nhaccuatui_manager.get_user_quality(user['user_id'])}kbps"
    track_meta["extension"] = ext_clean
    track_meta["provider"] = "NhacCuaTui"
    track_meta["type"] = "track"
    track_meta["explicit"] = False
    track_meta["tempfolder"] = collection_meta.get("tempfolder", f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/")

    final_genre = song.get("genre") or collection_meta.get("genre") or "Pop"
    track_meta["genre"] = str(final_genre).strip()

    track_meta["composer"] = song.get("composer") or collection_meta.get("composer") or track_meta["artist"]
    track_meta["producer"] = song.get("producer") or collection_meta.get("producer") or track_meta["artist"]
    track_meta["publisher"] = song.get("publisher") or collection_meta.get("publisher") or "NhacCuaTui"
    track_meta["label"] = track_meta["publisher"]
    track_meta["pub"] = track_meta["publisher"]
    
    release_year = track_meta["date"] or (track_meta["release_date"][:4] if track_meta["release_date"] else datetime.now().year)
    track_meta["copyright"] = song.get("copyright") or collection_meta.get("copyright") or f"© {release_year} {track_meta['publisher']}"
    track_meta["cpr"] = track_meta["copyright"]
    track_meta["isrc"] = song.get("isrc") or collection_meta.get("isrc") or ""

    # Cover Handling: Album memakai cover album bersama, Chart memakai cover asli masing-masing lagu
    is_album = collection_meta.get("type") == "album"

    if is_album and collection_meta.get("cover") and os.path.exists(str(collection_meta["cover"])):
        track_meta["cover"] = collection_meta["cover"]
        track_meta["thumbnail"] = collection_meta.get("thumbnail") or collection_meta["cover"]
    else:
        raw_song_cover = song.get("cover") or collection_meta.get("raw_cover") or ""
        track_cover_folder = os.path.join(track_meta["tempfolder"], f"track_{index}")
        if raw_song_cover:
            upgraded = await upgrade_cover_url(raw_song_cover)
            f_cov, t_cov = await save_optimized_cover(
                upgraded, track_cover_folder,
                title=track_meta["title"], artist=track_meta["artist"]
            )
            track_meta["cover"] = f_cov or collection_meta.get("cover", "")
            track_meta["thumbnail"] = t_cov or collection_meta.get("thumbnail", "")
        else:
            track_meta["cover"] = collection_meta.get("cover", "")
            track_meta["thumbnail"] = collection_meta.get("thumbnail", "")

    safe_title = sanitize_filename(song["title"])
    safe_artist = sanitize_filename(track_meta["artist"])
    
    if is_single:
        fname = f"{safe_title} - {safe_artist}.{ext_clean}"
    else:
        fname = f"{index:02d} - {safe_title} - {safe_artist}.{ext_clean}"

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

    if url_type == "unsupported":
        raise Exception("NhacCuaTui saat ini mendukung tautan Lagu Tunggal (/bai-hat/ atau /song/), Album (/album/), dan Chart (/chart/ atau /bxh/). Link Playlist dan Artist tidak didukung.")

    songs, page_info = await collect_songs(link, qual_pref)
    if not songs:
        raise Exception("Tidak ditemukan lagu yang dapat diunduh dari link NhacCuaTui tersebut (Khusus VIP atau link tidak valid).")

    temp_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/"
    os.makedirs(temp_folder, exist_ok=True)

    col_title = page_info.get("title") or ("BXH NhacCuaTui" if url_type == "chart" else "NhacCuaTui Album")
    if re.match(r'^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$', col_title.strip()):
        col_title = "BXH NhacCuaTui"

    col_artist = page_info.get("artist") or ("NhacCuaTui" if url_type == "chart" else "Various Artists")

    full_cover = ""
    thumb_cover = ""
    raw_cover = page_info.get("cover") or songs[0].get("cover") or ""
    if raw_cover:
        high_res_url = await upgrade_cover_url(raw_cover)
        full_cover, thumb_cover = await save_optimized_cover(
            high_res_url, temp_folder, title=col_title, artist=col_artist
        )

    # --- 1. SINGLE SONG ---
    if url_type == "song":
        song = songs[0]
        folderpath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/NhacCuaTui/"
        os.makedirs(folderpath, exist_ok=True)

        col_meta = {
            "title": song["title"],
            "artist": song.get("artist") or page_info.get("artist") or "Unknown Artist",
            "cover": full_cover,
            "thumbnail": thumb_cover or full_cover,
            "raw_cover": raw_cover,
            "genre": song.get("genre") or page_info.get("genre") or "Pop",
            "date": song.get("date") or page_info.get("date", ""),
            "release_date": song.get("release_date") or page_info.get("release_date", ""),
            "tempfolder": temp_folder,
            "type": "track",
        }
        track_meta = await download_single_nct_track(
            song, 1, 1, folderpath, col_meta, user, is_single=True
        )
        if not track_meta:
            raise Exception(f"Gagal mengunduh lagu: {song['title']}")

        await track_upload(track_meta, user)
        return

    # --- 2. ALBUM ATAU CHART ---
    col_type = "album" if url_type == "album" else "playlist"
    folderpath = os.path.join(
        f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/NhacCuaTui",
        sanitize_filename(col_title),
    )
    os.makedirs(folderpath, exist_ok=True)

    if full_cover and os.path.exists(full_cover):
        album_cover_dest = os.path.join(folderpath, "cover.jpg")
        shutil.copy2(full_cover, album_cover_dest)

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
    collection_meta["cover"] = full_cover
    collection_meta["thumbnail"] = thumb_cover or full_cover
    collection_meta["genre"] = page_info.get("genre") or (songs[0].get("genre") if songs else "Pop") or "Pop"
    collection_meta["release_date"] = page_info.get("release_date", "")
    collection_meta["date"] = page_info.get("date", "")
    collection_meta["explicit"] = False

    if full_cover:
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
        "type": "Chart" if url_type == "chart" else "Album",
        "action": "Download",
    }

    results = await run_concurrent_tasks(tasks, update_details)
    valid_tracks = [r for r in results if isinstance(r, dict) and r.get("filepath")]

    if not valid_tracks:
        raise Exception("Semua lagu dalam koleksi gagal diunduh.")

    collection_meta["tracks"] = valid_tracks
    collection_meta["albums"] = [{"tracks": valid_tracks}]

    if thumb_cover and os.path.exists(thumb_cover):
        collection_meta["cover"] = thumb_cover

    if url_type == "album":
        await album_upload(collection_meta, user)
    else:
        await playlist_upload(collection_meta, user)
