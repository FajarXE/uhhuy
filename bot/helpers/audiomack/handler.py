# [GANTI SELURUH ISI FILE: bot/helpers/audiomack/handler.py]
import os
import asyncio
import hashlib
import shutil
import re
from datetime import datetime
from PIL import Image
from bot.logger import LOGGER
from config import Config
import bot.helpers.translations as lang
from bot.helpers.utils import download_file, post_art_poster, format_string, run_concurrent_tasks
from bot.helpers.metadata import set_metadata, create_cover_file
from bot.helpers.uploder import track_upload, album_upload, playlist_upload

from .api import AudiomackAPI

api = AudiomackAPI()

def _convert_to_jpeg(img_path):
    """Konversi gambar WebP ke JPEG agar didukung penuh oleh Telegram"""
    try:
        with Image.open(img_path) as img:
            if img.format != 'JPEG':
                rgb_im = img.convert('RGB')
                new_path = img_path + "_converted.jpg"
                rgb_im.save(new_path, "JPEG")
                return new_path
    except Exception as e:
        LOGGER.error(f"Gagal konversi gambar: {e}")
    return img_path

def _fix_date(date_str, year_str):
    """Ubah format tanggal bahasa Inggris ke format standar YYYY-MM-DD"""
    if not date_str: return ""
    
    if re.match(r"^\d{4}-\d{2}-\d{2}", date_str):
        return date_str[:10]
    
    clean_date = re.sub(r'(?<=\d)(st|nd|rd|th)', '', date_str)
    
    if not year_str:
        year_str = str(datetime.now().year)
        
    try:
        dt = datetime.strptime(f"{clean_date.strip()} {year_str.strip()}", "%B %d %Y")
        return dt.strftime("%Y-%m-%d")
    except Exception as e:
        LOGGER.debug(f"Gagal parsing tanggal Audiomack: {e}")
        return date_str

async def start_audiomack(link: str, user: dict):
    if "/album/" in link.lower() or "/playlist/" in link.lower():
        await process_album(link, user)
    else:
        await process_track(link, user)

async def process_track(link: str, user: dict, track_data=None, album_meta=None, upload=True):
    if not track_data:
        track_data = await api.get_song(link)
        
    title = track_data.get('title', 'Unknown Title')
    artist = track_data.get('artist', 'Unknown Artist')
    stream_url = track_data.get('streamingUrl')
    
    if not stream_url:
        raise Exception(f"Streaming URL tersembunyi/tidak ditemukan untuk: {title}")
        
    ext = 'm4a' if '.m4a' in stream_url else 'mp3'
    
    folder_name = f"{user['r_id']}/Audiomack"
    if album_meta:
        folder_name += f"/{album_meta['title']}"
        
    raw_date = track_data.get('releaseDate') or (album_meta.get('release_date') if album_meta else '')
    raw_year = track_data.get('year') or (album_meta.get('date') if album_meta else '')
    fixed_date = _fix_date(raw_date, raw_year)
    
    metadata = {
        'title': title,
        'artist': artist,
        'album': album_meta['title'] if album_meta else title,
        'albumartist': album_meta['artist'] if album_meta else artist,
        'release_date': fixed_date,
        'date': raw_year,
        'genre': track_data.get('genre') or (album_meta.get('genre') if album_meta else ''),
        'producer': track_data.get('producer', ''),
        'duration': track_data.get('duration', '0:00'),
        'tracknumber': str(track_data.get('trackNumber', 1)).zfill(2),
        'totaltracks': str(album_meta.get('totaltracks', 1)) if album_meta else '1',
        'totalvolume': str(album_meta.get('totalvolume', 1)) if album_meta else '1',
        'volume': '1',
        'explicit': 'False',
        'provider': 'Audiomack',
        'type': 'track',
        'quality': 'HQ',
        'extension': ext,
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/"
    }
    
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, metadata, user)
    raw_filename = raw_filename.replace("/", "_")
    file_name = f"{raw_filename}.{ext}"
    
    filepath = os.path.join(Config.DOWNLOAD_BASE_DIR, folder_name, file_name)
    metadata['filepath'] = filepath
    
    cover_url = track_data.get('trackImageUrl') or (album_meta.get('cover_url') if album_meta else '')
    metadata['cover'] = await create_cover_file(cover_url, metadata)
    
    if metadata['cover'] and os.path.exists(metadata['cover']):
        metadata['cover'] = await asyncio.to_thread(_convert_to_jpeg, metadata['cover'])
    
    details = {'msg': user.get('bot_msg'), 'title': title, 'type': 'Track', 'action': 'Download'}
    err = await download_file(stream_url, filepath, details=details)
    if err:
        raise Exception(f"Gagal mengunduh stream Aria2: {err}")
    
    await set_metadata(metadata, user['user_id'])
    
    if upload and not album_meta:
        await track_upload(metadata, user)
        
    return metadata

