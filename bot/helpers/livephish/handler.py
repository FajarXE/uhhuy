# [GANTI FILE: bot/helpers/livephish/handler.py]

import re
import os
import shutil
import aiohttp
import asyncio
import urllib.parse
from datetime import datetime
from config import Config
from bot.helpers.livephish.manager import livephish_manager
from bot.helpers.metadata import set_metadata, create_cover_file

# Import Helper standar
from bot.helpers.utils import download_file, zip_handler, fetch_zip_settings, run_concurrent_tasks
from bot.helpers.uploder import track_upload, album_upload, post_art_poster
from bot.helpers.message import edit_message
from bot.logger import LOGGER

# Regex ID LivePhish
ID_REGEX = re.compile(r'(?:catalog/recording/|browse/music/0,|release/|show=)(\d+)')

# Tag Branding
BRANDING_TAG = "powered by livephish.com"

def sanitize_name(name):
    """Membersihkan nama file/folder."""
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

def format_date_standard(date_str):
    """Mengubah format tanggal LivePhish menjadi standar ISO (YYYY-MM-DD)."""
    if not date_str: return ""
    date_str = str(date_str).strip()
    formats = ["%m/%d/%Y", "%Y/%m/%d", "%Y-%m-%d", "%b %d, %Y", "%d/%m/%Y"]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError: continue
    return date_str.replace("/", "-")

# --- FUNGSI DEEP SEARCH ---
def find_deep_value(data, target_keys):
    """Mencari nilai secara rekursif dalam JSON."""
    if isinstance(target_keys, str): target_keys = [target_keys]
    if isinstance(data, dict):
        for k, v in data.items():
            if k.lower() in [tk.lower() for tk in target_keys] and v:
                return str(v)
            found = find_deep_value(v, target_keys)
            if found: return found
    elif isinstance(data, list):
        for item in data:
            found = find_deep_value(item, target_keys)
            if found: return found
    return ""

def find_deep_genre(data):
    """Deep search khusus Genre (menangani List/Dict)."""
    target_keys = ["styles", "genres", "genre", "style", "tags", "subGenre"]
    if isinstance(data, dict):
        for k, v in data.items():
            if k.lower() in target_keys and v:
                if isinstance(v, list) and len(v) > 0:
                    first = v[0]
                    if isinstance(first, dict):
                        name = first.get("name") or first.get("description")
                        if name: return str(name)
                    else: return str(first)
                elif isinstance(v, str): return v
            if isinstance(v, (dict, list)):
                found = find_deep_genre(v)
                if found: return found
    elif isinstance(data, list):
        for item in data:
            found = find_deep_genre(item)
            if found: return found
    return ""

