# [GANTI SELURUH ISI FILE: bot/helpers/audiomack/handler.py]
import os
import asyncio
import hashlib
import shutil
import yt_dlp
from datetime import datetime
from PIL import Image
from bot.logger import LOGGER
from config import Config
import bot.helpers.translations as lang
from bot.helpers.utils import download_file, post_art_poster, format_string, run_concurrent_tasks
from bot.helpers.metadata import set_metadata, create_cover_file
from bot.helpers.uploder import track_upload, album_upload, playlist_upload

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

def _fix_date(date_str):
    """Format tanggal YYYYMMDD dari yt-dlp ke YYYY-MM-DD"""
    if not date_str: return ""
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return date_str

def _extract_info_sync(url, flat=False):
    """Fungsi ekstraktor yt-dlp (Dijalankan di thread terpisah agar asinkron)"""
    ydl_opts = {
        'quiet': True, 
        'no_warnings': True, 
        'extract_flat': flat
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)

async def start_audiomack(link: str, user: dict):
    if 'bot_msg' in user:
        import bot.helpers.ui_manager as ui_manager
        task_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
        async with ui_manager.GLOBAL_STATE_LOCK:
            if task_id in ui_manager.GLOBAL_TASKS:
                ui_manager.GLOBAL_TASKS[task_id]['processed'] = 'Membaca metadata (yt-dlp)...'

    # Menggunakan yt-dlp untuk menarik struktur URL dengan sangat cepat
    info = await asyncio.to_thread(_extract_info_sync, link, True)
    
    if info.get('_type') in ['playlist', 'multi_video']:
        await process_album(link, user, info)
    else:
        # Jika itu lagu tunggal (single), tarik info lengkapnya (beserta direct link audio)
        full_info = await asyncio.to_thread(_extract_info_sync, link, False)
        await process_track(link, user, full_info)

async def process_track(link: str, user: dict, track_data=None, album_meta=None, upload=True, track_num=1):
    if not track_data:
        track_data = await asyncio.to_thread(_extract_info_sync, link, False)
        
    title = track_data.get('title', 'Unknown Title')
    artist = track_data.get('uploader') or track_data.get('creator') or 'Unknown Artist'
    stream_url = track_data.get('url')
    
    if not stream_url:
        raise Exception(f"Streaming URL tersembunyi/tidak ditemukan untuk: {title}")
        
    ext = track_data.get('ext', 'mp3')
    if ext == 'unknown_video': ext = 'mp3'
    
    folder_name = f"{user['r_id']}/Audiomack"
    if album_meta:
        folder_name += f"/{album_meta['title']}"
        
    raw_date = track_data.get('release_date') or (album_meta.get('raw_date') if album_meta else '')
    fixed_date = _fix_date(raw_date)
    raw_year = fixed_date[:4] if fixed_date else str(datetime.now().year)
    
    metadata = {
        'title': title,
        'artist': artist,
        'album': album_meta['title'] if album_meta else track_data.get('album', title),
        'albumartist': album_meta['artist'] if album_meta else artist,
        'release_date': fixed_date,
        'date': raw_year,
        'genre': track_data.get('genre', '') or (album_meta.get('genre') if album_meta else ''),
        'producer': track_data.get('creator', ''),
        'duration': track_data.get('duration', 0), # yt-dlp mengembalikan integer detik
        'tracknumber': str(track_num).zfill(2),
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
    
    # Resolusi cover WebP dari yt-dlp
    cover_url = None
    if track_data.get('thumbnails'):
        cover_url = track_data['thumbnails'][-1].get('url')
    if not cover_url and album_meta:
        cover_url = album_meta.get('cover_url')
        
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
        track_info = await asyncio.to_thread(_extract_info_sync, link, False)
        if track_info:
            return await process_track(link, user, track_info, album_meta, upload=False, track_num=track_num)
    except Exception as e:
        LOGGER.error(f"Gagal memproses lagu ke-{track_num} dari Audiomack: {e}")
    return None

async def process_album(link: str, user: dict, playlist_info: dict):
    is_playlist = "/playlist/" in link.lower()
    
    entries = playlist_info.get('entries', [])
    total_tracks = len(entries)
    
    if total_tracks == 0:
        raise Exception("Tidak ada lagu yang ditemukan di tautan ini.")
        
    album_title = playlist_info.get('title', 'Unknown Album')
    album_artist = playlist_info.get('uploader') or playlist_info.get('creator') or 'Unknown Artist'
    
    folder_path = os.path.join(Config.DOWNLOAD_BASE_DIR, f"{user['r_id']}/Audiomack", album_title)
    
    raw_date = playlist_info.get('release_date', '')
    fixed_date = _fix_date(raw_date)
    raw_year = fixed_date[:4] if fixed_date else str(datetime.now().year)
    
    album_meta = {
        'type': 'playlist' if is_playlist else 'album',
        'title': album_title,
        'artist': album_artist,
        'release_date': fixed_date,
        'date': raw_year,
        'raw_date': raw_date,
        'genre': playlist_info.get('genre', ''),
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
    }
    
    thumbnails = playlist_info.get('thumbnails', [])
    album_meta['cover_url'] = thumbnails[-1].get('url') if thumbnails else ''
    album_meta['cover'] = await create_cover_file(album_meta['cover_url'], album_meta)
    
    if album_meta['cover'] and os.path.exists(album_meta['cover']):
        album_meta['cover'] = await asyncio.to_thread(_convert_to_jpeg, album_meta['cover'])
        os.makedirs(folder_path, exist_ok=True)
        try:
            shutil.copy2(album_meta['cover'], os.path.join(folder_path, "cover.jpg"))
        except Exception as e:
            LOGGER.error(f"Gagal menyalin cover ke folder album: {e}")
    
    album_meta['poster_msg'] = await post_art_poster(user, album_meta)
    if not album_meta['poster_msg']:
        album_meta['poster_msg'] = user.get('bot_msg')
    
    update_details = {'text': lang.s.DOWNLOAD_PROGRESS, 'msg': user['bot_msg'], 'title': album_meta['title'], 'type': album_meta['type']}
    
    tasks = []
    for i, entry in enumerate(entries, 1):
        track_url = entry.get('url') or entry.get('webpage_url')
        if track_url:
            # Memperbaiki relasi link
            if not track_url.startswith('http'):
                track_url = f"https://audiomack.com{track_url}" if track_url.startswith('/') else track_url
                
            tasks.append(_scrape_and_download(track_url, i, user, album_meta))
        
    # KARENA SEKARANG KITA MEMAKAI YT-DLP, KITA BISA MENGUNDUH SECARA PARALEL! (Maks: MAX_WORKERS)
    task_results = await run_concurrent_tasks(tasks, update_details, limit=Config.MAX_WORKERS)
    
    successful_tracks = [res for res in task_results if res]
    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)
            
    if not album_meta['tracks']:
        raise Exception("Gagal mengekstrak dan mengunduh lagu apa pun dari tautan ini.")
        
    if is_playlist:
        await playlist_upload(album_meta, user)
    else:
        await album_upload(album_meta, user)
