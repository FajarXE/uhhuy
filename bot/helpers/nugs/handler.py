# [GANTI SELURUH FILE: bot/helpers/nugs/handler.py]

import asyncio
import os
import re
import traceback
import shutil
import aiohttp
import aiofiles
import math 

from pathvalidate import sanitize_filepath
from config import Config

# Impor dari modul Nugs
from .nugs_api import NugsNotAvailableError
from .mqa_identifier import MqaIdentifier
from .utils import create_temp_filename

# Impor yang diperlukan dari bot
from ..uploder import *
from ..metadata import set_metadata, create_cover_file
from ..message import edit_message
# --- [PERBAIKAN IMPORT] Menambahkan download_file dan post_art_poster ---
from ..utils import fetch_zip_settings, run_concurrent_tasks, format_string, zip_handler, download_file, post_art_poster
from bot.logger import LOGGER
import bot.helpers.translations as lang

# --- TAMBAHAN BARU: IMPOR MANAGER LIRIK ---
try:
    from bot.helpers.lyrics.manager import lyrics_manager
except ImportError:
    lyrics_manager = None
# --- BATAS TAMBAHAN ---

# Prioritas Kualitas (didasarkan pada interface.py)
# Format: {codec_enum: (nama_kualitas, ekstensi, prioritas)}
QUALITY_MAP = {
    'AAC': ("AAC 150k", "m4a", 0),
    'ALAC': ("ALAC", "m4a", 1), 
    'FLAC': ("FLAC", "flac", 2),
    'MQA': ("MQA", "flac", 3), 
    'MHA1': ("Sony 360RA", "m4a", 4)
}

PLAY_URL_REGEX = r'https?://play\.nugs\.net/#/(artist|catalog/recording|playlists/playlist)/(\d+)'
API_URL_REGEX = r'https?://streamapi\.nugs\.net/show\.aspx\?show=(\d+)'


def custom_url_parse(link: str):
    """Mengekstrak Tipe dan ID dari URL Nugs."""
    play_match = re.search(PLAY_URL_REGEX, link)
    if play_match:
        media_type_raw = play_match.group(1)
        item_id = play_match.group(2)
        media_types = {
            'catalog/recording': 'album',
            'artist': 'artist',
            'playlists/playlist': 'playlist',
        }
        media_type = media_types.get(media_type_raw)
        if not media_type:
             raise NotImplementedError(f"Tipe media Nugs '{media_type_raw}' belum didukung.")
        return media_type, item_id

    api_match = re.search(API_URL_REGEX, link)
    if api_match:
        media_type = 'album'
        item_id = api_match.group(1)
        return media_type, item_id

    raise Exception(f"URL Nugs tidak valid atau tidak dikenali: {link}")


async def parse_stream_format(stream_url: str):
    """Mengurai URL stream untuk menentukan kualitas."""
    if ".aac150/" in stream_url: return 'AAC'
    if ".alac16/" in stream_url: return 'ALAC'
    if ".flac16/" in stream_url: return 'FLAC'
    if ".mqa24/" in stream_url: return 'MQA'
    if ".s360/" in stream_url: return 'MHA1'
    return None

async def download_temp_header(file_url: str, user_agent: str) -> str | None:
    """Mengunduh header file untuk analisis MQA (Tetap menggunakan aiohttp karena hanya butuh 1MB)."""
    temp_location = await asyncio.to_thread(create_temp_filename, '.flac')
    try:
        headers = {'User-Agent': user_agent, 'Range': 'bytes=0-1048576'}
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url, headers=headers) as response:
                response.raise_for_status()
                content = await response.content.read()
                if not content:
                    return None
                async with aiofiles.open(temp_location, 'wb') as f:
                    await f.write(content)
                return temp_location
    except Exception as e:
        if os.path.exists(temp_location):
            os.remove(temp_location)
        return None