# --- FUNGSI HITUNG DURASI ASLI (FFPROBE) ---
async def get_audio_duration(file_path):
    """
    Menggunakan FFprobe untuk membaca durasi file ASLI di disk.
    Ini mengatasi masalah durasi -:-- di Telegram.
    """
    try:
        cmd = [
            "ffprobe", 
            "-v", "error", 
            "-show_entries", "format=duration", 
            "-of", "default=noprint_wrappers=1:nokey=1", 
            file_path
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if stdout:
            return int(float(stdout.decode().strip()))
    except Exception as e:
        LOGGER.warning(f"Gagal get duration ffprobe: {e}")
    
    return 0

# --- TEKNIK BRUTE FORCE COVER HD ---
async def fetch_website_cover_hd(url):
    """Mencari cover art resolusi MAKSIMAL."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    pattern = r'(https?://(?:static\.livephish\.com|s3\.amazonaws\.com|static\.nugs\.net)/[^"\']+\.jpg)'
                    matches = re.findall(pattern, html)
                    candidate = None
                    for m in matches:
                        if "shows" in m or "pix" in m or "assets" in m:
                            candidate = m
                            break 
                    if not candidate:
                        match_og = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html)
                        if match_og: candidate = match_og.group(1)

                    if candidate:
                        if candidate.startswith("//"): candidate = "https:" + candidate
                        clean_url = re.sub(r'(_\d+|_v\d+|_mini|_med|_small|_large)(\.jpg)$', r'\2', candidate)
                        if clean_url != candidate:
                            try:
                                async with session.head(clean_url) as hd_resp:
                                    if hd_resp.status == 200: return clean_url
                            except: pass
                        return candidate
    except Exception as e:
        LOGGER.warning(f"Gagal scrape Cover Website: {e}")
    return None

async def clean_audio_metadata(input_path):
    """OPSI NUKLIR: Menghapus total metadata bawaan."""
    temp_output = input_path + ".clean.m4a"
    if input_path.endswith(".flac"):
        temp_output = input_path + ".clean.flac"
    try:
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-map_metadata", "-1", "-map_metadata:g", "-1",
            "-c", "copy", temp_output
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        if os.path.exists(temp_output) and os.path.getsize(temp_output) > 0:
            os.replace(temp_output, input_path)
            return True
    except:
        if os.path.exists(temp_output): os.remove(temp_output)
    return False

# --- FUNGSI WORKER (UNTUK ARIA2 CONCURRENT) ---
async def process_livephish_track(t, i, total_tracks, base_meta, client, user, max_disc, album_copyright, final_label, genre, release_date):
    """Fungsi mandiri untuk memproses dan mengunduh 1 lagu."""
    track_id = t.get("trackID") or t.get("songID")
    title = t.get("songTitle", f"Track {i+1}")
    
    raw_track_num = t.get("trackNum", i+1)
    track_num_padded = f"{int(raw_track_num):02d}"
    disc_num = t.get("discNum", 1)
    
    try: api_duration = int(float(t.get("length", 0)))
    except: api_duration = 0
        
    composer = t.get("author") or t.get("composer") or t.get("writer") or ""
    isrc_val = t.get("isrc") or t.get("ISRC") or ""
    track_c = find_deep_value(t, ["copyright", "copyRight", "rights", "license"]) or album_copyright

    try: stream_url = await client.get_stream_url(track_id, livephish_manager.quality)
    except: stream_url = None

    if not stream_url:
        LOGGER.error(f"Stream URL kosong: {title}")
        return None

    ext = ".m4a"
    if livephish_manager.quality == "FLAC": ext = ".flac"

    clean_title = sanitize_name(title)
    
    if int(base_meta['totalvolume']) > 1:
        disc_folder = os.path.join(base_meta['tempfolder'], f"Disc {disc_num}")
        os.makedirs(disc_folder, exist_ok=True)
        current_save_path = disc_folder
    else:
        current_save_path = base_meta['tempfolder']

    fname = f"{track_num_padded} - {clean_title}{ext}"
    full_file_path = os.path.join(current_save_path, fname)
    
    # --- PROSES DOWNLOAD ARIA2 ---
    err = await download_file(stream_url, full_file_path)
    if err:
        LOGGER.error(f"Download error {title}: {err}")
        return None

    # Cleaning & Metadata
    await clean_audio_metadata(full_file_path)
    real_duration = await get_audio_duration(full_file_path)
    final_duration = real_duration if real_duration > 0 else api_duration

    track_meta = base_meta.copy()
    track_meta.update({
        'title': title,
        'tracknumber': str(raw_track_num),
        'volume': str(disc_num),
        'filepath': full_file_path,
        'itemid': str(track_id),
        'duration': final_duration,
        'extension': ext.replace(".", ""),
        'isrc': isrc_val,
        'composer': composer,
        'label': final_label,
        'genre': genre
    })

    branding_dict = {
        'comment': BRANDING_TAG, 'COMMENT': BRANDING_TAG,
        'description': BRANDING_TAG, 'DESCRIPTION': BRANDING_TAG,
        'encoded_by': BRANDING_TAG, 'ENCODED_BY': BRANDING_TAG
    }
    track_meta.update(branding_dict)

    if ext == ".flac":
        track_meta['discnumber'] = f"{disc_num}/{max_disc}"
        track_meta['DISCNUMBER'] = f"{disc_num}/{max_disc}"
        track_meta['tracknumber'] = f"{raw_track_num}/{total_tracks}"
        track_meta['TRACKNUMBER'] = f"{raw_track_num}/{total_tracks}"
        track_meta['ORGANIZATION'] = final_label
        track_meta['LABEL'] = final_label
        track_meta['COMPOSER'] = composer
        track_meta['ISRC'] = isrc_val
        track_meta['GENRE'] = genre
        track_meta['COPYRIGHT'] = track_c
        track_meta['cpr'] = track_c
        track_meta['DATE'] = release_date
        track_meta['totaldiscs'] = str(max_disc)
        track_meta['totaltracks'] = str(total_tracks)
        
    elif ext == ".m4a":
        track_meta['discnumber'] = str(disc_num)
        track_meta['totaldiscs'] = str(max_disc)
        track_meta['tracknumber'] = str(raw_track_num)
        track_meta['totaltracks'] = str(total_tracks)
        track_meta['copyright'] = track_c
        track_meta['label'] = final_label
        track_meta['composer'] = composer
        track_meta['genre'] = genre
        track_meta['date'] = release_date

    await set_metadata(track_meta, user['user_id'])
    return track_meta


async def start_livephish(link: str, user: dict):
    client = user.get('livephish_api')
    if not client: raise Exception("Internal Error: LivePhish Client not passed.")

    match = ID_REGEX.search(link)
    if not match: raise Exception(f"Gagal mengekstrak Album ID dari link: {link}")
    album_id = match.group(1)

    await edit_message(user['bot_msg'], f"Mengambil metadata ID: {album_id}...")
    
    meta_json = await client.get_album_meta(album_id)
    resp = meta_json.get("Response", {})
    if not resp: raise Exception(f"Gagal metadata ID {album_id}: Response kosong.")

    # --- METADATA ALBUM ---
    raw_album = resp.get("containerInfo", "Unknown Album")
    raw_artist = resp.get("artistName", "Phish")
    album_name = sanitize_name(raw_album)
    artist_name = sanitize_name(raw_artist)
    
    raw_date = ""
    for k in ["performanceDate", "releaseDateFormatted", "performanceDateFormatted", "performanceDateYear"]:
        if resp.get(k):
            raw_date = str(resp.get(k))
            break
    release_date = format_date_standard(raw_date)
    year = release_date[:4] if len(release_date) >= 4 else ""

    genre = find_deep_genre(resp)
    album_copyright = find_deep_value(resp, ["copyright", "copyRight", "rights", "license"])
    label = find_deep_value(resp, ["recordLabel", "label"])

    if not album_copyright and label:
        album_copyright = f"© {year} {label}"
    elif not album_copyright:
        album_copyright = f"© {year} {artist_name}"

    final_label = label if label else artist_name

    tracks = resp.get("tracks", [])
    total_tracks = len(tracks)
    max_disc = 1
    for t in tracks:
        d = t.get("discNum", 1)
        if d > max_disc: max_disc = d

    folder_name = f"{artist_name} - {album_name}"
    if len(folder_name) > 150: folder_name = folder_name[:150]
    base_folder_path = os.path.join(Config.DOWNLOAD_BASE_DIR, str(user['r_id']), folder_name)

    # --- DOWNLOAD COVER ---
    cover_url = None
    LOGGER.info("Mencari cover art HD via Web Scraper...")
    cover_url = await fetch_website_cover_hd(link)
        
    if not cover_url:
        pics = resp.get("pics", [])
        if pics:
            pics.sort(key=lambda x: x.get("width", 0), reverse=True)
            for p in pics:
                if p.get("url"): 
                    raw_url = p.get("url")
                    if raw_url.startswith("/"): cover_url = "https://static.livephish.com" + raw_url
                    else: cover_url = raw_url
                    break

    final_cover_path = ""
    if cover_url:
        try:
            temp_path = await create_cover_file(
                cover_url, {"itemid": album_id, "tempfolder": str(user['r_id']) + "/"}
            )
            if temp_path and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                 if "project-siesta" not in temp_path:
                    if not os.path.exists(base_folder_path):
                        os.makedirs(base_folder_path, exist_ok=True)
                    new_cover_path = os.path.join(base_folder_path, "cover.jpg")
                    shutil.move(temp_path, new_cover_path)
                    final_cover_path = new_cover_path
        except Exception as e:
            LOGGER.error(f"Gagal download cover: {e}")

    base_meta = {
        'title': album_name,
        'album': album_name,
        'albumartist': artist_name,
        'artist': artist_name,
        'year': year,
        'date': release_date,
        'cover': final_cover_path,
        'totaltracks': str(total_tracks),
        'totalvolume': str(max_disc),
        'provider': 'LivePhish',
        'quality': livephish_manager.quality,
        'tempfolder': base_folder_path, 
        'type': 'album', 
        'genre': genre,
        'copyright': album_copyright,
        'label': final_label,
        'explicit': False
    }

    # --- [FIX UI] KIRIM POSTER DI AWAL SEBELUM DOWNLOAD ---
    try:
        base_meta['poster_msg'] = await post_art_poster(user, base_meta)
    except Exception as e:
        LOGGER.error(f"Gagal mengirim poster: {e}")
    # ------------------------------------------------------
    
    # --- [SUNTIKAN MESIN KONKURENSI ARIA2] ---
    tasks = []
    for i, t in enumerate(tracks):
        tasks.append(process_livephish_track(t, i, total_tracks, base_meta, client, user, max_disc, album_copyright, final_label, genre, release_date))

    update_details = {
        'text': "Mengunduh...",
        'msg': user['bot_msg'],
        'title': album_name,
        'type': 'Album'
    }
    
    # Gunakan batas limit=4 agar koneksi ke LivePhish aman dari blokir
    task_results = await run_concurrent_tasks(tasks, update_details, limit=4)
    completed_tracks = [res for res in task_results if res]
    # ----------------------------------------

    # --- UPLOAD ---
    if completed_tracks:
        base_meta['tracks'] = completed_tracks
        base_meta['folderpath'] = base_meta['tempfolder']
        
        playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

        if album_zip:
            await edit_message(user['bot_msg'], f"Membuat file ZIP...\n{album_name}")
            base_meta['zip_path'] = await zip_handler(base_meta['folderpath'])

        await edit_message(user['bot_msg'], f"Mengunggah...\n{album_name}")
        await album_upload(base_meta, user)
    else:
        raise Exception("Tidak ada track yang berhasil diunduh.")

