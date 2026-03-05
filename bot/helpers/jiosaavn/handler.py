# [GANTI SELURUH FILE: bot/helpers/jiosaavn/handler.py]

import os
import re
import shutil
import asyncio
import aiofiles
import aiohttp
from bot.logger import LOGGER
from bot.helpers.message import edit_message, send_message
from .manager import jiosaavn_manager
from .metadata import set_jiosaavn_metadata
from bot.helpers.uploder import track_upload, album_upload, playlist_upload 
from bot import Config
from bot.helpers.utils import fetch_zip_settings, download_file, run_concurrent_tasks
import yt_dlp

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

URL_REGEX = re.compile(r"jiosaavn\.com/(song|album|featured|playlist)/.+?/(.+)")

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
async def fetch_image(session, img_url, dest_path):
    if not img_url: return False
    img_1200 = img_url.replace("150x150", "1200x1200").replace("50x50", "1200x1200")
    img_500 = img_url.replace("150x150", "500x500").replace("50x50", "500x500")
    
    for url in [img_1200, img_500, img_url]:
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    async with aiofiles.open(dest_path, mode='wb') as f:
                        await f.write(await resp.read())
                    return True
        except: pass
    return False

async def start_jiosaavn(link: str, user: dict):
    msg = user['bot_msg']
    session = jiosaavn_manager.session
    api = jiosaavn_manager.api

    match = URL_REGEX.search(link)
    if not match: return

    kind, token_id = match.groups()
    if kind == 'song':
        await process_single_track(token_id, user, session, api)
    elif kind == 'album':
        await process_album(token_id, user, session, api)
    elif kind in ['featured', 'playlist']:
        await process_playlist(token_id, user, session, api)

# --- WORKER: FULL ARIA2 + HYBRID FALLBACK ---
async def _process_track_worker(track_data, i, total, dl_dir, user, session, api, is_batch=True):
    title = track_data.get("song", f"Track {i}")
    enc_url = track_data.get("encrypted_media_url")
    base_img = track_data.get("image", "")
    
    track_num = track_data.get('track_number')
    safe_title = sanitize_filename(title)
    filename = f"{int(track_num):02d} - {safe_title}.m4a" if track_num else f"{safe_title}.m4a"
    file_path = os.path.join(dl_dir, filename)

    # 1. Unduh Cover Lagu (Jika ada)
    cover_path = os.path.join(dl_dir, f"{safe_title}.jpg")
    if not os.path.exists(cover_path):
        await fetch_image(session, base_img, cover_path)

    # 2. Ambil URL Audio Asli
    dl_url = await api.get_auth_url(session, enc_url)
    urls_to_try = []
    if dl_url:
        urls_to_try.append(dl_url) 
        urls_to_try.append(dl_url.replace("_320.mp4", "_160.mp4"))

    # 3. Mesin Aria2 + Penyamaran Headers
    headers_dict = {'User-Agent': api.headers['User-Agent']}
    details_aria = {'msg': None, 'headers': headers_dict} if is_batch else {
        'msg': user['bot_msg'], 'title': title, 'type': 'Track', 'headers': headers_dict
    }

    downloaded = False
    for url in urls_to_try:
        err = await download_file(url, file_path, retries=1, details=details_aria)
        if not err:
            downloaded = True
            break
        else:
            LOGGER.warning(f"JioSaavn: Aria2 ditolak untuk {title}. Fallback ke AIOHTTP Turbo...")
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

    # 4. Fallback Terakhir (YT-DLP)
    if not downloaded:
        if os.path.exists(file_path): os.remove(file_path)
        target = track_data.get('perma_url')
        if target:
            try:
                def run_ytdlp():
                    ydl_opts = {'format': 'bestaudio/best', 'outtmpl': file_path, 'quiet': True}
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([target])
                await asyncio.to_thread(run_ytdlp)
                if os.path.exists(file_path) and os.path.getsize(file_path) > 10000:
                    downloaded = True
            except: pass

    if not downloaded: 
        LOGGER.error(f"Gagal mengunduh track {title}")
        return None

    # 5. Pasang Metadata
    lyrics = await api.get_lyrics(session, track_data.get("id")) if track_data.get("has_lyrics") == "true" else None
    
    # --- [FIX] PANGGIL FUNGSI ASYNC SECARA LANGSUNG ---
    # Jangan gunakan asyncio.to_thread agar fungsi benar-benar dieksekusi dan mengembalikan angka!
    duration = await set_jiosaavn_metadata(
        file_path, 
        track_data, 
        cover_path if os.path.exists(cover_path) else None, 
        lyrics
    )
    # ---------------------------------------------------

    return {
        'filepath': file_path, 'title': title,
        'artist': track_data.get("primary_artists"), 'album': track_data.get("album"),
        'cover': cover_path if os.path.exists(cover_path) else None, 
        'duration': duration, 'quality': '320kbps'
    }

