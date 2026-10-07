# [BUAT FILE: bot/helpers/audiomack/handler.py]
import os
import asyncio
from bot.logger import LOGGER
from config import Config
from bot.helpers.utils import download_file
from bot.helpers.metadata import set_metadata, create_cover_file
from bot.helpers.uploder import track_upload, album_upload
import hashlib

from .api import AudiomackAPI

api = AudiomackAPI()

async def start_audiomack(link: str, user: dict):
    if "/album/" in link.lower():
        await process_album(link, user)
    else:
        await process_track(link, user)

async def process_track(link: str, user: dict, track_data=None, album_meta=None):
    if not track_data:
        import bot.helpers.ui_manager as ui_manager
        if 'bot_msg' in user:
            task_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
            async with ui_manager.GLOBAL_STATE_LOCK:
                if task_id in ui_manager.GLOBAL_TASKS:
                    ui_manager.GLOBAL_TASKS[task_id]['processed'] = 'Scraping Audiomack... (Membuka Web)'
        
        track_data = await api.get_song(link)
        
    title = track_data.get('title', 'Unknown Title')
    artist = track_data.get('artist', 'Unknown Artist')
    stream_url = track_data.get('streamingUrl')
    
    if not stream_url:
        raise Exception(f"Streaming URL tersembunyi/tidak ditemukan untuk: {title}")
        
    ext = 'm4a' if '.m4a' in stream_url else 'mp3'
    
    folder_name = f"{user['r_id']}/Audiomack"
    if album_meta:
        folder_name += f"/{album_meta['albumTitle']}"
        
    file_name = f"{artist} - {title}.{ext}".replace("/", "_")
    filepath = os.path.join(Config.DOWNLOAD_BASE_DIR, folder_name, file_name)
    
    metadata = {
        'title': title,
        'artist': artist,
        'album': album_meta['albumTitle'] if album_meta else title,
        'albumartist': album_meta['albumArtist'] if album_meta else artist,
        'cover': track_data.get('trackImageUrl') or (album_meta.get('albumImageUrl') if album_meta else ''),
        'release_date': track_data.get('releaseDate') or (album_meta.get('albumReleaseDate') if album_meta else ''),
        'date': track_data.get('year') or (album_meta.get('albumYear') if album_meta else ''),
        'genre': track_data.get('genre') or (album_meta.get('albumGenre') if album_meta else ''),
        'producer': track_data.get('producer', ''),
        'duration': track_data.get('duration', '0:00'),
        'tracknumber': str(track_data.get('trackNumber', 1)),
        'totaltracks': str(album_meta['albumTotalTracks']) if album_meta else '1',
        'filepath': filepath,
        'provider': 'Audiomack',
        'type': 'track',
        'quality': 'HQ'
    }
    
    details = {'msg': user.get('bot_msg'), 'title': title, 'type': 'Track', 'action': 'Download'}
    err = await download_file(stream_url, filepath, details=details)
    if err:
        raise Exception(f"Gagal mengunduh stream Aria2: {err}")
    
    await set_metadata(metadata, user['user_id'])
    
    if not album_meta:
        await track_upload(metadata, user)
        
    return metadata

async def process_album(link: str, user: dict):
    # Mengambil kerangka informasi album
    album_data = await api.get_album(link)
    total_tracks = album_data.get('albumTotalTracks', 0)
    
    if total_tracks == 0:
        raise Exception("Tidak ada lagu yang ditemukan di album ini.")
        
    folder_path = os.path.join(Config.DOWNLOAD_BASE_DIR, f"{user['r_id']}/Audiomack", album_data['albumTitle'])
    
    album_meta = {
        'type': 'album',
        'title': album_data['albumTitle'],
        'artist': album_data['albumArtist'],
        'folderpath': folder_path,
        'tempfolder': folder_path,  # <-- TAMBAHKAN BARIS INI
        'provider': 'Audiomack',
        'tracks': [],
        'poster_msg': user.get('bot_msg'),
        'cover': album_data.get('albumImageUrl'),
        'quality': 'HQ'
    }
    
    # --- [TAMBAHKAN BLOK INI] ---
    # Mengunduh cover album secara lokal agar tidak crash saat diunggah
    if album_meta['cover']:
        album_meta['cover'] = await create_cover_file(album_meta['cover'], album_meta)
    # ----------------------------
    
    # KARENA RENDER/NORTHFLANK RAWAN OOM (RAM PENUH), KITA EKSEKUSI SCRAPER SATU PER SATU
    for i in range(1, total_tracks + 1):
        try:
            import bot.helpers.ui_manager as ui_manager
            if 'bot_msg' in user:
                task_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
                async with ui_manager.GLOBAL_STATE_LOCK:
                    if task_id in ui_manager.GLOBAL_TASKS:
                        ui_manager.GLOBAL_TASKS[task_id]['processed'] = f'Scraping Track {i}/{total_tracks}...'
                        
            track_data_resp = await api.get_album(link, track=i)
            track_info = track_data_resp.get('track')
            if track_info:
                meta = await process_track(link, user, track_info, album_data)
                album_meta['tracks'].append(meta)
        except Exception as e:
            LOGGER.error(f"Gagal memproses lagu ke-{i} dari album Audiomack: {e}")
            
    if not album_meta['tracks']:
        raise Exception("Gagal mengekstrak dan mengunduh lagu apa pun dari album ini.")
        
    await album_upload(album_meta, user)
