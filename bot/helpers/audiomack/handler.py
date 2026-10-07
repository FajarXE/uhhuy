# [GANTI SELURUH ISI FILE: bot/helpers/audiomack/handler.py]
import os
import asyncio
import hashlib
from PIL import Image
from bot.logger import LOGGER
from config import Config
from bot.helpers.utils import download_file, post_art_poster
from bot.helpers.metadata import set_metadata, create_cover_file
from bot.helpers.uploder import track_upload, album_upload

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
        'cover': track_data.get('trackImageUrl') or (album_meta.get('cover') if album_meta else ''),
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
        # --- [SOLUSI THUMBNAIL TRACK TUNGGAL] ---
        if metadata['cover'] and metadata['cover'].startswith('http'):
            metadata['cover'] = await create_cover_file(metadata['cover'], metadata)
            try:
                with Image.open(metadata['cover']) as img:
                    img = img.convert('RGB')
                    img.thumbnail((320, 320))
                    thumb_path = metadata['cover'] + "_thumb.jpg"
                    img.save(thumb_path, "JPEG")
                    metadata['thumbnail'] = thumb_path
            except Exception as e:
                LOGGER.error(f"Gagal membuat thumbnail: {e}")
        
        # Kirim Art Poster
        metadata['poster_msg'] = await post_art_poster(user, metadata)
        if not metadata['poster_msg']:
            metadata['poster_msg'] = user.get('bot_msg')
            
        await track_upload(metadata, user)
        
    return metadata

async def process_album(link: str, user: dict):
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
        'tempfolder': folder_path,
        'provider': 'Audiomack',
        'tracks': [],
        'poster_msg': None,
        'cover': album_data.get('albumImageUrl'),
        'quality': 'HQ'
    }
    
    # --- [SOLUSI POSTER & THUMBNAIL ALBUM] ---
    if album_meta['cover']:
        # 1. Unduh cover WebP secara lokal
        album_meta['cover'] = await create_cover_file(album_meta['cover'], album_meta)
        
        # 2. Paksa konversi ke JPEG 320x320 agar Telegram mau menampilkannya di file ZIP
        try:
            with Image.open(album_meta['cover']) as img:
                img = img.convert('RGB')
                img.thumbnail((320, 320))
                thumb_path = album_meta['cover'] + "_thumb.jpg"
                img.save(thumb_path, "JPEG")
                album_meta['thumbnail'] = thumb_path
        except Exception as e:
            LOGGER.error(f"Gagal memotong thumbnail Audiomack: {e}")

    # 3. Kirim pesan Art Poster ke Telegram SEBELUM lagu diproses
    album_meta['poster_msg'] = await post_art_poster(user, album_meta)
    
    # Fallback jika poster dinonaktifkan di /usetting
    if not album_meta['poster_msg']:
        album_meta['poster_msg'] = user.get('bot_msg')
    # -----------------------------------------
    
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
                meta = await process_track(link, user, track_info, album_meta)
                album_meta['tracks'].append(meta)
        except Exception as e:
            LOGGER.error(f"Gagal memproses lagu ke-{i} dari album Audiomack: {e}")
            
    if not album_meta['tracks']:
        raise Exception("Gagal mengekstrak dan mengunduh lagu apa pun dari album ini.")
        
    await album_upload(album_meta, user)