async def process_single_track(token_id, user, session, api):
    msg = user['bot_msg']
    await edit_message(msg, "⚙️ Mengambil info lagu...")
    try:
        track_data = await api.get_song_details(session, token_id)
        if not track_data: raise Exception("Metadata tidak ditemukan.")
        
        track_data['track_number'] = 1
        track_data['total_tracks'] = 1
        dl_dir = ensure_download_dir(user)
        
        res = await _process_track_worker(track_data, 1, 1, dl_dir, user, session, api, is_batch=False)
        if not res: raise Exception("Gagal mengunduh lagu.")
        
        metadata = res.copy()
        metadata.update({'provider': 'JioSaavn', 'type': 'track'})
        
        await edit_message(msg, "🚀 Memproses Upload...")
        await track_upload(metadata, user)
    except Exception as e:
        await edit_message(msg, f"❌ Error: {e}")

async def process_album(token_id, user, session, api):
    msg = user['bot_msg']
    await edit_message(msg, "⚙️ Mengambil data Album...")
    try:
        album_data = await api.get_album_details(session, token_id)
        tracks = album_data.get("list") or album_data.get("songs") or []
        if not tracks: raise Exception("Album kosong.")
        
        title = album_data.get("title", "Unknown Album")
        dl_dir = ensure_download_dir(user, subdir=title)
        total = len(tracks)
        release_date = album_data.get("release_date") or album_data.get("year", "Unknown")
        
        # Cek Explicit Content
        is_explicit = "False"
        for t in tracks:
            if str(t.get("explicit_content")) == "1":
                is_explicit = "True"
                break

        # --- [FIX UI] UNDUH COVER UTAMA & KIRIM POSTER DI AWAL ---
        final_cover_path = os.path.join(dl_dir, "cover.jpg")
        await fetch_image(session, album_data.get("image"), final_cover_path)
        
        _, is_album_zip, _, is_art_poster = fetch_zip_settings(user)
        poster_msg = None
        if is_art_poster and os.path.exists(final_cover_path):
            try:
                caption = (
                    f"**ᴛɪᴛʟᴇ :** {title}\n**ᴀʀᴛɪsᴛ :** {album_data.get('primary_artists')}\n"
                    f"**ʀᴇʟᴇᴀsᴇ ᴅᴀᴛᴇ :** {release_date}\n**ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs :** {total}\n"
                    f"**ᴛᴏᴛᴀʟ ᴠᴏʟᴜᴍᴇs :** 1\n**ǫᴜᴀʟɪᴛʏ :** 320kbps\n"
                    f"**ᴘʀᴏᴠɪᴅᴇʀ :** JioSaavn\n**ᴇxᴘʟɪᴄɪᴛ :** {is_explicit}"
                )
                poster_msg = await send_message(user, final_cover_path, 'pic', caption=caption)
            except Exception as e: LOGGER.error(f"Gagal poster: {e}")
        # ---------------------------------------------------------

        # --- MESIN KONKURENSI ARIA2 ---
        async def wrap_track(track_raw, i):
            t_token = track_raw.get('perma_url', '').split('/')[-1]
            full_track = await api.get_song_details(session, t_token) if t_token else track_raw
            if not full_track: full_track = track_raw
            full_track['track_number'] = i + 1
            full_track['total_tracks'] = total
            return await _process_track_worker(full_track, i+1, total, dl_dir, user, session, api, is_batch=True)

        tasks = [wrap_track(t, i) for i, t in enumerate(tracks)]
        update_details = {'msg': msg, 'title': title, 'type': 'Album', 'action': 'Download'}
        
        results = await run_concurrent_tasks(worker_tasks, update_details, limit=8)
        downloaded_tracks = [r for r in results if r]

        if not downloaded_tracks: raise Exception("❌ Gagal mengunduh semua lagu.")

        await edit_message(msg, "📦 Memproses Album...")
        
        zip_path = None
        if is_album_zip:
             await edit_message(msg, "🗜️ Membersihkan & Membuat ZIP...")
             for f in os.listdir(dl_dir):
                 if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and f != "cover.jpg":
                     try: os.remove(os.path.join(dl_dir, f))
                     except: pass

             parent_dir = os.path.dirname(dl_dir)
             zip_name = sanitize_filename(title)
             base_name = os.path.join(parent_dir, zip_name)
             zip_path = await asyncio.to_thread(shutil.make_archive, base_name, 'zip', dl_dir)

        metadata = {
            'type': 'album', 
            'title': title, 
            'artist': album_data.get("primary_artists"), 
            'folderpath': dl_dir, 
            'tracks': downloaded_tracks, 
            'cover': final_cover_path if os.path.exists(final_cover_path) else None,
            'zip_path': zip_path, 
            'poster_msg': poster_msg, 
            'provider': 'JioSaavn', 
            'release_date': release_date, 
            'totaltracks': str(total),     # <-- Memperbaiki total tracks kosong
            'totalvolumes': '1',           # <-- Memperbaiki total volumes kosong
            'explicit': is_explicit,       # <-- Memperbaiki explicit kosong
            'quality': '320kbps'
        }
        await edit_message(msg, "🚀 Mengunggah Album...")
        await album_upload(metadata, user)
        
    except Exception as e:
        LOGGER.error(f"JioSaavn Album Error: {e}")
        await edit_message(msg, f"❌ Error: {e}")

