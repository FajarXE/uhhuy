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


# 1. Update fungsi start_tidal untuk mengarahkan rute 'video'
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
    elif type_ == 'video':
        await start_video(item_id, user) # <- TAMBAHAN RUTE VIDEO


# 2. Tambahkan fungsi inti start_video (Bisa diletakkan di paling bawah)
async def start_video(video_id: str, user: dict, upload=True):
    client: TidalApi = user['tidal_api']
    
    try:
        video_data = await client.get_video(video_id)
    except Exception as e:
        LOGGER.error(f"Gagal mengambil data video: {e}")
        return None
        
    video_meta = await get_video_metadata(video_id, video_data, user['r_id'], client, user['user_id'])
    
    filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{video_meta['provider']}/{video_meta['artist']}"
    if not os.path.exists(filepath):
        os.makedirs(filepath, exist_ok=True)
    
    filename = f"{video_meta['title']} - {video_meta['artist']}".replace('/', ' ')
    raw_ts_path = sanitize_filepath(f"{filepath}/{filename}.ts")
    final_mp4_path = sanitize_filepath(f"{filepath}/{filename}.mp4")
    
    session = client.tv_session 
    try:
        stream_data = await client.get_video_stream_url(video_id, session)
        segment_urls = await parse_m3u8_video(stream_data['manifest'], session.auth_headers())
    except Exception as e:
        LOGGER.error(f"Gagal memuat URL Video streaming: {e}")
        raise e
    
    # Beri tahu UI bahwa bot sedang mengunduh kepingan (sekali saja)
    if upload and 'bot_msg' in user:
        try: await edit_message(user['bot_msg'], f"⏳ Mengunduh {len(segment_urls)} kepingan video (HLS)...")
        except: pass
        
    temp_files = []
    # Unduh per-segmen HLS secara diam-diam
    for i, url in enumerate(segment_urls):
        t_path = f"{raw_ts_path}.{i}"
        
        # --- FIX: Hapus details=details di sini agar tidak membanjiri UI Radar ---
        err = await download_file(url, t_path)
        
        if err:
            LOGGER.error("Terjadi masalah saat mengunduh bagian video.")
            return None
        temp_files.append(t_path)
        
    # Beri tahu UI saat mulai menggabungkan file
    if upload and 'bot_msg' in user:
        try: await edit_message(user['bot_msg'], "⏳ Menggabungkan dan memproses video (FFmpeg)...")
        except: pass
        
    # Gabungkan file segmen dan ubah formatnya
    await merge_tracks(temp_files, raw_ts_path)
    await convert_ts_to_mp4(raw_ts_path, final_mp4_path)
    
    try: os.remove(raw_ts_path)
    except OSError: pass
    
    video_meta['filepath'] = final_mp4_path
    video_meta['extension'] = 'mp4'
    
    # Manfaatkan track_upload yang sudah ada
    if upload:
        await track_upload(video_meta, user, False)

    return video_meta
        

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
        client=client,
        user_id=user['user_id']
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
            
        # --- LOGIKA FOLDER VOLUME UNTUK MULTI-VOLUME ALBUM ---
        try:
            total_vol = int(track_meta.get('totalvolume', 1))
            # Jika total volume lebih dari 1, buat sub-folder "Volume X"
            if total_vol > 1:
                vol_num = track_meta.get('volume', '1')
                filepath = f"{filepath}/Volume {vol_num}"
        except Exception:
            pass
        # -----------------------------------------------------
        
        track_meta['folderpath'] = filepath
        
        filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
        filepath += f"/{filename}"
        filepath = sanitize_filepath(filepath)
        track_meta['filepath'] = filepath  

        # --- [FIX UTAMA] SUNTIKAN RADAR ARIA2 ---
        details = None
        if upload and 'bot_msg' in user:
            details = {
                'msg': user['bot_msg'],
                'title': track_meta.get('title', 'Unknown'),
                'type': track_meta.get('type', 'Track').capitalize()
            }
        # ----------------------------------------

        if type(urls) == list:
            # Beri tahu UI bahwa bot sedang mengunduh kepingan (sekali saja)
            if upload and 'bot_msg' in user:
                try: await edit_message(user['bot_msg'], f"⏳ Mengunduh {len(urls[0])} kepingan segmen...")
                except: pass
                
            i = 0
            temp_files = []
            for url in urls[0]:
                temp_path = f"{filepath}.{i}"
                
                # --- FIX: Hapus details=details di sini agar tidak membanjiri UI Radar ---
                err = await download_file(url, temp_path) 
                
                if err:
                    LOGGER.error(f"Download_file gagal (list): {err}")
                    return None
                i+=1
                temp_files.append(temp_path)
                
            # Beri tahu UI saat mulai menggabungkan file
            if upload and 'bot_msg' in user:
                try: await edit_message(user['bot_msg'], "⏳ Menggabungkan kepingan file...")
                except: pass
                
            await merge_tracks(temp_files, filepath)
        else:
            # Untuk file tunggal (bukan kepingan), TETAP GUNAKAN details 
            # agar progress bar berjalan normal di layar
            err = await download_file(urls, filepath, details=details) 
            if err:
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
        
    album_meta = await get_album_metadata(album_id, album_data, tracks_data, user['r_id'], user_id=user['user_id'])

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
    
    # Zipping dan upload diurus secara otomatis oleh uploader.py
    if upload:
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
    
    playlist_meta = await get_playlist_metadata(playlist_id, playlist_data, tracks_data, user['r_id'], user_id=user['user_id'])

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
    
    # Zipping dan upload diurus secara otomatis oleh uploader.py
    if upload:
        await playlist_upload(playlist_meta, user)


async def start_artist(artist_id:int, user:dict):
    client: TidalApi = user['tidal_api']

    artist_data = await client.get_artist(artist_id)
    artist_meta = await get_artist_metadata(artist_data, user['r_id'], user_id=user['user_id'])
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
        # Zipping dan upload diurus secara otomatis oleh uploader.py
        await artist_upload(artist_meta, user)
