# [GANTI FILE: bot/helpers/idagio/metadata.py]

import copy
import re
import aiohttp
import asyncio
import os 
import traceback 
from urllib.parse import urlparse
from config import Config 

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .manager import idagio_manager, IdagioError
from bot.logger import LOGGER

# Pemetaan dari bot Anda ke nilai API Idagio
QUALITY_MAP_API = {
    "FLAC": 90,
    "MP3_320": 70,
    "MP3_160": 50
}
# Pemetaan dari nilai API ke tampilan
QUALITY_MAP_DISPLAY = {
    90: ("FLAC", "flac"),
    70: ("AAC 320k", "m4a"),
    50: ("AAC 160k", "m4a")
}
# Urutan prioritas kualitas
QUALITY_ORDER = ["FLAC", "MP3_320", "MP3_160"]


def custom_url_parse(link: str):
    """Mengekstrak Tipe dan ID dari URL Idagio"""
    link = re.sub(r'/[a-z]{2}/', '/', link) # Hapus kode bahasa
    url = urlparse(link)
    components = url.path.split('/')
    
    if not components or len(components) <= 2:
        raise IdagioError(f'URL tidak valid: {link}')
    
    # Format: /TYPE/ID
    if len(components) in {3, 4}:
        type_ = components[1]
        media_id = components[2]
    else:
        raise IdagioError(f'URL tidak valid: {link}')

    if type_ == 'recordings':
        media_type = 'track'
    elif type_ == 'albums':
        media_type = 'album'
    elif type_ == 'playlists':
        media_type = 'playlist'
    elif type_ == 'profiles':
        media_type = 'artist'
    else:
        raise IdagioError(f'Tipe URL Idagio tidak didukung: {type_}')

    return media_type, media_id, {}


async def _process_cover(metadata: dict, url: str):
    """Memproses sampul dari URL Idagio"""
    return await create_cover_file(url, metadata)


