# [GANTI SELURUH FILE: bot/helpers/gaana/handler.py]

import os
import re
import asyncio
import shutil
import aiofiles
import aiohttp
from bot.logger import LOGGER
from bot.helpers.message import edit_message, send_message
from .manager import gaana_manager
from .metadata import set_gaana_metadata
from bot.helpers.uploder import track_upload, album_upload, playlist_upload
from bot import Config
from bot.helpers.utils import fetch_zip_settings, download_file, run_concurrent_tasks
import yt_dlp

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

URL_REGEX = re.compile(r"gaana\.com/(song|album|playlist)/(.+)")

def ensure_download_dir(user, subdir=None):
    base_dir = Config.DOWNLOAD_BASE_DIR
    uid = user.get('user_id', 'temp')
    user_dir = os.path.join(base_dir, str(uid))
    if subdir:
        user_dir = os.path.join(user_dir, sanitize_filename(subdir))
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    return user_dir

# --- FUNGSI MENGUNDUH GAMBAR ---
async def fetch_image(session, url, dest_path):
    if not url: return False
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                async with aiofiles.open(dest_path, mode='wb') as f:
                    await f.write(await resp.read())
                return True
    except: pass
    return False

async def start_gaana(link: str, user: dict):
    msg = user['bot_msg']
    session = gaana_manager.session
    api = gaana_manager.api

    match = URL_REGEX.search(link)
    if not match: return

    content_type, identifier = match.groups()
    if content_type == 'song':
        data = await api.get_metadata(session, identifier, 'songDetail')
        if data and 'tracks' in data:
            await process_single_gaana(data['tracks'][0], user, session, api)
    elif content_type == 'album':
        await process_album_gaana(identifier, user, session, api)
    elif content_type == 'playlist':
        await process_playlist_gaana(identifier, user, session, api)

