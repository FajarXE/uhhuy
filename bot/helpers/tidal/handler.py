# [GANTI FILE: bot/helpers/tidal/handler.py]

import json
import base64
import os
import shutil  # <-- TAMBAHAN: Untuk menyalin cover
import asyncio 
from datetime import datetime 

from pathvalidate import sanitize_filepath

from .manager import tidal_manager
try:
    from .tidal_api import TidalApi
except ImportError:
    class TidalApi: pass

from .utils import *
from .metadata import *
from .mqa_identifier import MqaIdentifier 

from ..utils import *
from .utils import ffmpeg_convert_and_tag
from ..metadata import set_metadata, get_audio_extension
from ..uploder import *
from ..message import send_message, edit_message 

try:
    from bot.helpers.lyrics.manager import lyrics_manager
except ImportError:
    lyrics_manager = None

from ...settings import bot_set
import bot.helpers.translations as lang

from bot.logger import LOGGER
from config import Config


async def start_tidal(url:str, user:dict):
    item_id, type_ = await parse_url(url)
    if not type_:
        raise Exception("Invalid Tidal URL")

    if type_ == 'track':
        await start_track(item_id, user, None)
    elif type_ == 'artist':
        await start_artist(item_id, user)
    elif type_ == 'album':
        await start_album(item_id, user)
    elif type_ == 'playlist':
        await start_playlist(item_id, user) 
        

