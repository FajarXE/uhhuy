# [GANTI FILE: bot/helpers/deezer/handler.py]

from pathvalidate import sanitize_filepath
from config import Config
import hashlib
import asyncio
import os 
import shutil

from .metadata import *
from .manager import DeezerError

from ..utils import *
from ..uploder import *
from ..metadata import set_metadata

from ...settings import bot_set
import bot.helpers.translations as lang

from bot.logger import LOGGER 
from ..utils import fetch_zip_settings 
from ..message import edit_message


async def start_deezer(url: str, user: dict):
    deezerapi = user.get('deezer_api')
    if not deezerapi:
        raise DeezerError("Sesi login Deezer tidak ditemukan.") 
    
    media_type, item_id = await deezerapi.custom_url_parse(url)

    if media_type == 'artist':
        await start_artist(item_id, user)
    elif media_type == 'track':
        success = await start_track(item_id, user, None)
        if not success:
            raise DeezerError("Track not available in this Deezer account.")
    elif media_type == 'album':
        await start_album(item_id, user)
    elif media_type == 'playlist':
        await start_playlist(item_id, user)


async def start_track(item_id: int, user: dict, track_meta: dict | None, upload=True, filepath=None, disable_link=False):
    deezerapi = user['deezer_api']
    is_single_track = track_meta is None

    if is_single_track:
        try:
            track_meta = await process_track_metadata(item_id, user['r_id'], user=user)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            LOGGER.warning(f"Deezer track {item_id} tidak tersedia: {e}")
            raise DeezerError(f"Track not available: {e}")
            
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)

    try:
        url = await deezerapi.get_track_url(item_id, track_meta['token'], track_meta['token_expiry'], track_meta['quality'])
    except asyncio.CancelledError:
        raise
    except Exception as e:
        LOGGER.warning(f"Gagal mendapatkan URL Deezer (Track {item_id}): {e}")
        if is_single_track:
            raise DeezerError(f"Track not available: {e}")
        return False

    # Jika berasal dari playlist (cover ditunda), unduh cover sekarang secara paralel (dengan cache)
    if not track_meta.get('cover'):
        try:
            await resolve_deezer_track_cover(track_meta, user)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            LOGGER.debug(f"Gagal memuat cover untuk track {item_id}: {e}")

    # --- LOGIKA FOLDER CD UNTUK MULTI-DISC ALBUM ---
    try:
        total_vol = int(track_meta.get('totalvolume', 1))
        if total_vol > 1:
            vol_num = track_meta.get('volume', '1')
            filepath = f"{filepath}/CD {vol_num}"
    except Exception:
        pass
    # -----------------------------------------------

    track_meta['folderpath'] = filepath
    raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
    safe_filename = sanitize_filepath(raw_filename)

    track_meta['extension'] = 'flac' if track_meta['quality'] in ['FLAC', 'FLAC_24'] else 'mp3'
    filepath += f"/{safe_filename}.{track_meta['extension']}"
    track_meta['filepath'] = filepath

    details = None
    if upload and user.get('bot_msg'):
        task_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
        details = {
            'msg': user['bot_msg'],
            'title': track_meta.get('title', 'Unknown'),
            'type': track_meta.get('type', 'Track').capitalize(),
            'action': 'Download',
            'task_id': task_id
        }

    err = await deezerapi.dl_track(item_id, url, track_meta['filepath'], details=details)
    if err:
        LOGGER.error(f"Deezer dl_track gagal: {err}")
        return False

    if not os.path.exists(track_meta['filepath']) or os.path.getsize(track_meta['filepath']) == 0: 
        LOGGER.warning("Deezer: File gagal diunduh atau kosong!")
        try:
            os.remove(track_meta['filepath'])
        except OSError:
            pass
        return False

    is_valid_header = False
    try:
        with open(track_meta['filepath'], 'rb') as f:
            header = f.read(16)
            if track_meta['extension'] == 'flac':
                if header.startswith(b'fLaC') or header.startswith(b'ID3'):
                    is_valid_header = True
                elif len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0:
                    # Server Deezer melakukan fallback otomatis ke MP3 karena FLAC tidak tersedia untuk track ini
                    track_meta['extension'] = 'mp3'
                    track_meta['quality'] = 'MP3_320'
                    new_mp3_path = os.path.splitext(track_meta['filepath'])[0] + '.mp3'
                    os.replace(track_meta['filepath'], new_mp3_path)
                    track_meta['filepath'] = new_mp3_path
                    is_valid_header = True
            else: 
                if header.startswith(b'ID3') or (len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0):
                    is_valid_header = True
    except Exception as e:
        LOGGER.warning(f"Gagal membaca header file: {e}")

    if not is_valid_header:
        LOGGER.warning("Deezer: File korup. Menghapus...")
        try:
            os.remove(track_meta['filepath'])
        except OSError:
            pass
        return False

    try:
        await set_metadata(track_meta, user['user_id'])
    except asyncio.CancelledError:
        raise
    except Exception as e:
        LOGGER.warning(f"Deezer: Metadata gagal ({e}).")
        try:
            os.remove(track_meta['filepath'])
        except OSError:
            pass
        return False

    if upload:
        await track_upload(track_meta, user, disable_link)

    return True


