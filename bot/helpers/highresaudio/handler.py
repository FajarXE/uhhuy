# [GANTI TOTAL ISI FILE: bot/helpers/highresaudio/handler.py]

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
import yarl

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

# --- Import Manajer Proksi Sentral ---
from bot.helpers.proxy_manager import proxy_manager


async def start_highresaudio(url: str, user: dict):
    try:
        user_id = user.get('user_id')
        client = highresaudio_manager.get_client(user_id)
        if client and hasattr(client, 're_login'):
            await asyncio.to_thread(client.re_login)
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
    if not client: raise HighResAudioError("Klien HighResAudio tidak tersedia.")
    if not track_meta: raise HighResAudioError("start_track dipanggil tanpa track_meta.")
            
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
    
    safe_filename = sanitize_filepath(raw_filename)[:120].strip()
    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    details = None
    if upload and 'bot_msg' in user:
        details = {
            'msg': user['bot_msg'],
            'title': track_meta.get('title', 'Unknown'),
            'type': track_meta.get('type', 'Track').capitalize()
        }

    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        cookie_str = "; ".join([f"{k}={v}" for k, v in client.s.cookies.items()])
        headers_dict = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
            "Referer": f"https://stream-app.highresaudio.com/album/{album_id_referer}",
            "Cookie": cookie_str
        }
        
        if details is None: details = {}
        details['headers'] = headers_dict
        
        if client.proxy:
            details['proxy'] = client.proxy 

        # Langkah 1: Aria2
        err = await download_file(download_url, track_meta['filepath'], retries=1, details=details)
        
        if err:
            LOGGER.warning(f"HighResAudio: Aria2 gagal/ditolak server. Mengaktifkan AIOHTTP Turbo Fallback...")
            
            if os.path.exists(track_meta['filepath'] + '.aria2'):
                try: os.remove(track_meta['filepath'] + '.aria2')
                except: pass
                
            if os.path.exists(track_meta['filepath']):
                try: os.remove(track_meta['filepath'])
                except: pass
            
            # --- [PERBAIKAN 1] HAPUS HEADER RANGE YANG MEMBINGUNGKAN CDN ---
            if "Range" in headers_dict:
                del headers_dict["Range"]
            
            used_proxy = await proxy_manager.get_proxy(client.proxy)

            # --- [PERBAIKAN 2] SISTEM RETRY UNTUK AIOHTTP ---
            max_aio_retries = 3
            aio_success = False
            
            for attempt in range(max_aio_retries):
                # [FIX: PINDAHKAN KE DALAM LOOP] 
                # Konektor harus dibuat baru pada setiap iterasi karena 
                # aiohttp.ClientSession akan menutup konektor saat keluar dari blok 'async with'
                connector = proxy_manager.get_aiohttp_connector(used_proxy)
                
                try:
                    async with aiohttp.ClientSession(headers=headers_dict, connector=connector) as session:
                        get_kwargs = {}
                        if used_proxy and not used_proxy.startswith('socks'):
                            get_kwargs['proxy'] = used_proxy
                            
                        safe_url = yarl.URL(download_url, encoded=True)
                        
                        # Timeout dinaikkan agar tidak putus di tengah
                        timeout = aiohttp.ClientTimeout(total=3600, sock_read=60)
                        async with session.get(safe_url, timeout=timeout, **get_kwargs) as r:
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
                                        
                                        if details and 'msg' in details:
                                            now = time.time()
                                            if now - last_update > 2.0 or downloaded == total_size:
                                                last_update = now
                                                from bot.helpers.utils import progress_message
                                                await progress_message(downloaded, total_size, details)
                    aio_success = True
                    break # Berhasil, keluar dari loop
                    
                except aiohttp.ClientPayloadError as e:
                    LOGGER.error(f"HighResAudio AIOHTTP payload error (Coba {attempt+1}/{max_aio_retries}): {e}")
                    await asyncio.sleep(2)
                except Exception as e:
                    LOGGER.error(f"HighResAudio AIOHTTP gagal (Coba {attempt+1}/{max_aio_retries}): {e}")
                    await asyncio.sleep(2)

            if not aio_success:
                raise Exception("AIOHTTP Turbo Fallback gagal setelah percobaan maksimal (ContentLengthError).")
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

    safe_artist = album_meta['artist'][:60].strip()
    safe_title = album_meta['title'][:60].strip()
    
    album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{safe_artist}/{safe_title}"
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder 

    if user.get('booklet_only'):
        await edit_message(user['bot_msg'], f"🔍 Mencari booklet untuk album: `{album_meta['title']}`...")
        
        if album_meta.get('booklet_url'):
            booklet_path = None
            try:
                os.makedirs(album_folder, exist_ok=True)
                temp_path = os.path.join(album_folder, "Booklet.pdf")
                dl_client = highresaudio_manager.get_client(user.get('user_id'))
                
                if dl_client:
                    await asyncio.to_thread(download_booklet, dl_client, album_meta['booklet_url'], temp_path)
                    if os.path.exists(temp_path):
                        booklet_path = temp_path
                else:
                    raise Exception("Klien HighResAudio tidak tersedia.")
            except Exception as e:
                await edit_message(user['bot_msg'], f"❌ Gagal mengunduh booklet: {e}")
                return
            
            if booklet_path and os.path.exists(booklet_path):
                try: 
                    await user['bot_msg'].reply_document(
                        document=booklet_path, 
                        caption=f"**Booklet**: {album_meta['title']}", 
                        file_name=f"{album_meta['title']} - Booklet.pdf"
                    )
                    await edit_message(user['bot_msg'], "✅ Booklet berhasil dikirim! Tugas selesai.")
                except Exception as e:
                    await edit_message(user['bot_msg'], f"❌ Gagal mengirim file Telegram: {e}")
            else:
                await edit_message(user['bot_msg'], "❌ File booklet gagal diproses/rusak.")
        else:
            await edit_message(user['bot_msg'], f"❌ Tidak ada booklet digital yang dirilis untuk album ini.")
        
        return

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
    
    task_results = await run_concurrent_tasks(tasks, update_details, limit=4)
    
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

    if upload:
        if booklet_path and os.path.exists(booklet_path):
            try:
                await user['bot_msg'].reply_document(
                    document=booklet_path,
                    caption=f"**Booklet**\n{album_meta['title']} - {album_meta['artist']}",
                )
            except Exception as e:
                LOGGER.error(f"HighResAudio: Gagal mengunggah booklet: {e}")
        
        await album_upload(album_meta, user)
