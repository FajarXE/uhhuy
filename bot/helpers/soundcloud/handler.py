# [GANTI FILE: bot/helpers/soundcloud/handler.py]

import aiohttp
import aiofiles
import os
import traceback
import asyncio
import shutil

from pathvalidate import sanitize_filepath
from config import Config
from bot.logger import LOGGER

# Impor API dan manager
from .api import SoundcloudError
from .manager import soundcloud_manager

# Impor fungsi metadata yang baru kita buat
from .metadata import (
    process_track_metadata,
    process_playlist_or_album,
    custom_url_parse
)

# Impor utilitas bot yang sudah ada
from ..utils import *
from ..uploder import *
from ..metadata import set_metadata
from ..message import edit_message
from ..utils import fetch_zip_settings
from ...settings import bot_set
import bot.helpers.translations as lang

try:
    from bot.helpers.lyrics.manager import lyrics_manager
except ImportError:
    lyrics_manager = None


async def download_soundcloud_track(download_url: str, download_type: str, filepath: str, details: dict = None):
    """
    Pengunduh file Soundcloud terintegrasi dengan Aria2 & FFmpeg.
    """
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        # 1. Gunakan ARIA2 untuk file Original & Progressive
        if download_type == 'original' or download_type == 'progressive':
            LOGGER.debug(f"Soundcloud: Mengunduh via Aria2 dari {download_url}")
            from bot.helpers.utils import download_file
            
            err = await download_file(download_url, filepath, details=details)
            if err:
                LOGGER.error(f"Soundcloud Aria2 gagal: {err}")
                if os.path.exists(filepath): os.remove(filepath)
                return f"Aria2 gagal: {err}"
            return None 

        # 2. Gunakan FFMPEG untuk Stream HLS (.m3u8)
        elif download_type == 'hls':
            LOGGER.debug(f"Soundcloud: Menggunakan ffmpeg (HLS) untuk {download_url}")
            
            # Ubah UI sementara karena FFmpeg tidak punya radar live
            if details and 'msg' in details:
                try:
                    from bot.helpers.message import edit_message
                    await edit_message(details['msg'], f"⚙️ **Menggabungkan HLS Stream (FFmpeg)...**\n`{details.get('title', 'Unknown Track')}`", None, False)
                except: pass

            args = [
                'ffmpeg',
                '-y',               
                '-i', download_url,   
                '-c', 'copy',       
                '-bsf:a', 'aac_adtstoasc', 
                filepath            
            ]
            
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode()
                LOGGER.error(f"Soundcloud: ffmpeg gagal!\n{error_msg}")
                if os.path.exists(filepath):
                    os.remove(filepath)
                return f"ffmpeg gagal: {error_msg}"
            
            LOGGER.debug("Soundcloud: ffmpeg HLS berhasil digabungkan.")
            return None 

        else:
            return f"Tipe unduhan tidak dikenal: {download_type}"
            
    except Exception as e:
        return f"Gagal mengunduh file: {e}"


async def start_track(item_id: str, user: dict, pre_data: dict = None, upload=True, filepath=None, disable_link=False):
    """Memulai alur kerja untuk satu track Soundcloud."""
    
    track_meta = None
    try:
        if pre_data and pre_data.get('provider') == 'Soundcloud':
            LOGGER.debug(f"SC start_track: Menggunakan pre_data yang sudah diproses.")
            track_meta = pre_data
        else:
            LOGGER.debug(f"SC start_track: Memanggil process_track_metadata.")
            track_meta = await process_track_metadata(
                item_id, 
                user['r_id'], 
                user, 
                pre_data=pre_data 
            )

        if not filepath:
            filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album'] or track_meta['title']}"
            filepath = sanitize_filepath(filepath)
            
    except Exception as e:
        LOGGER.error(f"Soundcloud track {item_id} tidak tersedia: {e}", exc_info=True)
        raise SoundcloudError(f"Gagal memproses metadata track {item_id}: {e}")
            
    download_url = track_meta.get('download_url')
    download_type = track_meta.get('download_type')
    if not download_url or not download_type:
        LOGGER.error(f"Tidak ada URL/Tipe download ditemukan untuk track SC {item_id}")
        raise SoundcloudError(f"Tidak ada URL download ditemukan untuk track {item_id}")

    track_meta['folderpath'] = filepath
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)

    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    # --- [SUNTIKAN KABEL RADAR UI TELEGRAM] ---
    details = None
    if upload and 'bot_msg' in user:
        details = {
            'msg': user['bot_msg'],
            'title': track_meta.get('title', 'Unknown'),
            'type': track_meta.get('type', 'Track').capitalize()
        }
    # ------------------------------------

    err = await download_soundcloud_track(
        download_url, 
        download_type, 
        track_meta['filepath'],
        details=details # <-- Kabel Radar masuk ke fungsi download
    )
    if err:
        LOGGER.error(f"Soundcloud dl_track gagal untuk {item_id}: {err}")
        raise SoundcloudError(f"Gagal mengunduh track: {err}")

    try:
        await set_metadata(track_meta, user['user_id'])
    except FileNotFoundError:
        LOGGER.error(f"[Errno 2] File not found setelah download SC: {filepath}")
        raise SoundcloudError(f"File tidak ditemukan setelah diunduh (path: {filepath})")
    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata SC: {filepath} -> {e}")
        try: os.remove(filepath)
        except: pass
        raise SoundcloudError(f"Gagal menulis metadata: {e}")

    if upload:
        await track_upload(track_meta, user, disable_link)

    return True