async def start_album(album_id: int, user: dict, upload=True, basefolder=None): 
    deezerapi = user['deezer_api']

    try:
        album_metadata_dict = await deezerapi.get_album(album_id)
        tracklist_raw_data = await deezerapi.get_album_tracks(album_id)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        raise DeezerError(f"Gagal mendapatkan metadata album Deezer: {e}")

    songs_dict = tracklist_raw_data.get('SONGS') if isinstance(tracklist_raw_data, dict) else None

    if not songs_dict or not songs_dict.get('data'):
        album_title = album_metadata_dict.get('ALB_TITLE', f'(ID: {album_id})') if isinstance(album_metadata_dict, dict) else f'(ID: {album_id})'
        raise DeezerError(f"Album '{album_title}' tidak tersedia atau tidak memiliki daftar lagu.")
    
    album_meta = await process_album_metadata(album_id, album_metadata_dict, songs_dict, user['r_id'], user=user)
    
    if basefolder:
        album_folder = basefolder + f"/{album_meta['title']}"
    else:
        album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder
    os.makedirs(album_folder, exist_ok=True)

    if upload:
        poster_key = f'poster_album_{album_id}'
        existing_poster = user.get(poster_key)
        
        if existing_poster:
            album_meta['poster_msg'] = existing_poster
        else:
            album_meta['poster_msg'] = await post_art_poster(user, album_meta)
            user[poster_key] = album_meta['poster_msg']

    tasks = []
    for track in album_meta['tracks']:
        tasks.append(start_track(track['itemid'], user, track, False, album_folder))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user.get('bot_msg'),
        'title': album_meta['title'],
        'type': album_meta['type']
    }
    
    task_results = await run_concurrent_tasks(tasks, update_details, limit=Config.MAX_WORKERS)

    original_tracks = album_meta['tracks']
    successful_tracks = []
    
    for i in range(len(original_tracks)):
        if i < len(task_results) and task_results[i] is True:
            successful_tracks.append(original_tracks[i])
        else:
            LOGGER.info(f"Melewatkan track Deezer {original_tracks[i].get('title', 'N/A')} karena gagal diunduh.")

    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks:
        raise DeezerError(f"Tidak ada lagu Deezer yang berhasil diunduh (Track not available) untuk album {album_meta['title']}.")

    if album_meta.get('cover') and os.path.exists(album_meta['cover']):
        try:
            cover_dest = os.path.join(album_meta['folderpath'], "cover.jpg")
            shutil.copy(album_meta['cover'], cover_dest)
        except Exception as e:
            LOGGER.warning(f"Gagal menyalin cover.jpg ke folder album: {e}")

    if upload:
        await album_upload(album_meta, user)

    return album_meta