async def process_track_metadata(track_data: dict, album_data: dict, user: dict):
    """Memproses metadata untuk satu lagu."""
    client = user['nugs_api'] 
    sub_details = client.subscription_details 
    
    release_date_str = album_data.get('releaseDateFormatted', '').replace('/', '-')
    if not release_date_str:
        title_date_match = re.search(r'^(\d{2}/\d{2}/\d{2})', album_data.get('containerInfo', ''))
        if title_date_match:
            try:
                parts = title_date_match.group(1).split('/')
                year = f"20{parts[2]}"
                month = parts[0]
                day = parts[1]
                release_date_str = f"{year}-{month}-{day}"
            except Exception:
                release_date_str = '' 
    
    release_year = release_date_str.split('-')[0] if '-' in release_date_str else ''
    
    metadata = {
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/",
        'provider': 'Nugs.net',
        'type': 'track',
        'itemid': track_data.get('songID'),
        'title': track_data.get('songTitle'),
        'artist': album_data.get('artistName'),
        'albumartist': album_data.get('artistName'),
        'album': album_data.get('containerInfo'),
        'tracknumber': str(track_data.get('trackNum', 0)).zfill(2),
        'discnumber': str(track_data.get('discNum', 1)).zfill(2),
        'volume': str(track_data.get('discNum')),
        'totaltracks': str(len(album_data.get('songs'))),
        'totaldiscs': str(album_data.get('numDiscs', 1)),
        'totalvolume': str(album_data.get('numDiscs', 1)),
        'date': release_date_str,
        'year': release_year,
        'copyright': f"© {release_year} {album_data.get('licensorName')}",
        'explicit': False, 
        'isrc': '', 
        'lyrics': '',
        'duration': int(track_data.get('duration', 0)), 
    }
    
    cover_url = f"https://secure.livedownloads.com{album_data.get('img', {}).get('url')}"
    metadata['cover'] = await create_cover_file(cover_url, metadata)
    metadata['thumbnail'] = await create_cover_file(cover_url, metadata, True)

    stream_data = []
    for stream_format_id in [9, 5, 2, None]: 
        try:
            stream_info = await asyncio.to_thread(
                client.get_stream,
                track_data.get('trackID'),
                sub_details,
                stream_format_id
            )
            stream_url = stream_info.get('streamLink')
            codec_key = await parse_stream_format(stream_url)
            
            if codec_key:
                quality_name, extension, priority = QUALITY_MAP[codec_key]
                stream_data.append({
                    'url': stream_url,
                    'codec': codec_key,
                    'quality_name': quality_name,
                    'extension': extension,
                    'priority': priority
                })
        except Exception as e:
            continue
            
    if not stream_data:
        raise NugsNotAvailableError(f"Tidak ada stream yang valid ditemukan untuk track {metadata['title']}")
        
    stream_data = sorted(stream_data, key=lambda k: k['priority'], reverse=True)
    selected_stream = stream_data[0]
    
    metadata['quality'] = selected_stream['quality_name'] 
    metadata['extension'] = selected_stream['extension']
    metadata['download_url'] = selected_stream['url']

    if selected_stream['codec'] == 'MQA':
        temp_flac_header = await download_temp_header(selected_stream['url'], client.session.user_agent)
        mqa_verified = False
        if temp_flac_header:
            try:
                mqa_file = await asyncio.to_thread(MqaIdentifier, temp_flac_header)
                if mqa_file.is_mqa:
                    metadata['bit_depth'] = mqa_file.bit_depth
                    metadata['sample_rate'] = mqa_file.original_sample_rate
                    mqa_verified = True
            except Exception:
                pass
            finally:
                if os.path.exists(temp_flac_header):
                    os.remove(temp_flac_header)
        
        if not mqa_verified:
            metadata['bit_depth'] = 24 

    elif selected_stream['codec'] == 'FLAC':
        metadata['bit_depth'] = 16
        metadata['sample_rate'] = 44100

    elif selected_stream['codec'] == 'ALAC':
        metadata['bit_depth'] = 16
        metadata['sample_rate'] = 44100
    
    metadata['quality_tag'] = metadata['quality']
    
    return metadata

# --- KINI MENGGUNAKAN FULL ARIA2 ENGINE ---
async def start_track(track_meta: dict, user: dict, upload=True):
    """Handler untuk mengunduh satu track Nugs."""
    client = user['nugs_api']
    filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
    filepath = sanitize_filepath(filepath)
    
    track_meta['folderpath'] = filepath
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)

    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    try:
        download_url = track_meta['download_url']
        user_agent = client.session.user_agent
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Penyamaran Aria2 dengan User-Agent Aplikasi Nugs
        headers_dict = {'User-Agent': user_agent}
        details_aria = {'msg': None, 'headers': headers_dict} if not upload else {
            'msg': user['bot_msg'], 'title': track_meta.get('title'), 'type': 'Track', 'headers': headers_dict
        }

        if os.path.exists(filepath):
            os.remove(filepath)
            
        # 1. Sedot langsung pakai Aria2!
        err = await download_file(download_url, filepath, retries=1, details=details_aria)

        if err or not os.path.exists(filepath) or os.path.getsize(filepath) < 10000:
            LOGGER.error(f"Nugs: Aria2 gagal mengunduh {track_meta['itemid']}")
            return False

    except Exception as e:
        LOGGER.error(f"Nugs dl_track gagal untuk {track_meta['itemid']}: {e}")
        return False

    try:
        await set_metadata(track_meta, user['user_id'])
    except Exception as e:
        LOGGER.error(f"Gagal memproses metadata Nugs: {filepath} -> {e}")
        try: os.remove(filepath)
        except: pass
        return False

    if upload:
        await track_upload(track_meta, user)

    return True

