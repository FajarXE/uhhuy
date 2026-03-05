# [GANTI SELURUH FILE: bot/helpers/bandcamp/handler.py]

import os
import re
import shutil
import asyncio
import aiohttp
import aiofiles
from bot.logger import LOGGER
from bot.helpers.message import edit_message, send_message
from .manager import bandcamp_manager
from .metadata import set_bandcamp_metadata
from bot.helpers.uploder import track_upload, album_upload, post_art_poster
from bot import Config
from bot.helpers.utils import fetch_zip_settings, download_file, run_concurrent_tasks

BANDCAMP_REGEX = re.compile(r'https?://[^/]+\.bandcamp\.com/(track|album)/[^/?#]+')

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

def ensure_download_dir(user, subdir=None):
    base_dir = Config.DOWNLOAD_BASE_DIR
    uid = user.get('user_id', 'temp')
    user_dir = os.path.join(base_dir, str(uid))
    if subdir:
        user_dir = os.path.join(user_dir, sanitize_filename(subdir))
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    return user_dir

async def start_bandcamp(link: str, user: dict):
    msg = user['bot_msg']
    session = bandcamp_manager.session
    api = bandcamp_manager.api

    if "bandcamp.com" not in link:
        await edit_message(msg, "Link Bandcamp tidak valid.")
        return

    await edit_message(msg, "⚙️ Mengambil data dari Bandcamp...")
    
    data = await api.get_track_or_album(session, link)
    if not data:
        await edit_message(msg, "❌ Gagal mengambil metadata (Mungkin Geo-blocked atau URL salah).")
        return

    artist = data['artist']
    album_title = data['album_title']
    tracks = data['tracks']
    is_album = data['is_album']
    release_date = data['release_date'] 
    genre = data['genre']
    label = data['label']
    is_explicit = data['explicit'] 
    
    json_raw = data.get('raw', {})
    
    copyright_text = json_raw.get('copyright') or f"{release_date[:4] if release_date else ''} {label or artist}".strip()
    
    credits = json_raw.get('credits', "")
    composer = artist
    if credits and len(credits) < 50:
        composer = credits.replace("Written by", "").strip()

    dl_dir = ensure_download_dir(user, subdir=album_title)
    
    cover_path = os.path.join(dl_dir, "cover.jpg")
    cover_url = f"https://f4.bcbits.com/img/a{data['art_id']}_10.jpg" if data['art_id'] else None
    
    if cover_url:
        try:
            # Gunakan Aria2 untuk menarik Cover agar cepat!
            await download_file(cover_url, cover_path)
        except: 
            cover_path = None

    total_tracks = len(tracks)

    # --- PERSIAPAN BUNGKUSAN METADATA UNTUK POSTER ---
    album_meta = {
        'type': 'album' if is_album else 'track',
        'title': album_title,
        'artist': artist,
        'albumartist': artist,
        'folderpath': dl_dir,
        'cover': cover_path,
        'provider': 'Bandcamp',
        'quality': '128kbps',
        'release_date': release_date,
        'date': release_date[:4] if release_date else '',
        'totaltracks': str(total_tracks),
        'totalvolumes': '1',
        'explicit': str(is_explicit),
        'tracks': []
    }

    # --- [FIX UI] KIRIM POSTER DI AWAL SEBELUM DOWNLOAD MULTIPLE ---
    try:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)
    except Exception as e:
        LOGGER.error(f"Gagal mengirim poster Bandcamp: {e}")
    # ---------------------------------------------------------------

    # --- FUNGSI WORKER CONCURRENT ---
    async def _process_track(track, i):
        file_info = track.get('file')
        if not file_info or 'mp3-128' not in file_info:
            LOGGER.warning(f"Track {track.get('title')} tidak memiliki stream gratis.")
            return None

        track_url = file_info['mp3-128']
        track_title = track.get('title', f"Track {i+1}")
        
        raw_track_num = track.get('track_num')
        track_num = int(raw_track_num) if raw_track_num is not None else i + 1
        
        filename = f"{track_num:02d} - {sanitize_filename(track_title)}.mp3"
        file_path = os.path.join(dl_dir, filename)
        
        # --- [FIX 1] MENCEGAH CRASH ARIA2 'msg' ---
        headers_dict = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'}
        details_aria = None
        
        if not is_album:
            details_aria = {
                'msg': msg,
                'title': track_title,
                'type': 'Track',
                'headers': headers_dict
            }

        err = await download_file(track_url, file_path, retries=1, details=details_aria)
        
        if err:
            LOGGER.warning(f"Bandcamp: Aria2 ditolak. Mengaktifkan AIOHTTP Turbo Fallback untuk {track_title}")
            async with aiohttp.ClientSession(headers=headers_dict) as fallback_session:
                async with fallback_session.get(track_url) as r:
                    if r.status == 200:
                        async with aiofiles.open(file_path, 'wb') as f:
                            async for chunk in r.content.iter_chunked(256 * 1024):
                                if chunk: await f.write(chunk)
        # ---------------------------------------------
        
        lyrics_text = track.get('lyrics') or None
        
        meta_payload = {
            'filepath': file_path,
            'title': track_title,
            'artist': artist,
            'album': album_title,
            'track_num': track_num,
            'total_tracks': total_tracks,
            'cover_path': cover_path,
            'date': release_date, 
            'genre': genre,
            'label': label,
            'album_artist': artist,
            'copyright': copyright_text,
            'composer': composer,
            'lyrics': lyrics_text,
            'isrc': None 
        }
        
        # --- [FIX 2] PANGGIL FUNGSI ASYNC SECARA LANGSUNG ---
        await set_bandcamp_metadata(file_path, meta_payload)
        # ----------------------------------------------------
        
        duration = int(float(track.get('duration') or 0))

        return {
            'filepath': file_path,
            'title': track_title,
            'artist': artist,
            'album': album_title,
            'cover': cover_path,
            'duration': duration,
            'quality': '128kbps',
            'provider': 'Bandcamp',
            'type': 'track'
        }
    # --------------------------------

    # --- EKSEKUSI ---
    if is_album:
        tasks = [_process_track(t, i) for i, t in enumerate(tracks)]
        update_details = {
            'msg': msg, 
            'title': album_title, 
            'type': 'Album',
            'action': 'Download'
        }
        
        # Eksekusi 4 Lagu Sekaligus secara paralel!
        results = await run_concurrent_tasks(tasks, update_details, limit=4)
        downloaded_tracks = [r for r in results if r]
    else:
        # Mode Single Track
        res = await _process_track(tracks[0], 0)
        downloaded_tracks = [res] if res else []

    if not downloaded_tracks:
        raise Exception("❌ Gagal mengunduh track apapun.")

    # --- UPLOAD ---
    if len(downloaded_tracks) == 1 and not is_album:
        track_meta = downloaded_tracks[0]
        await edit_message(msg, "🚀 Memproses Upload Track...")
        await track_upload(track_meta, user)
    else:
        await edit_message(msg, "📦 Memproses Album...")
        album_meta['tracks'] = downloaded_tracks
        
        _, is_album_zip, _, _ = await asyncio.to_thread(fetch_zip_settings, user)
        
        if is_album_zip:
            await edit_message(msg, "🗜️ Membuat ZIP...")
            try:
                from bot.helpers.utils import zip_folder
                album_meta['zip_path'] = await asyncio.to_thread(zip_folder, dl_dir)
            except ImportError:
                parent_dir = os.path.dirname(dl_dir)
                zip_name = sanitize_filename(album_title)
                base_name = os.path.join(parent_dir, zip_name)
                album_meta['zip_path'] = await asyncio.to_thread(shutil.make_archive, base_name, 'zip', dl_dir)

        await edit_message(msg, "🚀 Mengunggah Album...")
        await album_upload(album_meta, user)