async def start_artist(artist_id, user):
    deezerapi = user['deezer_api']
    
    try:
        artist_data = await deezerapi.get_artist(artist_id)
        artist_meta = await process_artist_metadata(artist_data, user['r_id'])
    except asyncio.CancelledError:
        raise
    except Exception as e:
        raise DeezerError(f"Gagal mendapatkan metadata artist Deezer: {e}")

    album_ids = await deezerapi.get_artist_album_ids(artist_id, 0, -1, False)
    if not album_ids:
        raise DeezerError("Tidak ada album yang ditemukan untuk artis ini.")
    
    artist_meta['folderpath'] = sanitize_filepath(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{artist_meta['provider']}/{artist_meta['artist']}")
    artist_meta['albums'] = []

    _, _, artist_zip, _ = fetch_zip_settings(user)
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', bot_set.upload_mode)
    
    upload_album = True
    if bot_set.artist_batch:
        upload_album = True if (bot_set.upload_mode == 'Telegram' and user_mode == 'Telegram') else False
    if artist_zip or user_mode.title() in ['Gofile', 'Buzzheavier', 'Vikingfiles', 'Transferit', 'Pixeldrain', 'Terabox']: 
        upload_album = False 

    for album in album_ids:
        try:
            alb_res = await start_album(album, user, upload_album, basefolder=artist_meta['folderpath'])
            if alb_res:
                artist_meta['albums'].append(alb_res)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            LOGGER.warning(f"Melewati album Deezer ID {album} pada artis {artist_meta['title']}: {e}")
            continue

    if not artist_meta['albums']:
        raise DeezerError("Tidak ada album dari artis ini yang berhasil diunduh.")

    if not upload_album:
        await artist_upload(artist_meta, user)


async def start_playlist(playlist_id, user):
    deezerapi = user['deezer_api']
    
    raw_data = await deezerapi.get_playlist(playlist_id, -1, 0)
    play_meta = await process_playlist_meta(raw_data, user['r_id'], user=user)

    playlist_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{play_meta['provider']}/"
    playlist_zip, _, _, _ = fetch_zip_settings(user)
    playlist_sort = False if bot_set.upload_mode == 'Telegram' else bot_set.playlist_sort
    
    if not playlist_sort:
        playlist_folder += f"{play_meta['title']}"
        playlist_folder = sanitize_filepath(playlist_folder)
    play_meta['folderpath'] = playlist_folder
    os.makedirs(play_meta['folderpath'], exist_ok=True)

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user.get('bot_msg'),
        'title': play_meta['title'],
        'type': play_meta['type']
    }

    poster_key = f'poster_playlist_{playlist_id}'
    existing_poster = user.get(poster_key)

    if existing_poster:
        play_meta['poster_msg'] = existing_poster
    else:
        play_meta['poster_msg'] = await post_art_poster(user, play_meta)
        user[poster_key] = play_meta['poster_msg']
    
    limit_pekerja = Config.MAX_WORKERS if bot_set.playlist_conc else 1

    tasks = []
    for track in play_meta['tracks']:
        tasks.append(start_track(track['itemid'], user, track, False, playlist_folder, bot_set.disable_sort_link))
    
    task_results = await run_concurrent_tasks(tasks, update_details, limit=limit_pekerja)
    
    original_tracks = play_meta['tracks']
    successful_tracks = []
    for i in range(len(original_tracks)):
        if i < len(task_results) and task_results[i] is True:
            successful_tracks.append(original_tracks[i])
            
    play_meta['tracks'] = successful_tracks
    play_meta['totaltracks'] = len(successful_tracks)
    
    if not play_meta['tracks']:
        raise DeezerError(f"Tidak ada lagu Deezer yang berhasil diunduh (Track not available) untuk playlist {play_meta['title']}.")

    if playlist_zip and playlist_sort:
        play_meta['folderpath'] = await move_sorted_playlist(play_meta, user)
            
    if play_meta.get('cover') and os.path.exists(play_meta['cover']):
        try:
            cover_dest = os.path.join(play_meta['folderpath'], "cover.jpg")
            shutil.copy(play_meta['cover'], cover_dest)
        except Exception as e:
            LOGGER.warning(f"Gagal menyalin cover.jpg ke folder playlist: {e}")

    await playlist_upload(play_meta, user)