async def start_track(track_id:int, user:dict, track_meta:dict | None,
    upload=True, basefolder=None, session=None, 
    quality=None, disable_link=False, disable_msg=False
  ):
    
    client: TidalApi = user['tidal_api']

    try:
        track_data = await client.get_track(track_id)
    except Exception as e:
        LOGGER.error(f"start_track (get_track) gagal: {e}")
        return None

    cover = track_meta.get('cover') if track_meta else None
    thumbnail = track_meta.get('thumbnail') if track_meta else None
    
    # Metadata Enrichment
    track_meta_full = await get_track_metadata(
        track_id, 
        track_data, 
        user['r_id'], 
        cover, 
        thumbnail,
        client=client 
    )
    
    if basefolder:
        filepath = basefolder
    else:
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta_full['provider']}/{track_meta_full['albumartist']}/{track_meta_full['album']}"
    
    if not session:
        session, quality = await get_stream_session(track_data, user)
    
    if track_meta: 
        if track_meta.get('album'): track_meta_full['album'] = track_meta['album']
        if track_meta.get('albumartist'): track_meta_full['albumartist'] = track_meta['albumartist']
        if track_meta.get('artist'): track_meta_full['artist'] = track_meta['artist']
        if track_meta.get('title'): track_meta_full['title'] = track_meta['title']
        if track_meta.get('tracknumber'): track_meta_full['tracknumber'] = track_meta['tracknumber']
    
    track_meta = track_meta_full

    try:
        stream_data = await client.get_stream_url(track_id, quality, session)
    except Exception as e:
        error = e
        if 'Asset is not ready for playback' in str(e):
            error = f'Track [{track_id}] is not available in your region'
        LOGGER.error(error)
        return None
    

    if stream_data is not None:
        track_meta['quality'] = await get_quality(stream_data)

        if stream_data['manifestMimeType'] == 'application/dash+xml':
            manifest = base64.b64decode(stream_data['manifest'])
            urls, track_codec = parse_mpd(manifest)
        else:
            manifest = json.loads(base64.b64decode(stream_data['manifest']))
            track_codec = 'AAC' if 'mp4a' in manifest['codecs'] else manifest['codecs'].upper()
            urls = manifest['urls'][0]

        track_meta['codec'] = track_codec
        if stream_data['audioQuality'] == 'HI_RES_LOSSLESS':
            track_meta['bit_depth'] = 24
        else:
            track_meta['bit_depth'] = 16
            
        if track_codec in {'EAC3', 'MHA1', 'AC4'}:
            track_meta['sample_rate'] = 48
        else:
            track_meta['sample_rate'] = 44.1
        
        track_meta['folderpath'] = filepath
        
        filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
        filepath += f"/{filename}"
        filepath = sanitize_filepath(filepath)
        track_meta['filepath'] = filepath 

        # --- [SUNTIKAN RADAR ARIA2] ---
        details = None
        if upload and 'bot_msg' in user:
            details = {
                'msg': user['bot_msg'],
                'title': track_meta.get('title', 'Unknown'),
                'type': track_meta.get('type', 'Track').capitalize()
            }
        # ------------------------------

        if type(urls) == list:
            # --- [FIX ARIA2 DASH TURBO PARALEL] ---
            import asyncio, os, aiofiles
            temp_files = [f"{filepath}.{i}" for i in range(len(urls[0]))]
            
            # Turunkan sedikit ke 7 agar server Fastly CDN Tidal tidak memblokir IP
            # (7 file bersamaan sudah sangat cepat dan jauh lebih stabil)
            sem = asyncio.Semaphore(7) 

            async def dl_segment(url, temp_path):
                async with sem:
                    return await download_file(url, temp_path, details=None)
            
            if details and 'msg' in details:
                try: 
                    from bot.helpers.message import edit_message
                    await edit_message(details['msg'], f"⚡ Mengunduh `{details.get('title', 'Unknown')}`\n⚙️ **Aria2 Turbo**: Memproses {len(urls[0])} segmen DASH paralel...", None, False)
                except: pass

            tasks = [dl_segment(urls[0][i], temp_files[i]) for i in range(len(urls[0]))]
            results = await asyncio.gather(*tasks)
            
            if any(results):
                from bot.logger import LOGGER
                LOGGER.error("Aria2 gagal mengunduh salah satu list segmen DASH")
                return None
                
            # --- [FIX METADATA HILANG: PENGGABUNGAN MANUAL KUNCI URUTAN] ---
            # Kita TIDAK memakai await merge_tracks(temp_files, filepath) karena 
            # fungsi itu bisa mengacak urutan file yang selesai didownload bersamaan.
            try:
                async with aiofiles.open(filepath, 'wb') as outfile:
                    for f_path in temp_files: # Mengunci urutan mutlak dari 0 sampai akhir
                        if os.path.exists(f_path):
                            async with aiofiles.open(f_path, 'rb') as infile:
                                chunk = await infile.read()
                                await outfile.write(chunk)
                            os.remove(f_path) # Bersihkan pecahan temp
            except Exception as e:
                from bot.logger import LOGGER
                LOGGER.error(f"Gagal menggabungkan pecahan: {e}")
                return None
            # ---------------------------------------------------------------
            
        else:
            # Unduhan Single File
            err = await download_file(urls, filepath, details=details) # <-- Tambahkan details
            if err:
                from bot.logger import LOGGER
                LOGGER.error(f"Download_file gagal (single): {err}")
                return None

        track_meta['extension'] = await get_audio_extension(filepath)

        
        try:
            _, __, ___, user_convert_m4a = tidal_manager.get_user_quality_settings(user['user_id']) 
        except Exception:
            user_convert_m4a = "OFF" 
        
        is_high_tier = quality in ['LOSSLESS', 'HI_RES', 'HI_RES_LOSSLESS']
        is_m4a_file = (track_meta['extension'] == 'm4a')

        if lyrics_manager:
            try:
                lyrics_text = await lyrics_manager.fetch_lyrics(track_meta, user['user_id'])
                if lyrics_text:
                    track_meta['lyrics'] = lyrics_text 
                    LOGGER.info("Lirik berhasil diambil.")
            except Exception as e:
                LOGGER.error(f"Gagal mengambil lirik: {e}")

        if is_high_tier and is_m4a_file and user_convert_m4a == "ON":
            LOGGER.info(f"Mengonversi M4A (Tier {quality}) ke FLAC untuk user {user['user_id']} Sesuai pengaturan.")
            await ffmpeg_convert_and_tag(filepath, track_meta)
            track_meta['filepath'] = track_meta['filepath'] + '.flac'
            try: os.remove(filepath)
            except OSError: pass
        else:
            if is_high_tier and is_m4a_file and user_convert_m4a == "OFF":
                LOGGER.info(f"File Lossless/Max format M4A terdeteksi, tapi convert OFF (User {user['user_id']}).")
            
            new_filepath = track_meta['filepath'] + f".{track_meta['extension']}"
            os.rename(filepath, new_filepath)
            track_meta['filepath'] = new_filepath
            
        LOGGER.info(f"Menjalankan FINAL set_metadata (Mutagen) untuk: {track_meta['filepath']}")
        await set_metadata(track_meta, user['user_id']) 

        if upload:
            await track_upload(track_meta, user, False)

    return track_meta