async def start_album_or_playlist(item_id: str, user: dict, pre_data: dict, media_type: str, upload=True):
    """Memulai alur kerja untuk album atau playlist Soundcloud."""
    try:
        multi_meta = await process_playlist_or_album(
            item_id, 
            user['r_id'], 
            user, 
            pre_data, 
            media_type
        )
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata {media_type} SC: {e}")

    folder_name = multi_meta['albumartist'] if media_type == 'album' else multi_meta['title']
    item_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{multi_meta['provider']}/{folder_name}"
    
    item_folder = sanitize_filepath(item_folder)
    os.makedirs(item_folder, exist_ok=True) # Pastikan folder dibuat
    multi_meta['folderpath'] = item_folder

    # --- TAMBAHAN BARU: Salin Cover ke Folder Album ---
    # Ini penting agar file cover masuk ke dalam ZIP
    if multi_meta.get('cover') and os.path.exists(multi_meta['cover']):
        try:
            # Ambil ekstensi file asli (jpg/png)
            ext = os.path.splitext(multi_meta['cover'])[1] or ".jpg"
            # Nama tujuan 'cover.jpg' agar dikenali pemutar musik
            dest_cover = os.path.join(item_folder, f"cover{ext}")
            
            LOGGER.debug(f"Soundcloud: Menyalin cover ke {dest_cover}")
            shutil.copy2(multi_meta['cover'], dest_cover)
        except Exception as e:
            LOGGER.warning(f"Soundcloud: Gagal menyalin file cover ke folder album: {e}")
    # --- AKHIR TAMBAHAN ---

    if upload:
        multi_meta['poster_msg'] = await post_art_poster(user, multi_meta)

    tasks = []
    for track_meta in multi_meta['tracks']:
        tasks.append(start_track(
            track_meta['itemid'], 
            user, 
            track_meta, 
            False, 
            item_folder
        ))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': multi_meta['title'],
        'type': multi_meta['type']
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details)
    
    successful_tracks = [multi_meta['tracks'][i] for i, result in enumerate(task_results) if result]
    multi_meta['tracks'] = successful_tracks
    multi_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        raise Exception(f"Tidak ada lagu SC yang berhasil diunduh untuk {multi_meta['title']}.")

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

    is_zip = (media_type == 'album' and album_zip) or (media_type == 'playlist' and playlist_zip)

    if is_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {multi_meta['totaltracks']} lagu menjadi .zip...")
        multi_meta['zip_path'] = await zip_handler(multi_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        if media_type == 'album':
            await album_upload(multi_meta, user)
        else:
            await playlist_upload(multi_meta, user)


async def start_soundcloud(link: str, user: dict):
    """Handler utama untuk link Soundcloud."""
    
    client = soundcloud_manager.get_client()
    if not client:
        raise SoundcloudError("Modul Soundcloud tidak diinisialisasi (Token hilang atau salah).")
        
    user['soundcloud_api'] = client
    
    if "on.soundcloud.com" in link:
        LOGGER.debug(f"Soundcloud: Link pendek terdeteksi: {link}. Mengambil URL asli...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.head(link, allow_redirects=False, timeout=10) as r:
                    if r.status in (301, 302, 307, 308) and 'Location' in r.headers:
                        original_link = r.headers['Location']
                        if original_link.startswith('/'):
                            original_link = "https://soundcloud.com" + original_link
                            
                        LOGGER.debug(f"Soundcloud: URL asli ditemukan: {original_link}")
                        link = original_link 
                    else:
                        raise SoundcloudError(f"Gagal me-resolve link pendek (status: {r.status})")
        except Exception as e:
            LOGGER.error(f"Gagal un-shorten link Soundcloud: {e}")
            raise SoundcloudError(f"Gagal me-resolve link pendek: {e}")
    
    elif "m.soundcloud.com" in link:
        LOGGER.debug(f"Soundcloud: Link mobile terdeteksi: {link}. Normalisasi...")
        link = link.replace("m.soundcloud.com", "soundcloud.com")
        LOGGER.debug(f"Soundcloud: URL dinormalisasi: {link}")

    try:
        media_type, item_id, extra = await custom_url_parse(link, client)

        if media_type == 'artist':
            raise NotImplementedError("Unduhan Artis Soundcloud (semua track) belum didukung.")
        
        elif media_type == 'track':
            await start_track(item_id, user, extra.get('pre_data'))
        
        elif media_type == 'album' or media_type == 'playlist':
            await start_album_or_playlist(item_id, user, extra.get('pre_data'), media_type)
        
    except Exception as e:
        LOGGER.error(f"Error fatal di Soundcloud handler: {e}\n{traceback.format_exc()}")
        raise e