async def process_playlist(token_id, user, session, api):
    msg = user['bot_msg']
    await edit_message(msg, "⚙️ Mengambil data Playlist...")
    try:
        pl_data = await api.get_playlist_details(session, token_id)
        tracks = pl_data.get("list") or pl_data.get("songs") or []
        if not tracks: raise Exception("Playlist kosong.")
        
        title = pl_data.get("listname") or pl_data.get("title") or "Unknown Playlist"
        dl_dir = ensure_download_dir(user, subdir=title)
        total = len(tracks)

        # --- [FIX UI] UNDUH COVER & KIRIM POSTER DI AWAL ---
        playlist_cover_path = os.path.join(dl_dir, "playlist_cover.jpg")
        await fetch_image(session, pl_data.get("image", ""), playlist_cover_path)
        
        is_pl_zip, _, _, is_art_poster = fetch_zip_settings(user)
        poster_msg = None
        if is_art_poster and os.path.exists(playlist_cover_path):
            try:
                caption = f"**ᴛɪᴛʟᴇ :** {title}\n**ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs :** {total}\n**ǫᴜᴀʟɪᴛʏ :** 320kbps\n**ᴘʀᴏᴠɪᴅᴇʀ :** JioSaavn"
                poster_msg = await send_message(user, playlist_cover_path, 'pic', caption=caption)
            except: pass
        # ---------------------------------------------------
        
        # --- MESIN KONKURENSI ARIA2 ---
        async def wrap_track(track_raw, i):
            t_token = track_raw.get('perma_url', '').split('/')[-1]
            full_track = await api.get_song_details(session, t_token) if t_token else track_raw
            if not full_track: full_track = track_raw
            full_track['track_number'] = i + 1
            full_track['total_tracks'] = total
            return await _process_track_worker(full_track, i+1, total, dl_dir, user, session, api, is_batch=True)

        tasks = [wrap_track(t, i) for i, t in enumerate(tracks)]
        update_details = {'msg': msg, 'title': title, 'type': 'Playlist', 'action': 'Download'}
        
        results = await run_concurrent_tasks(worker_tasks, update_details, limit=8)
        downloaded_tracks = [r for r in results if r]

        if not downloaded_tracks: raise Exception("❌ Gagal mengunduh playlist.")

        await edit_message(msg, "📦 Memproses Playlist...")
        
        zip_path = None
        if is_pl_zip:
             await edit_message(msg, "🗜️ Membersihkan & Membuat ZIP...")
             for f in os.listdir(dl_dir):
                 if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and f != "playlist_cover.jpg":
                     try: os.remove(os.path.join(dl_dir, f))
                     except: pass

             parent_dir = os.path.dirname(dl_dir)
             zip_name = sanitize_filename(title)
             base_name = os.path.join(parent_dir, zip_name)
             zip_path = await asyncio.to_thread(shutil.make_archive, base_name, 'zip', dl_dir)

        metadata = {
            'type': 'playlist', 
            'title': title, 
            'folderpath': dl_dir, 
            'tracks': downloaded_tracks, 
            'cover': playlist_cover_path if os.path.exists(playlist_cover_path) else None, 
            'zip_path': zip_path, 
            'poster_msg': poster_msg, 
            'provider': 'JioSaavn', 
            'totaltracks': str(total),     # <-- Memperbaiki total tracks kosong
            'quality': '320kbps'
        }
        await edit_message(msg, "🚀 Mengunggah Playlist...")
        await playlist_upload(metadata, user)
        
    except Exception as e:
        LOGGER.error(f"JioSaavn Playlist Error: {e}")
        await edit_message(msg, f"❌ Error: {e}")