async def start_album(album_id:int, user:dict, upload=True, basefolder=None):
    client: TidalApi = user['tidal_api']
    
    try:
        album_data = await client.get_album(album_id)
        tracks_data = await client.get_album_tracks(album_id)
    except Exception as e:
        raise e
        
    album_meta = await get_album_metadata(album_id, album_data, tracks_data, user['r_id'])

    if basefolder:
        album_folder = basefolder + f"/{album_meta['title']}"
    else:
        album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder 
    
    # Buat folder jika belum ada (untuk antisipasi copy cover)
    if not os.path.exists(album_folder):
        os.makedirs(album_folder, exist_ok=True)

    # --- TAMBAHAN: COPY COVER KE DALAM ZIP ---
    if album_meta.get('cover') and os.path.exists(album_meta['cover']):
        try:
            target_cover = os.path.join(album_folder, "cover.jpg")
            shutil.copy(album_meta['cover'], target_cover)
            LOGGER.info(f"Cover disalin ke folder album: {target_cover}")
        except Exception as e:
            LOGGER.warning(f"Gagal menyalin cover ke folder: {e}")
    # ------------------------------------------

    try:
        track_id_sample = tracks_data['items'][0]['id']
        track_data_sample = await client.get_track(track_id_sample)
        session, quality = await get_stream_session(track_data_sample, user)
        stream_data = await client.get_stream_url(track_id_sample, quality, session)
        album_meta['quality'] = await get_quality(stream_data)
    except Exception as e:
        LOGGER.error(f"Gagal mendapatkan info kualitas untuk album {album_id}: {e}")
        session, quality = (None, "LOSSLESS") 
        album_meta['quality'] = "LOSSLESS"

    if upload:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    tasks = []
    for track in album_meta['tracks']:
        stub_meta = {
            'itemid': track['itemid'],
            'album': album_meta['album'],
            'albumartist': album_meta['albumartist'],
            'cover': album_meta['cover'],
            'thumbnail': album_meta['thumbnail'],
            'tracknumber': track.get('tracknumber'), 
            'artist': track.get('artist'), 
            'title': track.get('title') 
        }
        tasks.append(start_track(
            track['itemid'], 
            user, 
            stub_meta,
            False, 
            album_folder, 
            session, 
            quality
        ))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': album_meta['title'],
        'type': album_meta['type']
    }
    
    # [FIX] Tambahkan limit antrean agar Aria2 stabil dan tidak tersedak!
    results = await run_concurrent_tasks(tasks, update_details, limit=Config.MAX_WORKERS)
    
    album_meta['tracks'] = [track for track in results if track]
    
    _, album_zip, __, ___ = fetch_zip_settings(user)
    
    if album_zip:
        await edit_message(user['bot_msg'], lang.s.ZIPPING)
        album_meta['zip_path'] = await zip_handler(album_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await album_upload(album_meta, user)


async def start_playlist(playlist_id:str, user:dict, upload=True, basefolder=None):
    client: TidalApi = user['tidal_api']
    
    try:
        playlist_data = await client.get_playlist(playlist_id)
    except Exception as e:
        raise e
        
    total_tracks = playlist_data.get('numberOfTracks', 0)
    if total_tracks == 0:
        LOGGER.warning(f"Playlist {playlist_id} terdaftar sebagai kosong (0 tracks).")
        
    tracks_data = await client.get_playlist_tracks(playlist_id, total_tracks)
    
    playlist_meta = await get_playlist_metadata(playlist_id, playlist_data, tracks_data, user['r_id'])

    if not playlist_meta['tracks']:
        LOGGER.warning(f"Playlist {playlist_id} kosong atau tidak berisi track.")
        raise Exception("Playlist ini kosong atau tidak berisi track yang valid.")

    playlist_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{playlist_meta['provider']}/{playlist_meta['artist']}/{playlist_meta['title']}"
    
    playlist_folder = sanitize_filepath(playlist_folder)
    playlist_meta['folderpath'] = playlist_folder 

    # Buat folder jika belum ada
    if not os.path.exists(playlist_folder):
        os.makedirs(playlist_folder, exist_ok=True)

    # --- TAMBAHAN: COPY COVER KE DALAM ZIP ---
    if playlist_meta.get('cover') and os.path.exists(playlist_meta['cover']):
        try:
            target_cover = os.path.join(playlist_folder, "cover.jpg")
            shutil.copy(playlist_meta['cover'], target_cover)
            LOGGER.info(f"Cover disalin ke folder playlist: {target_cover}")
        except Exception as e:
            LOGGER.warning(f"Gagal menyalin cover ke folder playlist: {e}")
    # ------------------------------------------

    try:
        track_id_sample = playlist_meta['tracks'][0]['itemid'] 
        track_data_sample = await client.get_track(track_id_sample)
        session, quality = await get_stream_session(track_data_sample, user)
        stream_data = await client.get_stream_url(track_id_sample, quality, session)
        playlist_meta['quality'] = await get_quality(stream_data)
    except Exception as e:
        LOGGER.error(f"Gagal mendapatkan info kualitas untuk playlist {playlist_id}: {e}")
        session, quality = (None, "LOSSLESS")
        playlist_meta['quality'] = "LOSSLESS"

    if upload:
        playlist_meta['poster_msg'] = await post_art_poster(user, playlist_meta)

    tasks = []
    for track in playlist_meta['tracks']:
        stub_meta = {
            'itemid': track['itemid'],
            'album': playlist_meta['album'], 
            'albumartist': playlist_meta['albumartist'], 
            'cover': None, 
            'thumbnail': None,
            'tracknumber': track.get('tracknumber'),
            'artist': track.get('artist'),
            'title': track.get('title')
        }
        tasks.append(start_track(
            track['itemid'], 
            user, 
            stub_meta, 
            False, 
            playlist_folder, 
            session, 
            quality
        ))

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': user['bot_msg'],
        'title': playlist_meta['title'],
        'type': playlist_meta['type']
    }
    
    # [FIX] Tambahkan limit antrean. Mendukung Mode Concurrent atau Berurutan!
    if getattr(bot_set, 'playlist_conc', True):
        limit_pekerja = Config.MAX_WORKERS
    else:
        limit_pekerja = 1 # Sequential (Kerjakan 1 per 1)
        
    results = await run_concurrent_tasks(tasks, update_details, limit=limit_pekerja)
    
    playlist_meta['tracks'] = [track for track in results if track]
    
    playlist_zip, _, __, ___ = fetch_zip_settings(user)

    if playlist_zip:
        await edit_message(user['bot_msg'], lang.s.ZIPPING)
        playlist_meta['zip_path'] = await zip_handler(playlist_meta['folderpath'])

    if upload:
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await playlist_upload(playlist_meta, user)