# --- WORKER: FULL ARIA2 + HYBRID FALLBACK ---
async def _process_track_worker(track_info, i, total, dl_dir, user, session, api, is_batch=True):
    title = track_info.get("track_title", f"Track {i}")
    enc_path = track_info.get('urls', {}).get('auto', {}).get('message')
    if not enc_path: 
        LOGGER.warning(f"Gaana: Tidak ada stream URL untuk {title}")
        return None
    
    try:
        decrypted_url = api.decrypt_stream_path(enc_path)
    except Exception as e:
        LOGGER.error(e)
        return None

    final_url = decrypted_url
    if "medium.mp4" in final_url: final_url = final_url.replace("medium.mp4", "320.mp4")
    elif "128.mp4" in final_url: final_url = final_url.replace("128.mp4", "320.mp4")
    elif "f.mp4" in final_url: final_url = final_url.replace("f.mp4", "320.mp4")
    elif "64.mp4" in final_url: final_url = final_url.replace("64.mp4", "320.mp4")
    elif "low.mp4" in final_url: final_url = final_url.replace("low.mp4", "320.mp4")
    else: final_url = final_url.replace(".mp4", "_320.mp4")

    track_num = track_info.get('track_number') or i
    safe_title = sanitize_filename(title)
    filename = f"{int(track_num):02d} - {safe_title}.m4a"
    file_path = os.path.join(dl_dir, filename)

    # 1. Unduh Cover Lagu
    artwork_url = track_info.get('artwork', '')
    if artwork_url:
        artwork_url = re.sub(r'crop_\d+x\d+_', '', artwork_url)
        artwork_url = artwork_url.replace("size_s", "size_xl").replace("size_m", "size_xl")

    cover_path = os.path.join(dl_dir, f"{safe_title}.jpg")
    if not os.path.exists(cover_path):
        await fetch_image(session, artwork_url, cover_path)

    # 2. Mesin Aria2 + Penyamaran Headers
    headers_dict = api.headers
    details_aria = {'msg': None, 'headers': headers_dict} if is_batch else {
        'msg': user['bot_msg'], 'title': title, 'type': 'Track', 'headers': headers_dict
    }

    downloaded = False
    urls_to_try = [final_url, decrypted_url]
    for url in urls_to_try:
        # [KUNCI 1] Bersihkan file sampah dari percobaan sebelumnya!
        if os.path.exists(file_path):
            os.remove(file_path)
            
        err = await download_file(url, file_path, retries=1, details=details_aria)
        
        if not err and os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
            downloaded = True
            break
        else:
            LOGGER.warning(f"Gaana: Aria2 ditolak untuk {title}. Fallback ke AIOHTTP Turbo...")
            # [KUNCI 2] Hapus file sampah 301 bytes buatan Aria2 agar tidak menipu mesin fallback!
            if os.path.exists(file_path):
                os.remove(file_path)
                
            # --- Fallback 1: AIOHTTP Turbo ---
            try:
                async with session.get(url, headers=headers_dict) as resp:
                    if resp.status == 200:
                        async with aiofiles.open(file_path, mode='wb') as f:
                            async for chunk in resp.content.iter_chunked(256 * 1024):
                                if chunk: await f.write(chunk)
                        if os.path.getsize(file_path) > 10000:
                            downloaded = True
                            break
            except: pass
            
            # --- Fallback 2 & 3: Mesin FFmpeg & YT-DLP Terakhir ---
            if not downloaded:
                LOGGER.warning(f"Gaana: AIOHTTP gagal. Mendeteksi HLS Stream, mengeksekusi FFmpeg...")
                if os.path.exists(file_path):
                    os.remove(file_path)
                
                # 1. Gunakan FFmpeg Langsung (Sangat stabil untuk M3U8/Live Stream HLS)
                try:
                    ua = headers_dict.get('User-Agent', 'Mozilla/5.0')
                    # FFmpeg akan menyedot stream dan menjahitnya ke M4A secara otomatis!
                    cmd = f'ffmpeg -y -user_agent "{ua}" -i "{url}" -c copy "{file_path}"'
                    process = await asyncio.create_subprocess_shell(
                        cmd,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL
                    )
                    await process.communicate()
                    
                    if os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
                        downloaded = True
                        break
                except Exception as e:
                    LOGGER.error(f"FFmpeg Error: {e}")
                    pass
                
                # 2. Jika FFmpeg masih gagal, gunakan YT-DLP mode Standar (Tanpa argumen aneh yang bikin crash)
                if not downloaded:
                    try:
                        def run_ytdlp():
                            ydl_opts = {
                                'format': 'bestaudio/best', 
                                'outtmpl': file_path, 
                                'quiet': True,
                                'http_headers': headers_dict,
                            }
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([url])
                            
                        await asyncio.to_thread(run_ytdlp)
                        
                        if os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
                            downloaded = True
                            break
                    except Exception as e:
                        LOGGER.error(f"YT-DLP Error: {e}")
                        pass

    if not downloaded:
        LOGGER.error(f"Gagal mengunduh track {title}")
        return None

    # 3. Pasang Metadata
    dur = await set_gaana_metadata(file_path, track_info, cover_path if os.path.exists(cover_path) else None)

    artist_name = "Unknown"
    if track_info.get("artist"):
        artist_name = track_info["artist"][0]['name']

    return {
        'filepath': file_path, 'title': title,
        'artist': artist_name,
        'album': track_info.get("album_title", "Unknown Album"), 
        'cover': cover_path if os.path.exists(cover_path) else None, 
        'duration': dur, 'quality': '320kbps', 'provider': 'Gaana'
    }

async def process_single_gaana(track, user, session, api):
    msg = user['bot_msg']
    try:
        track['track_number'] = 1
        track['track_count'] = 1
        dl_dir = ensure_download_dir(user)
        
        res = await _process_track_worker(track, 1, 1, dl_dir, user, session, api, is_batch=False)
        if not res: raise Exception("Gagal mengunduh lagu.")
        
        res['type'] = 'track'
        # Langsung serahkan ke uploader untuk transisi mulus
        await track_upload(res, user)
    except Exception as e:
        await edit_message(msg, f"❌ Error: {e}")

