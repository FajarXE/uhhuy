# [GANTI SELURUH FILE: bot/helpers/kkbox/handler.py]

import aiohttp
import aiofiles
import os
import shutil
import traceback
import asyncio

from pathvalidate import sanitize_filepath
from config import Config

from .metadata import (
    process_track_metadata, 
    process_album_metadata,
    process_playlist_metadata,
    custom_url_parse
)
from .manager import KKBoxError

# Impor yang diperlukan
from ..uploder import *
from ..metadata import set_metadata
from ..message import edit_message
from ..utils import fetch_zip_settings, run_concurrent_tasks, format_string, zip_handler, download_file
from ...settings import bot_set 
import bot.helpers.translations as lang
from bot.logger import LOGGER

try:
    from bot.helpers.lyrics.manager import lyrics_manager
except ImportError:
    lyrics_manager = None


async def start_kkbox(url: str, user: dict):
    """Handler utama untuk link KKBox."""
    try:
        media_type, item_id, extra_kwargs = custom_url_parse(url)
        
        if media_type == 'track':
            success = await start_track(item_id, user, None)
            if not success:
                raise Exception("Gagal mengunduh atau memproses track.")
        
        elif media_type == 'album':
            await start_album(item_id, user)

        elif media_type == 'playlist':
            await start_playlist(item_id, user)
            
        else:
            raise NotImplementedError(f"Tipe media KKBox '{media_type}' belum didukung.")
        
    except Exception as e:
        LOGGER.error(f"Error fatal di KKBox handler: {e}\n{traceback.format_exc()}")
        raise e 


async def start_track(item_id: str, user: dict, track_meta: dict | None, upload=True, filepath=None, disable_link=False):
    client = user['kkbox_api']

    if not track_meta:
        try:
            track_meta = await process_track_metadata(item_id, user['r_id'], user)
        except Exception as e:
            LOGGER.warning(f"KKBox track {item_id} tidak tersedia: {e}")
            return False
            
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)

    download_id = track_meta.get('download_id')
    download_quality = track_meta.get('download_quality_key')
    if not download_id or not download_quality:
        LOGGER.error(f"Metadata tidak lengkap untuk unduhan KKBox track {item_id}")
        return False

    track_meta['folderpath'] = filepath
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)

    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    try:
        format_key = {
            '128k': 'mp3_128k_chromecast',
            '192k': 'mp3_192k_kkdrm1',
            '320k': 'aac_320k_m4a_kkdrm1',
            'hifi': 'flac_16_download_kkdrm',
            'hires': 'flac_24_download_kkdrm',
        }[download_quality]
        
        play_mode = 'chromecast' if format_key == 'mp3_128k_chromecast' else None

        urls_list = await asyncio.to_thread(client.get_ticket, download_id, play_mode)
        
        download_url = None
        for fmt in urls_list:
            if fmt['name'] == format_key:
                download_url = fmt['url']
                break
        
        if not download_url:
            raise KKBoxError(f"Format {format_key} tidak ditemukan di tiket.")
            
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        # --- [FIX KECEPATAN] FULL ARIA2 + DEKRIPSI OTOMATIS ---
        is_drm = format_key != 'mp3_128k_chromecast'
        # File sementara untuk menampung data mentah ber-DRM
        temp_filepath = track_meta['filepath'] + ".enc" if is_drm else track_meta['filepath']

        # Inject penyamaran dari KKBox API
        headers_dict = {'User-Agent': 'okhttp/3.14.9'}
        details_aria = {'msg': None, 'headers': headers_dict} if not upload else {
            'msg': user['bot_msg'], 'title': track_meta['title'], 'type': 'Track', 'headers': headers_dict
        }

        # 1. Aria2 menyedot file terenkripsi secara brutal
        err = await download_file(download_url, temp_filepath, retries=1, details=details_aria)

        if err or not os.path.exists(temp_filepath):
            LOGGER.error(f"KKBox: Aria2 gagal mengunduh {track_meta['title']}")
            return False

        # 2. Mesin Dekripsi ARC4 Lokal (Menjahit DRM jadi lagu normal)
        if is_drm:
            def _decrypt_kkbox():
                from Cryptodome.Cipher import ARC4
                rc4 = ARC4.new(client.lic_content_key, drop=512)
                with open(temp_filepath, 'rb') as f_in, open(track_meta['filepath'], 'wb') as f_out:
                    f_in.seek(1024) # Melompati header 1024 bytes bawaan KKBox DRM
                    while True:
                        chunk = f_in.read(65536)
                        if not chunk: break
                        f_out.write(rc4.decrypt(chunk))
                os.remove(temp_filepath) # Bersihkan file mentah

            # Jalankan di background agar bot tidak lag
            await asyncio.to_thread(_decrypt_kkbox)
        # ----------------------------------------------------

    except Exception as e:
        LOGGER.error(f"KKBox dl_track gagal untuk {item_id}: {e}")
        return False

    try:
        await set_metadata(track_meta, user['user_id'])
    except FileNotFoundError:
        LOGGER.error(f"[Errno 2] File not found setelah download KKBox: {filepath}")
        return False
    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata KKBox: {filepath} -> {e}")
        try: os.remove(filepath)
        except: pass
        return False

    if upload:
        await track_upload(track_meta, user, disable_link)

    return True