async def _scrape_and_download(link, track_num, user, album_meta):
    try:
        track_data_resp = await api.get_album(link, track=track_num)
        track_info = track_data_resp.get('track')
        if track_info:
            return await process_track(link, user, track_info, album_meta, upload=False)
    except Exception as e:
        LOGGER.error(f"Gagal memproses lagu ke-{track_num} dari album/playlist Audiomack: {e}")
    return None

async def process_album(link: str, user: dict):
    is_playlist = "/playlist/" in link.lower()
    
    import bot.helpers.ui_manager as ui_manager
    if 'bot_msg' in user:
        task_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
        async with ui_manager.GLOBAL_STATE_LOCK:
            if task_id in ui_manager.GLOBAL_TASKS:
                ui_manager.GLOBAL_TASKS[task_id]['processed'] = 'Menggulir halaman untuk memuat playlist...'
                
    album_data = await api.get_album(link)
    total_tracks = album_data.get('albumTotalTracks', 0)
    
    if total_tracks == 0:
        raise Exception("Tidak ada lagu yang ditemukan di tautan ini.")
        
    folder_path = os.path.join(Config.DOWNLOAD_BASE_DIR, f"{user['r_id']}/Audiomack", album_data['albumTitle'])
    
    raw_date = album_data.get('albumReleaseDate', '')
    raw_year = album_data.get('albumYear', '')
    fixed_date = _fix_date(raw_date, raw_year)
    
    album_meta = {
        'type': 'playlist' if is_playlist else 'album',
        'title': album_data['albumTitle'],
        'artist': album_data['albumArtist'],
        'release_date': fixed_date,
        'date': raw_year,
        'genre': album_data.get('albumGenre', ''),
        'totaltracks': total_tracks,
        'totalvolume': '1',
        'volume': '1',
        'explicit': 'False',
        'folderpath': folder_path,
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/",
        'provider': 'Audiomack',
        'tracks': [],
        'poster_msg': None,
        'quality': 'HQ',
        'cover_url': album_data.get('albumImageUrl')
    }
    
    album_meta['cover'] = await create_cover_file(album_meta['cover_url'], album_meta)
    
    if album_meta['cover'] and os.path.exists(album_meta['cover']):
        album_meta['cover'] = await asyncio.to_thread(_convert_to_jpeg, album_meta['cover'])
        
        os.makedirs(folder_path, exist_ok=True)
        try:
            shutil.copy2(album_meta['cover'], os.path.join(folder_path, "cover.jpg"))
        except Exception as e:
            LOGGER.error(f"Gagal menyalin cover ke folder: {e}")
    
    album_meta['poster_msg'] = await post_art_poster(user, album_meta)
    if not album_meta['poster_msg']:
        album_meta['poster_msg'] = user.get('bot_msg')
    
    update_details = {'text': lang.s.DOWNLOAD_PROGRESS, 'msg': user['bot_msg'], 'title': album_meta['title'], 'type': album_meta['type']}
    
    tasks = []
    for i in range(1, total_tracks + 1):
        tasks.append(_scrape_and_download(link, i, user, album_meta))
        
    # Menggunakan antrean resmi (run_concurrent_tasks) dengan limit=1 agar 
    # tampilannya 100% konsisten dan tidak membebani server
    task_results = await run_concurrent_tasks(tasks, update_details, limit=1)
    
    successful_tracks = [res for res in task_results if res]
    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)
            
    if not album_meta['tracks']:
        raise Exception("Gagal mengekstrak dan mengunduh lagu apa pun dari tautan ini.")
        
    if is_playlist:
        await playlist_upload(album_meta, user)
    else:
        await album_upload(album_meta, user)