async def start_album(album_id: str, user: dict, upload=True):
    """Handler untuk unduhan album Nugs."""
    client = user['nugs_api']
    
    try:
        album_data = await asyncio.to_thread(client.get_album, album_id)
        if not album_data:
            raise Exception(f"Album {album_id} tidak ditemukan.")
            
        tracks_list = album_data.get('songs', [])
        if not tracks_list:
            raise Exception(f"Tidak ada lagu yang ditemukan di album {album_id}.")
            
    except Exception as e:
        raise Exception(f"Gagal mendapatkan metadata album Nugs: {e}")

    try:
        track_one_data = tracks_list[0]
        track_one_meta = await process_track_metadata(track_one_data, album_data, user)
    except Exception as e:
        track_one_meta = {}

    poster_release_date = track_one_meta.get('date', album_data.get('releaseDateFormatted', '').replace('/', '-'))
    if not poster_release_date:
        title_date_match = re.search(r'^(\d{2}/\d{2}/\d{2})', album_data.get('containerInfo', ''))
        if title_date_match:
            try:
                parts = title_date_match.group(1).split('/')
                year = f"20{parts[2]}"
                month = parts[0]
                day = parts[1]
                poster_release_date = f"{year}-{month}-{day}"
            except Exception:
                poster_release_date = '' 
    
    album_meta = {
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/",
        'provider': 'Nugs.net',
        'type': 'album',
        'itemid': album_id,
        'title': album_data.get('containerInfo'),
        'artist': album_data.get('artistName'),
        'albumartist': album_data.get('artistName'),
        'totaltracks': str(len(tracks_list)),
        'date': poster_release_date,
        'year': poster_release_date.split('-')[0] if '-' in poster_release_date else '',
        'release_date': poster_release_date,
        'totalvolume': track_one_meta.get('totalvolume', str(album_data.get('numDiscs', 1))),
        'quality': track_one_meta.get('quality', 'Unknown'), 
        'explicit': track_one_meta.get('explicit', False), 
        'lyrics': None, 
    }
    
    album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder

    if upload:
        cover_url = f"https://secure.livedownloads.com{album_data.get('img', {}).get('url')}"
        album_meta['cover'] = await create_cover_file(cover_url, album_meta)
        album_meta['thumbnail'] = await create_cover_file(cover_url, album_meta, True)
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    tasks = []
    
    if track_one_meta: 
        tasks.append(start_track(track_one_meta, user, False))
    else:
        LOGGER.warning(f"Nugs: Gagal memproses metadata untuk lagu pertama. Mencoba melanjutkan...")

    for track_data in tracks_list[1:]: 
        try:
            # --- [PERBAIKAN] Jangan biarkan error disembunyikan ---
            track_meta = await process_track_metadata(track_data, album_data, user)
            if track_meta:
                tasks.append(start_track(track_meta, user, False))
        except Exception as e:
            # Tampilkan error ke log agar kita tahu kenapa lagu ini dilewati
            LOGGER.error(f"Nugs: Lagu ke-{track_data.get('trackNum')} gagal diproses: {e}")
            continue

    if not tasks:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk album Nugs {album_meta['title']}")

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': album_meta['title'],
        'type': album_meta['type']
    }
    
    # --- [FIX] PARALEL MAX_WORKERS ---
    task_results = await run_concurrent_tasks(tasks, update_details, limit=Config.MAX_WORKERS)
    
    successful_tracks_count = sum(1 for result in task_results if result)

    if successful_tracks_count == 0:
        raise Exception(f"Tidak ada lagu Nugs yang berhasil diunduh untuk album {album_meta['title']}.")

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

    # --- [FIX COVER DI DALAM ZIP] ---
    # Salin file cover dari folder sementara ke folder album sebelum di-zip
    if album_meta.get('cover') and os.path.exists(album_meta['cover']):
        try:
            cover_target = os.path.join(album_meta['folderpath'], "cover.jpg")
            shutil.copy(album_meta['cover'], cover_target)
        except Exception as e:
            LOGGER.warning(f"Gagal menyalin cover ke folder ZIP: {e}")
    # ---------------------------------

    if album_zip: 
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])

    if upload:
        await album_upload(album_meta, user)

async def start_nugs(url: str, user: dict):
    """Handler utama untuk link Nugs."""
    try:
        media_type, item_id = custom_url_parse(url)
        
        if media_type == 'album':
            await start_album(item_id, user)
        else:
            raise NotImplementedError(f"Tipe media Nugs '{media_type}' belum didukung.")
        
    except Exception as e:
        LOGGER.error(f"Error fatal di Nugs handler: {e}\n{traceback.format_exc()}")
        raise e 
