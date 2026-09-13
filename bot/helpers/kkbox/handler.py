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
    process_artist_metadata,
    custom_url_parse
)
from .manager import KKBoxError

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
            
        elif media_type == 'artist':
            await start_artist(item_id, user)
            
        else:
            raise NotImplementedError(f"Tipe media KKBox '{media_type}' belum didukung.")
        
    except Exception as e:
        LOGGER.error(f"Error fatal di KKBox handler: {e}\n{traceback.format_exc()}")
        raise e 


async def start_artist(artist_id: str, user: dict):
    """Handler untuk unduhan seluruh diskografi artis KKBox."""
    try:
        artist_meta = await process_artist_metadata(artist_id, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata artist KKBox: {e}")

    artist_folder = sanitize_filepath(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{artist_meta['provider']}/{artist_meta['title']}")
    artist_meta['folderpath'] = artist_folder

    upload_album = True
    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    
    if bot_set.artist_batch: 
        upload_album = True if bot_set.upload_mode == 'Telegram' else False
    if artist_zip: 
        upload_album = False 

    successful_albums = []
    for album in artist_meta.get('releases', []):
        # Cari dari key 'id' terlebih dahulu, gunakan 'album_id' sebagai fallback
        raw_id = album.get('id') or album.get('album_id')
        
        # Lakukan validasi SEBELUM mengonversinya menjadi string
        if not raw_id:
            continue
            
        album_id = str(raw_id)
            
        try:
            await start_album(album_id, user, upload=upload_album)
            successful_albums.append(album_id)
        except Exception as e:
            LOGGER.warning(f"KKBox: Gagal mengunduh rilis {album_id} milik {artist_meta['title']}: {e}")
            continue

    if not successful_albums:
        raise Exception("Tidak ada rilis yang berhasil diunduh untuk artis ini.")

    if not upload_album:
        await artist_upload(artist_meta, user)

async def start_track(item_id: str, user: dict, track_meta: dict | None, upload=True, filepath=None, disable_link=False):
    client = user['kkbox_api']

    if not track_meta:
        try:
            track_meta = await process_track_metadata(item_id, user['r_id'], user)
        except Exception as e:
            LOGGER.warning(f"KKBox track {item_id} tidak tersedia: {e}")
            return False

    download_id = track_meta.get('download_id')
    download_quality = track_meta.get('download_quality_key')
    if not download_id or not download_quality:
        LOGGER.error(f"Metadata tidak lengkap untuk unduhan KKBox track {item_id}")
        return False

    # --- FIX: JALUR DINAMIS UNTUK DOWNGRADE KUALITAS ---
    base_dir = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
    base_dir = sanitize_filepath(base_dir)
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)
    
    # Rantai Fallback Kualitas
    fallback_chain = ['hires', 'hifi', '320k', '192k', '128k']
    try:
        start_idx = fallback_chain.index(download_quality)
        qualities_to_try = fallback_chain[start_idx:]
    except ValueError:
        qualities_to_try = [download_quality, '192k', '128k']

    err = True
    temp_filepath = ""
    is_drm = False

    for qual in qualities_to_try:
        # Perbarui Ekstensi File & Info Kualitas
        if qual in ['hires', 'hifi']: ext = 'flac'
        elif qual == '320k': ext = 'm4a'
        else: ext = 'mp3'
        
        track_meta['extension'] = ext
        track_meta['download_quality_key'] = qual
        
        quality_labels = {'hires': 'FLAC 24-bit', 'hifi': 'FLAC 16-bit', '320k': 'AAC 320k', '192k': 'MP3 192k', '128k': 'MP3 128k'}
        track_meta['quality'] = quality_labels.get(qual, f"Audio {qual}")
        
        filepath = f"{base_dir}/{safe_filename}.{ext}"
        track_meta['filepath'] = filepath
        track_meta['folderpath'] = base_dir

        format_key = {
            '128k': 'mp3_128k_chromecast',
            '192k': 'mp3_192k_kkdrm1',
            '320k': 'aac_320k_m4a_kkdrm1',
            'hifi': 'flac_16_download_kkdrm',
            'hires': 'flac_24_download_kkdrm',
        }.get(qual, 'mp3_128k_chromecast')
        
        play_mode = 'chromecast' if format_key == 'mp3_128k_chromecast' else None

        try:
            urls_list = await asyncio.to_thread(client.get_ticket, download_id, play_mode)
            
            download_url = None
            for fmt in urls_list:
                if fmt['name'] == format_key:
                    download_url = fmt['url']
                    break
            
            if not download_url:
                LOGGER.warning(f"KKBox: Format {format_key} tidak ada di tiket. Mencoba downgrade kualitas...")
                continue
                
            os.makedirs(base_dir, exist_ok=True)

            is_drm = format_key != 'mp3_128k_chromecast'
            temp_filepath = track_meta['filepath'] + ".enc" if is_drm else track_meta['filepath']

            headers_dict = {'User-Agent': 'okhttp/3.14.9'}
            details_aria = {'msg': None, 'headers': headers_dict} if not upload else {
                'msg': user['bot_msg'], 'title': track_meta['title'], 'type': 'Track', 'headers': headers_dict
            }

            client_proxy = client.s.proxies.get('http') or client.s.proxies.get('https')
            if client_proxy and not client_proxy.startswith('socks'):
                details_aria['proxy'] = client_proxy

            err = await download_file(download_url, temp_filepath, retries=1, details=details_aria)

            if err or not os.path.exists(temp_filepath):
                LOGGER.warning(f"KKBox: Aria2 ditolak (404) untuk {track_meta['title']} ({qual}). Mengaktifkan AIOHTTP Fallback...")
                
                # Bersihkan sisa file sebelum berpindah ke AIOHTTP
                for f in [temp_filepath + '.aria2', temp_filepath]:
                    if os.path.exists(f):
                        try: os.remove(f)
                        except: pass
                
                connector = None
                if client_proxy and client_proxy.startswith('socks'):
                    try:
                        from aiohttp_socks import ProxyConnector
                        safe_proxy = client_proxy.replace('socks5h://', 'socks5://').replace('socks4a://', 'socks4://')
                        connector = ProxyConnector.from_url(safe_proxy)
                    except ImportError: pass
                    
                import time
                import yarl
                try:
                    async with aiohttp.ClientSession(headers=headers_dict, connector=connector) as session:
                        get_kwargs = {}
                        if client_proxy and not client_proxy.startswith('socks'):
                            get_kwargs['proxy'] = client_proxy
                            
                        safe_url = yarl.URL(download_url, encoded=True)
                        async with session.get(safe_url, **get_kwargs) as r:
                            r.raise_for_status()
                            total_size = int(r.headers.get('content-length', 0))
                            downloaded = 0
                            start_time = time.time()
                            last_update = start_time
                            
                            async with aiofiles.open(temp_filepath, 'wb') as f:
                                async for chunk in r.content.iter_chunked(256 * 1024):
                                    if chunk:
                                        await f.write(chunk)
                                        downloaded += len(chunk)
                                        
                                        if upload and 'bot_msg' in user:
                                            now = time.time()
                                            if now - last_update > 2.0 or downloaded == total_size:
                                                last_update = now
                                                from bot.helpers.utils import progress_message
                                                await progress_message(downloaded, total_size, details_aria)
                    err = False 
                except Exception as fallback_e:
                    LOGGER.warning(f"KKBox AIOHTTP Fallback gagal ({qual}): {fallback_e}")
                    err = True

            if not err and os.path.exists(temp_filepath):
                break 
            else:
                LOGGER.warning(f"KKBox: CDN 404 untuk {track_meta['title']}. Mencoba downgrade kualitas...")
                await asyncio.sleep(2.0) 

        except Exception as e:
            LOGGER.error(f"KKBox dl_track error untuk {item_id} ({qual}): {e}")
            await asyncio.sleep(2.0)

    if err or not os.path.exists(temp_filepath):
        LOGGER.error(f"KKBox: Gagal mengunduh {track_meta['title']} setelah mencoba semua kualitas yang tersedia.")
        return False

    if is_drm:
        try:
            def _decrypt_kkbox():
                from Cryptodome.Cipher import ARC4
                rc4 = ARC4.new(client.lic_content_key, drop=512)
                with open(temp_filepath, 'rb') as f_in, open(track_meta['filepath'], 'wb') as f_out:
                    f_in.seek(1024) 
                    while True:
                        chunk = f_in.read(65536)
                        if not chunk: break
                        f_out.write(rc4.decrypt(chunk))
                os.remove(temp_filepath) 

            await asyncio.to_thread(_decrypt_kkbox)
        except Exception as e:
            LOGGER.error(f"KKBox decrypt gagal untuk {item_id}: {e}")
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
        'msg': user.get('bot_msg'),
        'title': album_meta['title'],
        'type': album_meta['type']
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details, limit=4)
    
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

    if upload:
        await album_upload(album_meta, user)
