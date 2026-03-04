# [GANTI FILE: bot/helpers/bugs/handler.py]

import aiohttp
import aiofiles
import os
import shutil
import traceback
import asyncio

from pathvalidate import sanitize_filepath
from config import Config

# Impor metadata dan manager Bugs
from .metadata import (
    process_track_metadata, 
    process_album_metadata,
    custom_url_parse
)
from .manager import BugsError, bugs_manager

# Impor helper standar
from ..uploder import *
from ..metadata import set_metadata
from ..message import edit_message
from ..utils import fetch_zip_settings, run_concurrent_tasks, format_string, zip_handler
from ...settings import bot_set 
import bot.helpers.translations as lang
from bot.logger import LOGGER

# --- TAMBAHAN BARU: IMPOR MANAGER LIRIK ---
try:
    from bot.helpers.lyrics.manager import lyrics_manager
except ImportError:
    lyrics_manager = None
# --- BATAS TAMBAHAN ---


async def start_bugs(url: str, user: dict):
    """Handler utama untuk link Bugs."""
    try:
        media_type, item_id, extra_kwargs = custom_url_parse(url)
        
        if media_type == 'track':
            success = await start_track(item_id, user, None)
            if not success:
                raise Exception("Gagal mengunduh atau memproses track Bugs.")
        
        elif media_type == 'album':
            await start_album(item_id, user)
            
        else:
            raise NotImplementedError(f"Tipe media Bugs '{media_type}' belum didukung.")
        
    except Exception as e:
        LOGGER.error(f"Error fatal di Bugs handler: {e}\n{traceback.format_exc()}")
        # Melempar error agar download.py tahu tugasnya gagal
        raise e 


async def start_track(item_id: str, user: dict, track_meta: dict | None, upload=True, \
    filepath=None, disable_link=False):

    client = user['bugs_api']

    if not track_meta:
        try:
            track_meta = await process_track_metadata(item_id, user['r_id'], user)
        except Exception as e:
            LOGGER.warning(f"Bugs track {item_id} tidak tersedia: {e}")
            return False
            
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)

    download_id = track_meta.get('download_id')
    download_quality = track_meta.get('download_quality_key')
    if not download_id or not download_quality:
        LOGGER.error(f"Metadata tidak lengkap untuk unduhan Bugs track {item_id}")
        return False

    track_meta['folderpath'] = filepath
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)

    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    # --- LOGIKA UNDUH BUGS ---
    try:
        # 1. Dapatkan URL Stream (Async)
        stream_data = await asyncio.to_thread(
            client.get_stream, 
            int(download_id), 
            download_quality
        )

        if stream_data.get('state') != 'OK' or not stream_data.get('url'):
            raise BugsError(f"Gagal mendapatkan stream dari API Bugs. State: {stream_data.get('state')}")

        download_url = stream_data.get('url')
            
        # Pastikan direktori ada
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        # 2. Siapkan Kabel Radar UI Telegram (Hanya aktif untuk Single Track)
        details = None
        if upload and 'bot_msg' in user:
            details = {
                'msg': user['bot_msg'],
                'title': track_meta.get('title', 'Unknown'),
                'type': track_meta.get('type', 'Track').capitalize()
            }

        # 3. Lempar tugas unduhan ke mesin Aria2 yang super cepat!
        from bot.helpers.utils import download_file
        err = await download_file(download_url, track_meta['filepath'], details=details)
        
        if err:
            LOGGER.error(f"Aria2 gagal mengunduh Bugs track {item_id}: {err}")
            return False

    except Exception as e:
        LOGGER.error(f"Bugs dl_track gagal untuk {item_id}: {e}")
        return False
    # --- BATAS LOGIKA UNDUH ---

    try:
        # --- MODIFIKASI PENTING: Kirim user_id ke set_metadata agar lirik diambil ---
        await set_metadata(track_meta, user['user_id'])
        # --- BATAS MODIFIKASI ---
    except FileNotFoundError:
        LOGGER.error(f"[Errno 2] File not found setelah download Bugs: {filepath}")
        return False
    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata Bugs: {filepath} -> {e}")
        try:
            os.remove(filepath)
        except:
            pass
        return False

    if upload:
        await track_upload(track_meta, user, disable_link)

    return True

async def start_album(album_id: str, user: dict, upload=True):
    """
    Handler untuk unduhan album (didasarkan pada handler.py provider lain)
    """
    try:
        album_meta = await process_album_metadata(album_id, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata album Bugs: {e}")

    album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder

    if upload:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    # --- TAMBAHAN: Salin Cover ke Folder Album Sebelum Zip ---
    try:
        # Pastikan folder tujuan ada
        os.makedirs(album_folder, exist_ok=True)
        
        # Cek apakah ada cover di metadata (ini path ke file temp)
        if album_meta.get('cover') and os.path.exists(album_meta['cover']):
            # Salin ke folder album dengan nama cover.jpg
            cover_dest = os.path.join(album_folder, "cover.jpg")
            shutil.copy(album_meta['cover'], cover_dest)
            LOGGER.info(f"Berhasil menyalin cover ke: {cover_dest}")
    except Exception as e:
        LOGGER.warning(f"Gagal menyalin cover.jpg ke folder album: {e}")
    # --- AKHIR TAMBAHAN ---

    tasks = []
    for track in album_meta['tracks']:
        # Kirim track_meta (pre_data) ke start_track agar tidak perlu fetch ulang
        tasks.append(start_track(track['itemid'], user, track, False, album_folder))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': album_meta['title'],
        'type': album_meta['type']
    }
    
    # Server Bugs memutus koneksi jika kita mencoba > 10 koneksi sekaligus
    task_results = await run_concurrent_tasks(tasks, update_details, limit=8)
    
    successful_tracks = [album_meta['tracks'][i] for i, result in enumerate(task_results) if result]
    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        raise Exception(f"Tidak ada lagu Bugs yang berhasil diunduh untuk album {album_meta['title']}.")

    # --- PERBAIKAN: Unpack 4 nilai (urutan baru) ---
    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    # --- AKHIR PERBAIKAN ---

    if album_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {album_meta['totaltracks']} lagu menjadi .zip...")
        # --- PERBAIKAN: Gunakan 'zip_path' agar konsisten ---
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])
        # --- AKHIR PERBAIKAN ---

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)