async def start_artist(artist_id:int, user:dict):
    client: TidalApi = user['tidal_api']

    artist_data = await client.get_artist(artist_id)
    artist_meta = await get_artist_metadata(artist_data, user['r_id'])
    artist_meta['folderpath'] = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{artist_meta['provider']}/{artist_meta['artist']}"
    artist_meta['folderpath'] = sanitize_filepath(artist_meta['folderpath']) 
    
    try:
        artist_albums = await client.get_artist_albums(artist_id)
        artist_eps = await client.get_artist_albums_ep_singles(artist_id)
    except Exception as e:
        raise e

    albums = await sort_album_from_artist(artist_albums['items'], user)
    ep_singles = await sort_album_from_artist(artist_eps['items'], user)
    
    albums.extend(ep_singles)

    _, __, artist_zip, ___ = fetch_zip_settings(user)

    upload_album = True
    
    if bot_set.artist_batch:
        upload_album = True if bot_set.upload_mode == 'Telegram' else False
    
    if artist_zip: 
        upload_album = False

    for album in albums:
        await start_album(album['id'], user, upload_album, artist_meta['folderpath'])

    if not upload_album:
        _, __, artist_zip_check, ___ = fetch_zip_settings(user) 
        if artist_zip_check: 
            await edit_message(user['bot_msg'], lang.s.ZIPPING)
            artist_meta['zip_path'] = await zip_handler(artist_meta['folderpath'])
        
        await edit_message(user['bot_msg'], lang.s.UPLOADING)
        await artist_upload(artist_meta, user)