async def process_track_metadata(track_id: str, r_id: str, user: dict, pre_data: dict = None, alb_info_pre: dict = None, track_num_pre: int = None):
    """Memproses metadata untuk satu lagu (recording)."""
    client = user['idagio_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    try:
        if pre_data:
            track_data = pre_data
        else:
            track_data = await asyncio.to_thread(client.get_recording, track_id)
            
        if alb_info_pre:
            album_data = alb_info_pre
        else:
            album_id = track_data.get('albums')[0] # Ambil album pertama
            album_data = await asyncio.to_thread(client.get_album, album_id)

    except Exception as e:
        LOGGER.error(f"Idagio: Gagal mendapatkan metadata track {track_id}: {e}\n{traceback.format_exc()}")
        raise e

    if track_data.get('geoblocked'):
        raise IdagioError(f"Track '{track_data.get('name')}' diblokir di wilayah Anda.")

    metadata['itemid'] = track_id
    metadata['title'] = track_data.get('work').get('title') #
    metadata['album'] = album_data.get('title')
    
    # --- Logika Artis & Composer ---
    try:
        metadata['composer'] = track_data.get('work').get('composer').get('name')
    except AttributeError:
        LOGGER.warning("Idagio: Gagal mendapatkan composer utama.")
        metadata['composer'] = "Various Artists"
    try:
        album_artist_obj = [c for c in album_data.get('participants') if c.get('type') == 'composer'][0]
        metadata['albumartist'] = album_artist_obj.get('name')
    except (IndexError, AttributeError):
        metadata['albumartist'] = metadata['composer'] # Fallback ke composer track
    metadata['artist'] = track_data.get('summary') #
    # --- Batas Logika Artis ---

    # --- Temukan Track Number, Disc Number, dan Durasi ---
    download_track_id = None
    track_obj_list = track_data.get('tracks', [])
    
    try:
        if track_obj_list:
            track_obj = track_obj_list[0]
            download_track_id = track_obj.get('id') 
            
            # --- PERBAIKAN: Logika default yang lebih kuat ---
            disc_num = track_obj.get('discNumber')
            metadata['discnumber'] = str(disc_num if disc_num else 1)
            
            total_discs = album_data.get('discCount')
            metadata['totaldiscs'] = str(total_discs if total_discs else 1)
            metadata['totalvolumes'] = metadata['totaldiscs']
            
            try:
                metadata['duration'] = int(track_obj.get('duration')) 
            except (TypeError, ValueError):
                LOGGER.warning(f"Idagio: Gagal mendapatkan durasi untuk {track_id}")
                metadata['duration'] = 0
            # --- BATAS PERBAIKAN ---

    except (IndexError, AttributeError):
        LOGGER.warning(f"Idagio: Gagal menemukan stream ID/Disc/Durasi untuk {track_id}")
    
    metadata['tracknumber'] = str(track_num_pre) if track_num_pre else "1"
    metadata['totaltracks'] = str(len(album_data.get('tracks')))
    # --- Batas Perbaikan ---

    metadata['date'] = album_data.get('publishDate', '1900')[:4] #
    metadata['copyright'] = f'©℗ {album_data.get("copyright")}' #
    metadata['upc'] = album_data.get('upc')
    metadata['provider'] = 'Idagio'
    metadata['type'] = 'track'
    metadata['explicit'] = False 

    # --- Logika Genre ---
    genres = []
    try:
        if track_data.get('work').get('genre'):
            genres.append(track_data.get('work').get('genre').get('title'))
        if track_data.get('work').get('subgenre'):
            genres.append(track_data.get('work').get('subgenre').get('title'))
    except AttributeError:
        pass
    if genres:
        metadata['genre'] = ", ".join(genres)
    
    # Sampul (Gunakan cache cover dari album jika tersedia)
    if alb_info_pre and alb_info_pre.get('cover'):
        metadata['cover'] = alb_info_pre['cover']
        metadata['thumbnail'] = alb_info_pre.get('thumbnail', metadata['cover'])
    else:
        metadata['cover'] = await _process_cover(metadata, album_data.get("imageUrl"))
        metadata['thumbnail'] = metadata['cover']

    # --- Logika Kualitas ---
    user_id = user.get('user_id')
    preferred_quality_key = idagio_manager.get_user_quality(user_id)
    requested_api_quality = QUALITY_MAP_API[preferred_quality_key] # 90, 70, atau 50
    chosen_api_quality = 0
    if requested_api_quality == 90:
        chosen_api_quality = 90
    elif requested_api_quality == 70:
        chosen_api_quality = 70
    else:
        chosen_api_quality = 50
    if chosen_api_quality == 0:
        chosen_api_quality = 70 # Default fallback ke 320k

    metadata['quality'], metadata['extension'] = QUALITY_MAP_DISPLAY[chosen_api_quality]
    metadata['download_quality_tier'] = chosen_api_quality # 90, 70, 50
    metadata['download_track_id'] = download_track_id # ID unik untuk stream
    
    if not metadata['download_track_id']:
        raise IdagioError(f"Tidak dapat menemukan ID stream untuk track {track_id}")
    
    return metadata


async def process_album_metadata(album_id: str, r_id: str, user: dict):
    """Memproses metadata untuk satu album."""
    client = user['idagio_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    try:
        album_data = await asyncio.to_thread(client.get_album, album_id)
    except Exception as e:
        LOGGER.error(f"Idagio: Gagal mendapatkan metadata album {album_id}: {e}\n{traceback.format_exc()}")
        raise e

    # Coba temukan 'albumartist' (composer album)
    try:
        album_artist_obj = [c for c in album_data.get('participants') if c.get('type') == 'composer'][0]
        album_artist_name = album_artist_obj.get('name')
    except (IndexError, AttributeError):
        album_artist_name = "Various Artists"

    metadata['itemid'] = album_id
    metadata['title'] = album_data.get('title')
    metadata['album'] = album_data.get('title')
    metadata['artist'] = album_artist_name 
    metadata['albumartist'] = album_artist_name
    metadata['date'] = album_data.get('publishDate', '1900')[:4]
    metadata['totaltracks'] = str(len(album_data.get('tracks')))
    metadata['provider'] = 'Idagio'
    metadata['type'] = 'album'
    
    # --- PERBAIKAN: Logika default yang lebih kuat ---
    total_discs = album_data.get('discCount')
    metadata['totalvolumes'] = str(total_discs if total_discs else 1)
    metadata['explicit'] = False 
    # --- BATAS PERBAIKAN ---

    # Sampul
    metadata['cover'] = await _process_cover(metadata, album_data.get("imageUrl"))
    metadata['thumbnail'] = metadata['cover']
    
    # Simpan ke album_data agar dipakai oleh seluruh track tanpa download ulang
    album_data['cover'] = metadata['cover']
    album_data['thumbnail'] = metadata['thumbnail']

    metadata['tracks'] = []
    
    for i, track in enumerate(album_data.get('tracks')):
        try:
            recording_id = track.get('recording').get('id')
            
            track_meta = await process_track_metadata(
                recording_id, r_id, user, 
                pre_data=None, 
                alb_info_pre=album_data,
                track_num_pre=i + 1
            )

            track_meta['cover'] = metadata['cover'] 
            track_meta['thumbnail'] = metadata['thumbnail']
            metadata['tracks'].append(track_meta)
        except Exception as e:
            LOGGER.error(f"Idagio: Gagal memproses track {recording_id} di album: {e}\n{traceback.format_exc()}")
            continue

    if not metadata['tracks']:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk album {metadata['title']}")
    
    metadata['quality'] = metadata['tracks'][0]['quality']
    return metadata
