# [GANTI SELURUH FILE: bot/helpers/highresaudio/metadata.py]

import copy
import re
import asyncio
import traceback 
from config import Config 

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .manager import highresaudio_manager, HighResAudioError
from bot.logger import LOGGER

def custom_url_parse(link: str):
    pattern = r"https://(?:www\.)?highresaudio\.com/[a-z]{2}/album/view/(\w+)/.*"
    match = re.match(pattern, link)
    if match:
        return 'album', link, {}
    else:
        raise HighResAudioError('URL HighResAudio tidak valid atau tidak didukung.')

async def _process_cover(metadata: dict, url: str):
    if not url:
        return metadata['tempfolder'] + "cover.jpg"
    return await create_cover_file(url, metadata)

async def process_album_metadata(album_url: str, r_id: str, user: dict):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    # [MODIFIKASI] Ambil Client via Manager (User Specific / Global)
    user_id = user.get('user_id')
    client = highresaudio_manager.get_client(user_id)
    
    if not client:
        raise HighResAudioError("Tidak ada akun HighResAudio yang tersedia (Login akun sendiri atau hubungi admin).")

    api_data = None
    album_id = None
    
    try:
        # LANGKAH 1: Scrape ID
        LOGGER.debug(f"HighResAudio: Scraping ID dari {album_url}...")
        album_id = await asyncio.to_thread(client.get_album_id_from_url, album_url)

        # LANGKAH 2: API Metadata
        api_data = await asyncio.to_thread(client.get_album_metadata, album_id)
        
        data = api_data.get('data', {}).get('results', {})
        if not data:
            raise HighResAudioError("Data metadata kosong dari API.")
            
    except Exception as e:
        raise HighResAudioError(f"Gagal mengambil metadata album: {e}")

    # --- Mapping Metadata ---
    metadata['itemid'] = album_id
    metadata['title'] = data.get('title')
    metadata['album'] = data.get('title')
    metadata['artist'] = data.get('artist')
    metadata['albumartist'] = data.get('artist')
    metadata['provider'] = 'HighResAudio'
    metadata['type'] = 'album'
    
    track_list = data.get('tracks', [])
    metadata['totaltracks'] = str(len(track_list))
    
    release_date_raw = data.get('releaseDate', '') 
    if 'T' in release_date_raw:
        metadata['release_date'] = release_date_raw.split('T')[0]
    else:
        metadata['release_date'] = release_date_raw.split(' ')[0] if release_date_raw else ''

    metadata['date'] = str(data.get('productionYear', '')) 
    metadata['totalvolumes'] = str(data.get('discCount', 1))
    metadata['explicit'] = bool(data.get('explicit', False))
    metadata['genre'] = data.get('genre', '') 
    metadata['subgenre'] = data.get('subgenre', '') 
    metadata['composer'] = data.get('composer', '')
    metadata['publisher'] = data.get('label', '')
    metadata['upc'] = data.get('upc') or data.get('ean', '')

    cover_url_str = None
    try:
        cover_data = data.get('cover') 
        if isinstance(cover_data, dict):
            file_url = cover_data.get('master', {}).get('file_url')
            if file_url: cover_url_str = f"https://{file_url}"
        elif isinstance(cover_data, str):
            cover_url_str = cover_data
    except: pass 

    metadata['cover'] = await _process_cover(metadata, cover_url_str)
    metadata['thumbnail'] = metadata['cover']

    metadata['tracks'] = []
    for track in track_list:
        try:
            track_meta = copy.deepcopy(base_meta)
            track_meta['tempfolder'] = metadata['tempfolder']
            
            track_meta['title'] = track.get('title')
            track_meta['album'] = metadata['album']
            track_meta['artist'] = metadata['artist']
            track_meta['albumartist'] = metadata['albumartist']
            track_meta['provider'] = 'HighResAudio'
            track_meta['type'] = 'track'
            track_meta['cover'] = metadata['cover']
            track_meta['thumbnail'] = metadata['thumbnail']
            
            track_meta['date'] = metadata['date'] 
            track_meta['release_date'] = metadata['release_date'] 
            track_meta['explicit'] = metadata['explicit']
            track_meta['genre'] = metadata['genre']
            track_meta['subgenre'] = metadata['subgenre']
            track_meta['composer'] = metadata['composer']
            track_meta['publisher'] = metadata['publisher']
            track_meta['upc'] = metadata['upc']

            track_meta['itemid'] = track.get('id') 
            track_meta['tracknumber'] = str(track.get('trackNumber')).zfill(2)
            track_meta['totaltracks'] = metadata['totaltracks']
            track_meta['isrc'] = track.get('isrc')
            track_meta['discnumber'] = str(track.get('discNumber', 1))
            track_meta['totalvolumes'] = metadata['totalvolumes']

            track_meta['quality'] = f"{track.get('format')} kHz FLAC"
            track_meta['extension'] = 'flac'
            
            raw_url = track.get('url')
            if raw_url:
                new_url = raw_url.replace('cdn.highresaudio.com', 'streaming.highresaudio.com')
                # Perbaikan URL replace agar lebih aman
                new_url = new_url.replace('highresaudio.com//', 'highresaudio.com/')
                track_meta['download_url'] = new_url
            else:
                track_meta['download_url'] = None

            track_meta['album_id_referer'] = album_id 

            if not track_meta['download_url']:
                LOGGER.warning(f"Tidak ada URL unduhan untuk track {track_meta['title']}")
                continue

            metadata['tracks'].append(track_meta)
            
        except Exception as e:
            LOGGER.error(f"Skip track HRA: {e}")
            continue

    if "booklet" in data and data['booklet']:
        booklet_url = data['booklet']
        if not booklet_url.startswith('http'):
            booklet_url = f"https://{booklet_url}"
        metadata['booklet_url'] = booklet_url

    if not metadata['tracks']:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk album {metadata['title']}")
    
    metadata['quality'] = metadata['tracks'][0]['quality']
    return metadata