async def process_album_gaana(identifier, user, session, api):
    msg = user['bot_msg']
    data = await api.get_metadata(session, identifier, 'albumDetail')
    
    if not data or 'tracks' not in data:
        await edit_message(msg, "❌ Album gagal diambil.")
        return

    tracks = data['tracks']
    album_title = data.get("title") or tracks[0].get("album_title") or "Unknown Album"
    dl_dir = ensure_download_dir(user, subdir=album_title)
    
    total = len(tracks)
    is_explicit = "False"
    for t in tracks:
        if t.get("parental_warning") == 1:
            is_explicit = "True"
            break
            
    release_date = data.get("release_date") or tracks[0].get("release_date", "Unknown")

    # --- [FIX UI] UNDUH COVER UTAMA & KIRIM POSTER DI AWAL ---
    final_cover_path = os.path.join(dl_dir, "cover.jpg")
    artwork_url = data.get('artwork', '') or tracks[0].get('artwork', '')
    if artwork_url:
        artwork_url = re.sub(r'crop_\d+x\d+_', '', artwork_url)
        artwork_url = artwork_url.replace("size_s", "size_xl").replace("size_m", "size_xl")
        await fetch_image(session, artwork_url, final_cover_path)
        
    _, is_album_zip, _, is_art_poster = fetch_zip_settings(user)
    poster_msg = None
    
    artist_name = "Unknown"
    if tracks and tracks[0].get("artist"):
        artist_name = tracks[0]["artist"][0]['name']

    if is_art_poster and os.path.exists(final_cover_path):
        try:
            caption = (
                f"**ᴛɪᴛʟᴇ :** {album_title}\n**ᴀʀᴛɪsᴛ :** {artist_name}\n"
                f"**ʀᴇʟᴇᴀsᴇ ᴅᴀᴛᴇ :** {release_date}\n**ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs :** {total}\n"
                f"**ᴛᴏᴛᴀʟ ᴠᴏʟᴜᴍᴇs :** 1\n**ǫᴜᴀʟɪᴛʏ :** 320kbps\n"
                f"**ᴘʀᴏᴠɪᴅᴇʀ :** Gaana\n**ᴇxᴘʟɪᴄɪᴛ :** {is_explicit}"
            )
            poster_msg = await send_message(user, final_cover_path, 'pic', caption=caption)
        except: pass
    # ---------------------------------------------------------

    # --- MESIN KONKURENSI ARIA2 ---
    async def wrap_track(track_raw, i):
        track_raw["track_number"] = i + 1
        track_raw["track_count"] = total
        track_raw["label_name"] = data.get("label_name", "Gaana")
        return await _process_track_worker(track_raw, i+1, total, dl_dir, user, session, api, is_batch=True)

    worker_tasks = [wrap_track(t, i) for i, t in enumerate(tracks)]
    update_details = {'msg': msg, 'title': album_title, 'type': 'Album', 'action': 'Download'}
    
    results = await run_concurrent_tasks(worker_tasks, update_details, limit=8)
    downloaded = [r for r in results if r]

    if not downloaded:
        await edit_message(msg, "❌ Gagal mengunduh semua lagu.")
        return

    # Pembersihan gambar sampah sebelum uploader mengambil alih
    for f in os.listdir(dl_dir):
        if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and f != "cover.jpg":
            try: os.remove(os.path.join(dl_dir, f))
            except: pass

    metadata = {
        'type': 'album', 'title': album_title, 'artist': artist_name, 
        'folderpath': dl_dir, 'tracks': downloaded, 'cover': final_cover_path if os.path.exists(final_cover_path) else None,
        # 'zip_path' dihapus agar diurus otomatis oleh uploader.py
        'poster_msg': poster_msg, 'provider': 'Gaana', 
        'release_date': release_date, 'totaltracks': str(total), 'totalvolumes': '1', 
        'explicit': is_explicit, 'quality': '320kbps'
    }
    await album_upload(metadata, user)

