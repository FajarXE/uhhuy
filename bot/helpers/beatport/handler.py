# [GANTI SELURUH FILE: bot/helpers/beatport/handler.py]

import os
import shutil 
import traceback
import asyncio 
import random 

from pathvalidate import sanitize_filepath
from config import Config

from .metadata import (
    process_track_metadata, 
    process_album_metadata, 
    process_playlist_metadata,
    custom_url_parse,
    write_extended_tags 
)

from .api import BeatportError, APP_USER_AGENT 
from .manager import beatport_manager

from ..utils import *

try:
    from ..uploder import *
except ImportError as e:
    raise ImportError(f"Gagal mengimpor uploder.py: {e}")

from ..metadata import set_metadata
from ..message import edit_message
from ..utils import fetch_zip_settings, run_concurrent_tasks, download_file, post_art_poster, zip_handler, format_string
from ...settings import bot_set 

import bot.helpers.translations as lang
from bot.logger import LOGGER

async def refresh_track_url(item_id: str, current_meta: dict, user_id: int):
    try:
        pref_qual = current_meta.get('quality', 'High').lower()
        if pref_qual not in ['lossless', 'high', 'medium']:
            pref_qual = beatport_manager.get_user_quality(user_id)

        quality_priority = ["medium"]
        if pref_qual == "lossless": quality_priority = ["lossless", "high", "medium"]
        elif pref_qual == "high": quality_priority = ["high", "medium"]

        LOGGER.info(f"Beatport: Refreshing URL for {item_id} ({pref_qual})...")
        client = beatport_manager.get_client(user_id)
        if not client: return None, None
            
        for qual in quality_priority:
            try:
                q_map = {"lossless": "lossless", "high": "high", "medium": "medium"}
                stream_data = await client.get_track_download(item_id, q_map[qual])
                new_url = stream_data.get("location")
                if new_url: return new_url, qual 
            except: continue
        return None, None
    except Exception as e:
        LOGGER.error(f"Gagal refresh URL Beatport {item_id}: {e}")
        return None, None

async def start_beatport(url: str, user: dict):
    try:
        media_type, item_id, extra_kwargs = custom_url_parse(url)
        if media_type == 'artist': raise NotImplementedError("Unduhan Artis Beatport belum didukung.")
        elif media_type == 'track':
            success = await start_track(item_id, user, None)
            if not success: raise Exception("Gagal mengunduh track.")
        elif media_type == 'album': await start_album(item_id, user)
        elif media_type == 'playlist': await start_playlist(item_id, user, extra_kwargs)
    except Exception as e:
        LOGGER.error(f"Error Beatport handler: {e}")
        raise e 

# --- KINI MENGGUNAKAN FULL ARIA2 ENGINE ---
async def start_track(item_id: str, user: dict, track_meta: dict | None, upload=True, filepath=None, disable_link=False):
    user_id = user.get('user_id')
    client = beatport_manager.get_client(user_id)
    
    if not track_meta:
        try: track_meta = await process_track_metadata(item_id, user['r_id'], user, fetch_stream=True)
        except Exception as e:
            LOGGER.warning(f"Beatport track {item_id} error: {e}")
            return False
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)

    try:
        if client and random.random() < 0.7:
            await asyncio.sleep(random.uniform(0.5, 1.5))
    except Exception: pass 

    if not track_meta.get('download_url'):
        new_url, qual = await refresh_track_url(item_id, track_meta, user_id)
        if new_url:
            track_meta['download_url'] = new_url
            if qual:
                track_meta['quality'] = qual.capitalize()
                track_meta['extension'] = 'flac' if qual == 'lossless' else 'm4a'
        else: return False

    track_meta['folderpath'] = filepath
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    filepath += f"/{sanitize_filepath(raw_filename)}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    # Penyamaran Aria2 agar tidak terkena 403 Forbidden dari server Beatport
    headers_dict = {"User-Agent": APP_USER_AGENT, "Accept": "*/*", "Referer": "https://www.beatport.com/"}
    details_aria = {'msg': None, 'headers': headers_dict} if not upload else {
        'msg': user['bot_msg'], 'title': track_meta.get('title'), 'type': 'Track', 'headers': headers_dict
    }

    if os.path.exists(filepath): os.remove(filepath)
    
    # 1. Sedot langsung pakai Aria2!
    err = await download_file(track_meta['download_url'], filepath, retries=1, details=details_aria)
    
    # 2. Jika gagal/403 (biasanya karena link kedaluwarsa), refresh link dan hajar lagi!
    if err or not os.path.exists(filepath) or os.path.getsize(filepath) < 10000:
        LOGGER.warning(f"Beatport: Aria2 gagal/403 untuk {track_meta['title']}. Menyegarkan URL...")
        new_url, qual = await refresh_track_url(item_id, track_meta, user_id)
        if new_url:
            track_meta['download_url'] = new_url
            if qual and qual != track_meta['quality'].lower():
                 new_ext = 'flac' if qual == 'lossless' else 'm4a'
                 if new_ext != track_meta['extension']:
                     filepath = filepath.rsplit('.', 1)[0] + f".{new_ext}"
                     track_meta['filepath'] = filepath
                     track_meta['extension'] = new_ext
            
            if os.path.exists(filepath): os.remove(filepath)
            err = await download_file(new_url, filepath, retries=1, details=details_aria)

    if err or not os.path.exists(filepath) or os.path.getsize(filepath) < 10000:
        LOGGER.error(f"Gagal mengunduh track {track_meta['title']}")
        return False

    try:
        await set_metadata(track_meta, user['user_id'])
        await write_extended_tags(track_meta['filepath'], track_meta)
    except Exception as e:
        LOGGER.warning(f"Gagal set metadata: {e}")
        try: os.remove(filepath)
        except: pass
        return False

    if upload: await track_upload(track_meta, user, disable_link)
    
    # Return dictionary metadata agar bisa ditangkap oleh run_concurrent_tasks
    return track_meta