async def start_album(album_id: str, user: dict, upload=True):
    try:
        album_meta = await process_album_metadata(album_id, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata album KKBox: {e}")

    album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder
    
    os.makedirs(album_folder, exist_ok=True)

    if upload:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    tasks = []
    for track in album_meta['tracks']:
        tasks.append(start_track(track['itemid'], user, track, False, album_folder))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': album_meta['title'],
        'type': album_meta['type']
    }
    
    # --- [FIX PARALEL] Menggunakan MAX_WORKERS ---
    task_results = await run_concurrent_tasks(tasks, update_details, limit=Config.MAX_WORKERS)
    
    successful_tracks = [album_meta['tracks'][i] for i, result in enumerate(task_results) if result]
    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        raise Exception(f"Tidak ada lagu KKBox yang berhasil diunduh untuk album {album_meta['title']}.")

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

    if album_meta.get('cover'):
        try:
            cover_path = os.path.join(album_folder, "cover.jpg")
            if album_meta['cover'].startswith('http'):
                 async with aiohttp.ClientSession() as session:
                    async with session.get(album_meta['cover']) as resp:
                        if resp.status == 200:
                            async with aiofiles.open(cover_path, mode='wb') as f:
                                await f.write(await resp.read())
            elif os.path.exists(album_meta['cover']):
                await asyncio.to_thread(shutil.copy, album_meta['cover'], cover_path)
        except Exception: pass

    if album_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {album_meta['totaltracks']} lagu menjadi .zip...")
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)

async def start_playlist(playlist_id: str, user: dict):
    try:
        pl_meta = await process_playlist_metadata(playlist_id, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata playlist KKBox: {e}")

    pl_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{pl_meta['provider']}/Playlists/{pl_meta['title']}"
    pl_folder = sanitize_filepath(pl_folder)
    pl_meta['folderpath'] = pl_folder
    
    os.makedirs(pl_folder, exist_ok=True)

    siesta_cover = getattr(Config, 'PROJECT_SIESTA_COVER', None)
    
    if siesta_cover: pl_meta['cover'] = siesta_cover
    elif os.path.exists("assets/project-siesta.png"): pl_meta['cover'] = os.path.abspath("assets/project-siesta.png")
    elif os.path.exists("assets/project-siesta.jpg"): pl_meta['cover'] = os.path.abspath("assets/project-siesta.jpg")
    elif not pl_meta.get('cover'):
        if pl_meta.get('tracks') and len(pl_meta['tracks']) > 0:
            fallback = pl_meta['tracks'][0].get('cover')
            if fallback: pl_meta['cover'] = fallback

    if pl_meta.get('cover'):
        try: pl_meta['poster_msg'] = await post_art_poster(user, pl_meta)
        except Exception: pass

    tasks = []
    for track in pl_meta['tracks']:
        tasks.append(start_track(track['itemid'], user, track, False, pl_folder))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': pl_meta['title'],
        'type': 'playlist' 
    }
    
    # --- [FIX PARALEL] Menggunakan MAX_WORKERS ---
    task_results = await run_concurrent_tasks(tasks, update_details, limit=Config.MAX_WORKERS)
    
    successful_tracks = [pl_meta['tracks'][i] for i, result in enumerate(task_results) if result]
    pl_meta['tracks'] = successful_tracks
    pl_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        raise Exception(f"Tidak ada lagu KKBox yang berhasil diunduh untuk playlist {pl_meta['title']}.")

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

    if pl_meta.get('cover'):
        try:
            cover_path = os.path.join(pl_folder, "cover.jpg")
            if pl_meta['cover'].startswith('http'):
                 async with aiohttp.ClientSession() as session:
                    async with session.get(pl_meta['cover']) as resp:
                        if resp.status == 200:
                            async with aiofiles.open(cover_path, mode='wb') as f:
                                await f.write(await resp.read())
            elif os.path.exists(pl_meta['cover']):
                await asyncio.to_thread(shutil.copy, pl_meta['cover'], cover_path)
        except Exception: pass

    if playlist_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {pl_meta['totaltracks']} lagu menjadi .zip...")
        pl_meta['zip_path'] = await zip_handler(pl_meta['folderpath'])

    await edit_message(user['bot_msg'], lang.s.UPLOADING)
    await album_upload(pl_meta, user)
