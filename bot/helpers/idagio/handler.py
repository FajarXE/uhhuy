# [GANTI FILE: bot/helpers/idagio/handler.py]

import os
import traceback
import asyncio
import requests 
import math 

from pathvalidate import sanitize_filepath
from config import Config
from Cryptodome.Cipher import AES
from Cryptodome.Hash import SHA256

from .metadata import (
    process_track_metadata, 
    process_album_metadata,
    custom_url_parse
)
from .manager import IdagioError

from ..uploder import *
from ..metadata import set_metadata
from ..message import edit_message
from ..utils import fetch_zip_settings, run_concurrent_tasks, format_string, zip_handler

import bot.helpers.translations as lang
from bot.logger import LOGGER

try:
    from bot.helpers.lyrics.manager import lyrics_manager
except ImportError:
    lyrics_manager = None


async def start_idagio(url: str, user: dict):
    """Handler utama untuk link Idagio."""
    try:
        media_type, item_id, extra_kwargs = custom_url_parse(url)
        
        if media_type == 'track':
            await start_track(item_id, user, None)
        elif media_type == 'album':
            await start_album(item_id, user)
        else:
            raise NotImplementedError(f"Tipe media Idagio '{media_type}' belum didukung.")
        
    except Exception as e:
        LOGGER.error(f"Error fatal di Idagio handler: {e}\n{traceback.format_exc()}")
        raise e 


async def start_track(item_id: str, user: dict, track_meta: dict | None, upload=True, filepath=None, disable_link=False):

    client = user['idagio_api']

    if not track_meta:
        try:
            track_meta = await process_track_metadata(item_id, user['r_id'], user)
        except Exception as e:
            LOGGER.error(f"Idagio track {item_id} gagal di process_track_metadata: {e}")
            raise e
            
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)

    quality_tier = track_meta.get('download_quality_tier') 
    stream_track_id = track_meta.get('download_track_id') 
    
    if not quality_tier or not stream_track_id:
        raise IdagioError(f"Metadata tidak lengkap untuk track {item_id}")

    track_meta['folderpath'] = filepath
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)[:150].strip()
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

    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        await download_track_idagio(
            client,
            stream_track_id,
            quality_tier,
            track_meta['filepath'],
            details
        )

    except Exception as e:
        LOGGER.error(f"Idagio dl_track gagal untuk {item_id}: {e}")
        raise e

    try:
        await set_metadata(track_meta, user['user_id'])
    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata Idagio: {filepath} -> {e}")
        try: os.remove(filepath)
        except: pass
        raise e

    if upload:
        await track_upload(track_meta, user, disable_link)

    return True


async def download_track_idagio(client, track_id, quality_tier, temp_location, details):
    """
    Fungsi ASINKRON untuk mengunduh dengan Aria2 dan mendekripsi file Idagio.
    """
    # 1. Dapatkan stream data
    def get_stream():
        stream_data_list = client.get_track_stream(track_id, quality=quality_tier)
        if not stream_data_list and quality_tier == 90:
            LOGGER.debug(f"Idagio: Gagal mendapatkan stream, mencoba fallback Sonos...")
            stream_data_list = client.get_track_stream_2(track_id, quality=quality_tier)
        return stream_data_list

    stream_data_list = await asyncio.to_thread(get_stream)
    if not stream_data_list:
        raise IdagioError(f"Tidak bisa mendapatkan data stream untuk track {track_id}")
        
    stream_data = stream_data_list[0]
    download_url = stream_data.get('url')

    # 2. Intip Header untuk Curi Kunci Enkripsi
    def check_encryption():
        r = client.s.get(download_url, stream=True)
        headers = r.headers
        r.close()
        return headers

    headers = await asyncio.to_thread(check_encryption)
    
    is_encrypted = False
    cipher_key = None
    cipher_iv = None

    if headers.get('X-X'):
        is_encrypted = True
        base_key, iv = headers['X-X'].split(' ')
        secret = 'mola*jbaf^*`*V^fG^lkf4fb_bba2'
        offset = 3
        extended_key = ''.join(map(chr, [(ord(char) + offset + 65536) % 65536 for char in secret]))

        key = base_key + extended_key
        key_checksum = SHA256.new(key.encode('utf-8')).hexdigest()[:16].encode('utf-8')
        cipher_key = key_checksum
        cipher_iv = iv.encode('utf-8')

    # 3. Minta Aria2 untuk Menyedot File secara Brutal!
    from bot.helpers.utils import download_file
    err = await download_file(download_url, temp_location, details=details)
    if err:
        raise IdagioError(f"Aria2 gagal mengunduh track: {err}")

    # 4. Dekripsi Cepat jika file terenkripsi
    if is_encrypted:
        if details and 'msg' in details:
            from bot.helpers.message import edit_message
            try:
                await edit_message(details['msg'], f"⚙️ **Mendekripsi File Idagio (AES-CTR)...**\n`{details.get('title', 'Unknown Track')}`", None, False)
            except: pass

        def decrypt_file():
            dec_loc = temp_location + ".dec"
            cipher = AES.new(cipher_key, AES.MODE_CTR, initial_value=cipher_iv, nonce=b'')
            with open(temp_location, 'rb') as f_in, open(dec_loc, 'wb') as f_out:
                while True:
                    chunk = f_in.read(65536)
                    if not chunk: break
                    f_out.write(cipher.decrypt(chunk))
            os.replace(dec_loc, temp_location)

        await asyncio.to_thread(decrypt_file)
        
    return True


async def start_album(album_id: str, user: dict, upload=True):
    """
    Handler untuk unduhan album dengan Sistem Konkurensi Cerdas.
    """
    try:
        album_meta = await process_album_metadata(album_id, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata album Idagio: {e}")

    album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder 

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
    
    results = await run_concurrent_tasks(worker_tasks, update_details, limit=Config.MAX_WORKERS)
    
    successful_tracks = [album_meta['tracks'][i] for i, result in enumerate(task_results) if result]
    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        raise Exception(f"Tidak ada lagu Idagio yang berhasil diunduh untuk album {album_meta['title']}.")

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

    if album_zip: 
        await edit_message(user['bot_msg'], f"Menyiapkan {album_meta['totaltracks']} lagu menjadi .zip...")
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)
