# [GANTI SELURUH FILE: bot/helpers/highresaudio/handler.py]

import aiohttp
import aiofiles
import os
import shutil
import traceback
import asyncio
import math 
import requests 
import random 
import time

from pathvalidate import sanitize_filepath
from config import Config

from .metadata import (
    process_album_metadata,
    custom_url_parse
)
from .manager import HighResAudioError, highresaudio_manager

from ..uploder import *
from ..metadata import set_metadata
from ..message import edit_message
from ..utils import fetch_zip_settings, run_concurrent_tasks, format_string, zip_handler, download_file
from ...settings import bot_set 
import bot.helpers.translations as lang
from bot.logger import LOGGER


async def start_highresaudio(url: str, user: dict):
    # --- RE-LOGIN OTOMATIS ---
    try:
        user_id = user.get('user_id')
        client = highresaudio_manager.get_client(user_id)
        
        if client:
            if hasattr(client, 're_login'):
                await asyncio.to_thread(client.re_login)
            else:
                LOGGER.warning(f"HighResAudio: Client {user_id} tidak memiliki method 're_login'.")
    except Exception as e:
        LOGGER.error(f"HighResAudio: Gagal menyegarkan sesi (Re-login): {e}")

    try:
        media_type, item_id, extra_kwargs = custom_url_parse(url)
        if media_type == 'album':
            await start_album(url, user)
        else:
            raise NotImplementedError(f"Tipe media HighResAudio '{media_type}' belum didukung.")
    except Exception as e:
        LOGGER.error(f"Error fatal di HighResAudio handler: {e}\n{traceback.format_exc()}")
        raise e 

async def start_track(item_id: str, user: dict, track_meta: dict | None, upload=True, filepath=None, disable_link=False):
    
    client = highresaudio_manager.get_client(user.get('user_id'))
    
    if not client:
         raise HighResAudioError("Tidak ada klien HighResAudio yang tersedia (Silakan login akun sendiri atau hubungi Admin).")

    if not track_meta:
        raise HighResAudioError("start_track dipanggil tanpa track_meta.")
            
    if not filepath:
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)

    download_url = track_meta.get('download_url')
    album_id_referer = track_meta.get('album_id_referer') 
    
    if not download_url or not album_id_referer:
        LOGGER.error(f"Metadata tidak lengkap untuk unduhan HRA track.")
        return False

    track_meta['folderpath'] = filepath
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)
    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    # --- SUNTIKAN KABEL RADAR UI TELEGRAM ---
    details = None
    if upload and 'bot_msg' in user:
        details = {
            'msg': user['bot_msg'],
            'title': track_meta.get('title', 'Unknown'),
            'type': track_meta.get('type', 'Track').capitalize()
        }

    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # --- MESIN PENGUNDUH HYBRID (ARIA2 -> AIOHTTP TURBO) ---
        cookie_str = "; ".join([f"{k}={v}" for k, v in client.s.cookies.items()])
        headers_dict = {
            "Referer": f"https://stream-app.highresaudio.com/album/{album_id_referer}",
            "Cookie": cookie_str
        }
        
        # [PERBAIKAN FATAL] Hanya tambahkan headers jika details benar-benar ada (Mode Single Track).
        # Jika Mode Album (details = None), biarkan tetap None agar aria2_helper tidak crash (KeyError: 'msg').
        if details is not None:
            details['headers'] = headers_dict

        # Langkah 1: Coba kekuatan penuh Aria2 (retries=1 agar cepat beralih jika ditolak server)
        err = await download_file(download_url, track_meta['filepath'], retries=1, details=details)
        
        if err:
            LOGGER.warning(f"HighResAudio: Aria2 gagal/ditolak server. Mengaktifkan AIOHTTP Turbo Fallback...")
            
            # Langkah 2: AIOHTTP Turbo Fallback (Menjamin Cookie Tembus 100%)
            async with aiohttp.ClientSession(headers=headers_dict) as session:
                async with session.get(download_url) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get('content-length', 0))
                    downloaded = 0
                    start_time = time.time()
                    last_update = start_time
                    
                    async with aiofiles.open(track_meta['filepath'], 'wb') as f:
                        async for chunk in r.content.iter_chunked(256 * 1024):
                            if chunk:
                                await f.write(chunk)
                                downloaded += len(chunk)
                                
                                # Update Radar UI (Hanya jika Single Track)
                                if details and 'msg' in details:
                                    now = time.time()
                                    if now - last_update > 2.0 or downloaded == total_size:
                                        last_update = now
                                        from bot.helpers.utils import progress_message
                                        await progress_message(downloaded, total_size, details)
        # --------------------------------------------------------
        
    except Exception as e:
        LOGGER.error(f"HighResAudio dl_track gagal: {e}")
        return False

    try:
        await set_metadata(track_meta, user['user_id'])
    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata HRA: {filepath} -> {e}")
        try: os.remove(filepath)
        except: pass
        return False

    if upload:
        await track_upload(track_meta, user, disable_link)

    return True

def download_booklet(client, url, temp_location):
    try:
        r = client.get_booklet_stream(url) 
        r.raise_for_status()
        with open(temp_location, 'wb') as f:
            for chunk in r.iter_content(chunk_size=32 * 1024):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        if os.path.isfile(temp_location):
            os.remove(temp_location)
        LOGGER.error(f"HighResAudio: Gagal mengunduh booklet: {e}")
    

async def start_album(album_url: str, user: dict, upload=True):
    try:
        album_meta = await process_album_metadata(album_url, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata album HighResAudio: {e}")

    album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder 

    if upload:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    tasks = []
    for track in album_meta['tracks']:
        tasks.append(start_track(None, user, track, False, album_folder))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': album_meta['title'],
        'type': album_meta['type']
    }
    
    results = await run_concurrent_tasks(worker_tasks, update_details, limit=8)
    
    successful_tracks = [album_meta['tracks'][i] for i, result in enumerate(task_results) if result]
    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        raise Exception(f"Tidak ada lagu HighResAudio yang berhasil diunduh.")

    booklet_path = None
    if 'booklet_url' in album_meta:
        LOGGER.info("HighResAudio: Mengunduh booklet...")
        booklet_path = os.path.join(album_folder, "booklet.pdf")
        dl_client = highresaudio_manager.get_client(user.get('user_id'))
        if dl_client:
            await asyncio.to_thread(download_booklet, dl_client, album_meta['booklet_url'], booklet_path)
    
    if album_meta.get('cover') and os.path.exists(album_meta['cover']):
        try:
            cover_dest_path = os.path.join(album_folder, "cover.jpg")
            if not os.path.exists(cover_dest_path):
                await asyncio.to_thread(shutil.copy, album_meta['cover'], cover_dest_path)
        except: pass

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

    if album_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {album_meta['totaltracks']} lagu menjadi .zip...")
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)

        if 'zip_path' not in album_meta and booklet_path and os.path.exists(booklet_path):
            try:
                await user['bot_msg'].reply_document(
                    document=booklet_path,
                    caption=f"**Booklet**\n{album_meta['title']} - {album_meta['artist']}",
                    quote=True
                )
            except Exception as e:
                LOGGER.error(f"HighResAudio: Gagal mengunggah booklet: {e}")
        
        await album_upload(album_meta, user)