async def process_playlist_gaana(identifier, user, session, api):
    msg = user['bot_msg']
    data = await api.get_metadata(session, identifier, 'playlistDetail')
    
    if not data or 'tracks' not in data:
        await edit_message(msg, "❌ Playlist gagal diambil.")
        return

    tracks = data['tracks']
    title_candidates = [data.get("title"), data.get("name"), data.get("playlist_title"), data.get("english_title")]
    valid_titles = [t for t in title_candidates if t and str(t).strip()]
    title = valid_titles[0] if valid_titles else "Unknown Playlist"
    
    clean_identifier = identifier.replace("-", " ").title()
    if "Unknown" in title or title.lower() == identifier.lower(): title = clean_identifier
    title = re.sub(r'(?i)gaana\s*dj\s*', '', title).strip().replace("&amp;", "&")
    if not title: title = clean_identifier
    
    dl_dir = ensure_download_dir(user, subdir=title)
    total = len(tracks)

    # --- [FIX UI] POSTER PLAYLIST ---
    playlist_cover_path = os.path.join(dl_dir, "playlist_cover.jpg")
    artwork_url = data.get('artwork', '')
    if artwork_url:
        artwork_url = re.sub(r'crop_\d+x\d+_', '', artwork_url)
        artwork_url = artwork_url.replace("size_s", "size_xl").replace("size_m", "size_xl")
        await fetch_image(session, artwork_url, playlist_cover_path)
        
    _, is_pl_zip, _, is_art_poster = fetch_zip_settings(user)
    poster_msg = None
    
    # Fallback jika playlist tidak punya cover
    if not os.path.exists(playlist_cover_path):
        siesta_jpg = "project-siesta.jpg"
        siesta_png = "project-siesta.png"
        if os.path.exists(siesta_jpg): shutil.copy(siesta_jpg, playlist_cover_path)
        elif os.path.exists(siesta_png): shutil.copy(siesta_png, playlist_cover_path)

    if is_art_poster and os.path.exists(playlist_cover_path):
        try:
            caption = f"**ᴛɪᴛʟᴇ :** {title}\n**ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs :** {total}\n**ǫᴜᴀʟɪᴛʏ :** 320kbps\n**ᴘʀᴏᴠɪᴅᴇʀ :** Gaana"
            poster_msg = await send_message(user, playlist_cover_path, 'pic', caption=caption)
        except: pass
    # --------------------------------

    # --- MESIN KONKURENSI ARIA2 ---
    async def wrap_track(track_raw, i):
        track_raw["track_number"] = i + 1
        track_raw["track_count"] = total
        return await _process_track_worker(track_raw, i+1, total, dl_dir, user, session, api, is_batch=True)

    worker_tasks = [wrap_track(t, i) for i, t in enumerate(tracks)]
    update_details = {'msg': msg, 'title': title, 'type': 'Playlist', 'action': 'Download'}
    
    results = await run_concurrent_tasks(worker_tasks, update_details, limit=8)
    downloaded = [r for r in results if r]

    if not downloaded:
        await edit_message(msg, "❌ Gagal mengunduh playlist.")
        return

    # Pembersihan gambar sampah sebelum uploader mengambil alih
    for f in os.listdir(dl_dir):
        if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and f != "playlist_cover.jpg":
            try: os.remove(os.path.join(dl_dir, f))
            except: pass

    metadata = {
        'type': 'playlist', 'title': title, 'folderpath': dl_dir, 
        'tracks': downloaded, 'cover': playlist_cover_path if os.path.exists(playlist_cover_path) else None, 
        # 'zip_path' dihapus agar diurus otomatis oleh uploader.py
        'poster_msg': poster_msg, 'provider': 'Gaana', 
        'track_count': total, 'totaltracks': str(total), 'quality': '320kbps'
    }
    await playlist_upload(metadata, user)