async def start_album(album_id: str, user: dict, upload=True):
    try: album_meta = await process_album_metadata(album_id, user['r_id'], user)
    except Exception as e: raise Exception(f"Gagal metadata album Beatport: {e}")

    album_folder = sanitize_filepath(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}")
    album_meta['folderpath'] = album_folder

    if upload: album_meta['poster_msg'] = await post_art_poster(user, album_meta)
    
    # --- [FIX] PARALEL MAX_WORKERS ---
    tasks = []
    for track in album_meta['tracks']:
        tasks.append(start_track(track['itemid'], user, track, False, album_folder))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'], 
        'title': album_meta['title'], 
        'type': album_meta['type']
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details, limit=Config.MAX_WORKERS)
    successful_tracks = [res for res in task_results if isinstance(res, dict) and res.get('filepath')]
    # ---------------------------------

    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)
    if not successful_tracks: raise Exception("Tidak ada lagu yang berhasil diunduh.")

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    if album_zip: 
        try:
            cover_src = album_meta.get('cover')
            if cover_src:
                target = os.path.join(album_meta['folderpath'], "cover.jpg")
                if os.path.exists(cover_src): shutil.copy(cover_src, target)
                elif cover_src.startswith('http'):
                    # Biarkan Aria2 yang mengunduh gambarnya juga
                    details_aria = {'msg': None}
                    await download_file(cover_src, target, retries=1, details=details_aria)
        except: pass
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])

    if upload: 
        await album_upload(album_meta, user)

async def start_playlist(playlist_id: str, user: dict, extra: dict, upload=True):
    try: play_meta = await process_playlist_metadata(playlist_id, user['r_id'], user, extra)
    except Exception as e: raise Exception(f"Gagal metadata playlist Beatport: {e}")

    playlist_folder = sanitize_filepath(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{play_meta['provider']}/{play_meta['title']}")
    play_meta['folderpath'] = playlist_folder

    if upload: play_meta['poster_msg'] = await post_art_poster(user, play_meta)

    # --- [FIX] PARALEL MAX_WORKERS ---
    tasks = []
    for track in play_meta['tracks']:
        tasks.append(start_track(track['itemid'], user, track, False, playlist_folder))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'], 
        'title': play_meta['title'], 
        'type': play_meta['type']
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details, limit=Config.MAX_WORKERS)
    successful_tracks = [res for res in task_results if isinstance(res, dict) and res.get('filepath')]
    # ---------------------------------

    play_meta['tracks'] = successful_tracks
    play_meta['totaltracks'] = len(successful_tracks)
    if not successful_tracks: raise Exception("Tidak ada lagu yang berhasil diunduh.")

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    if playlist_zip: 
        try:
            cover_src = play_meta.get('cover')
            if cover_src:
                target = os.path.join(play_meta['folderpath'], "cover.jpg")
                if os.path.exists(cover_src): shutil.copy(cover_src, target)
                elif cover_src.startswith('http'):
                    # Biarkan Aria2 yang mengunduh gambarnya juga
                    details_aria = {'msg': None}
                    await download_file(cover_src, target, retries=1, details=details_aria)
        except: pass
        play_meta['zip_path'] = await zip_handler(play_meta['folderpath'])

    if upload: 
        await playlist_upload(play_meta, user)
