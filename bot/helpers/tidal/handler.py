# [GANTI FILE: bot/helpers/tidal/handler.py]

import json
import base64
import os
import shutil 
import asyncio 
import hashlib
import time
import zipfile
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
from bot.helpers.ui_manager import progress_message, GLOBAL_CANCEL_DICT

from ...settings import bot_set
import bot.helpers.translations as lang

from bot.logger import LOGGER
from config import Config


async def start_tidal(url: str, user: dict):
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
        await start_video(item_id, user) 


async def start_video(video_id: str, user: dict, upload=True):
    client: TidalApi = user['tidal_api']
    
    video_data = await client.get_video(video_id)
    video_meta = await get_video_metadata(video_id, video_data, user['r_id'], client, user['user_id'])
    
    filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{video_meta['provider']}/{video_meta['artist']}"
    os.makedirs(filepath, exist_ok=True)
    
    filename = f"{video_meta['title']} - {video_meta['artist']}".replace('/', ' ')
    raw_ts_path = sanitize_filepath(f"{filepath}/{filename}.ts")
    final_mp4_path = sanitize_filepath(f"{filepath}/{filename}.mp4")
    
    session = client.tv_session or (client.saved[0] if client.saved else None)
    stream_data = await client.get_video_stream_url(video_id, session)
    segment_urls, quality_str = await parse_m3u8_video(stream_data['manifest'], session.auth_headers())
    
    details = None
    task_id = None
    if upload and user.get('bot_msg'):
        task_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
        details = {
            'msg': user['bot_msg'],
            'title': video_meta.get('title', 'Unknown Video'),
            'type': 'Video',
            'action': 'Download',
            'machine': 'Aria2c 1.37.0',
            'task_id': task_id
        }
        
    sem = asyncio.Semaphore(16)
    total_segments = len(segment_urls)
    completed_segments = 0
    total_bytes = 0
    last_ui_update = time.time() 
    
    async def fetch_segment(index, url):
        nonlocal completed_segments, total_bytes, last_ui_update
        if task_id and task_id in GLOBAL_CANCEL_DICT:
            raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
        t_path = f"{raw_ts_path}.{index}"
        async with sem:
            if task_id and task_id in GLOBAL_CANCEL_DICT:
                raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
            err = await download_file(url, t_path)
            if err:
                raise Exception(f"Gagal mengunduh bagian video: {err}")
            
            if os.path.exists(t_path):
                total_bytes += os.path.getsize(t_path)
            completed_segments += 1
            
            now = time.time()
            if details and (now - last_ui_update > 5.0 or completed_segments == total_segments):
                last_ui_update = now
                estimasi_total = int((total_bytes / completed_segments) * total_segments) if completed_segments > 0 else 0
                details['action'] = 'Download'
                asyncio.create_task(progress_message(total_bytes, estimasi_total, details))
                
        return t_path

    tasks = [asyncio.create_task(fetch_segment(i, url)) for i, url in enumerate(segment_urls)]
    
    try:
        temp_files = await asyncio.gather(*tasks)
    except BaseException:
        for t in tasks:
            if not t.done():
                t.cancel()
        for i in range(total_segments):
            seg_p = f"{raw_ts_path}.{i}"
            if os.path.exists(seg_p):
                try:
                    os.remove(seg_p)
                except OSError:
                    pass
        raise
        
    await merge_tracks(temp_files, raw_ts_path)
    await convert_ts_to_mp4(raw_ts_path, final_mp4_path)
    
    try:
        os.remove(raw_ts_path)
    except OSError:
        pass
    
    user_settings = bot_set.user_data.get(user['user_id'], {})
    raw_zip = user_settings.get("VIDEO_ZIP")
    if raw_zip is None:
        raw_zip = user_settings.get("video_zip", False)
        
    if isinstance(raw_zip, str):
        is_video_zip = raw_zip.strip().lower() in ['true', '1', 'on', 'yes']
    else:
        is_video_zip = bool(raw_zip)
    
    if is_video_zip:
        zip_path = f"{filepath}/{filename}.zip"
        if details:
            details['action'] = 'Zipping'
            await progress_message(1, 1, details) 
            
        await asyncio.to_thread(_create_single_file_zip, zip_path, final_mp4_path)
        try:
            os.remove(final_mp4_path)
        except OSError:
            pass
        
        video_meta['filepath'] = zip_path
        video_meta['extension'] = 'zip'
        video_meta['type'] = 'Video'       
        video_meta['media_type'] = 'doc'   
    else:
        video_meta['filepath'] = final_mp4_path
        video_meta['extension'] = 'mp4'
        video_meta['type'] = 'Video'       
        video_meta['media_type'] = 'video' 
    
    video_meta['quality'] = quality_str
    video_meta['caption'] = (
        f"NAME : {video_meta.get('title', 'Unknown')}\n"
        f"TYPE : Video\n"
        f"PROVIDER : Tidal\n"
        f"QUALITY : {quality_str}"
    )
    
    if upload:
        await video_upload(video_meta, user)

    return video_meta


def _create_single_file_zip(zip_path: str, target_file: str):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED, allowZip64=True) as zipf:
        zipf.write(target_file, os.path.basename(target_file))


async def start_track(
    track_id: int,
    user: dict,
    track_meta: dict | None,
    upload=True,
    basefolder=None,
    session=None, 
    quality=None,
    disable_link=False,
    disable_msg=False
):
    client: TidalApi = user['tidal_api']
    is_single_track = track_meta is None

    try:
        track_data = await client.get_track(track_id)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        if is_single_track:
            raise e
        LOGGER.error(f"start_track (get_track {track_id}) gagal: {e}")
        return None

    cover = track_meta.get('cover') if track_meta else None
    thumbnail = track_meta.get('thumbnail') if track_meta else None
    
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
        if track_meta.get('album'):
            track_meta_full['album'] = track_meta['album']
        if track_meta.get('albumartist'):
            track_meta_full['albumartist'] = track_meta['albumartist']
        if track_meta.get('artist'):
            track_meta_full['artist'] = track_meta['artist']
        if track_meta.get('title'):
            track_meta_full['title'] = track_meta['title']
        if track_meta.get('tracknumber'):
            track_meta_full['tracknumber'] = track_meta['tracknumber']
    
    track_meta = track_meta_full

    try:
        stream_data = await client.get_stream_url(track_id, quality, session)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        error = e
        if 'Asset is not ready for playback' in str(e):
            error = f'Region-locked: Track [{track_id}] is not available in your region'
            
        if is_single_track:
            raise Exception(error)
        else:
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
            
        try:
            total_vol = int(track_meta.get('totalvolume', 1))
            if total_vol > 1:
                vol_num = track_meta.get('volume', '1')
                filepath = f"{filepath}/Volume {vol_num}"
        except Exception:
            pass
        
        track_meta['folderpath'] = filepath
        
        filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
        filepath += f"/{filename}"
        filepath = sanitize_filepath(filepath)
        track_meta['filepath'] = filepath  

        details = None
        task_id = None
        if user.get('bot_msg'):
            task_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
            if upload:
                details = {
                    'msg': user['bot_msg'],
                    'title': track_meta.get('title', 'Unknown'),
                    'type': 'Track',
                    'action': 'Download',
                    'machine': 'Aria2c 1.37.0',
                    'task_id': task_id
                }

        if isinstance(urls, list):
            sem = asyncio.Semaphore(16) 
            
            total_segments = len(urls[0])
            completed_segments = 0
            total_bytes = 0
            last_ui_update = time.time()
            
            async def fetch_audio_chunk(index, url):
                nonlocal completed_segments, total_bytes, last_ui_update
                if task_id and task_id in GLOBAL_CANCEL_DICT:
                    raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
                t_path = f"{filepath}.{index}"
                async with sem:
                    if task_id and task_id in GLOBAL_CANCEL_DICT:
                        raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
                    err = await download_file(url, t_path) 
                    if err:
                        raise Exception(f"Gagal mengunduh kepingan audio {index}: {err}")
                    
                    if os.path.exists(t_path):
                        total_bytes += os.path.getsize(t_path)
                    completed_segments += 1
                    
                    now = time.time()
                    if details and (now - last_ui_update > 2.0 or completed_segments == total_segments):
                        last_ui_update = now
                        estimasi_total = int((total_bytes / completed_segments) * total_segments) if completed_segments > 0 else 0
                        details['action'] = 'Download'
                        asyncio.create_task(progress_message(total_bytes, estimasi_total, details))
                        
                return t_path

            tasks = [asyncio.create_task(fetch_audio_chunk(i, url)) for i, url in enumerate(urls[0])]
            try:
                temp_files = await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                for t in tasks:
                    if not t.done():
                        t.cancel()
                for i in range(total_segments):
                    seg_p = f"{filepath}.{i}"
                    if os.path.exists(seg_p):
                        try:
                            os.remove(seg_p)
                        except OSError:
                            pass
                raise
            except Exception as e:
                for t in tasks:
                    if not t.done():
                        t.cancel()
                for i in range(total_segments):
                    seg_p = f"{filepath}.{i}"
                    if os.path.exists(seg_p):
                        try:
                            os.remove(seg_p)
                        except OSError:
                            pass
                LOGGER.error(f"Gagal mendownload segmen audio: {e}")
                if is_single_track:
                    raise e
                return None
                
            await merge_tracks(temp_files, filepath)
        else:
            err = await download_file(urls, filepath, details=details) 
            if err:
                LOGGER.error(f"Download_file gagal (single): {err}")
                if is_single_track:
                    raise Exception(f"Gagal mengunduh file audio: {err}")
                return None

        track_meta['extension'] = await get_audio_extension(filepath)
        
        if track_meta['extension'] == 'flac':
            mqa_info = await asyncio.to_thread(MqaIdentifier, filepath)
            if mqa_info.is_mqa:
                LOGGER.info(f"Tidal: MQA Terdeteksi! Sample Rate Asli: {mqa_info.get_original_sample_rate()}kHz")
                track_meta['mqa_details'] = mqa_info
                track_meta['is_mqa_studio'] = mqa_info.is_mqa_studio
        
        try:
            _, __, ___, user_convert_m4a = tidal_manager.get_user_quality_settings(user['user_id']) 
        except Exception:
            user_convert_m4a = "OFF" 
        
        actual_quality = track_meta.get('quality', '')
        is_high_tier = actual_quality in ['LOSSLESS', 'MAX', 'HI_RES', 'HI_RES_LOSSLESS']
        is_m4a_file = (track_meta.get('extension') == 'm4a')

        if is_high_tier and is_m4a_file and user_convert_m4a == "ON":
            LOGGER.info(f"Mengonversi M4A (Tier {actual_quality}) ke FLAC untuk user {user['user_id']}.")
            await ffmpeg_convert_and_tag(filepath, track_meta)
            try:
                os.remove(filepath)
            except OSError:
                pass
            track_meta['filepath'] = f"{track_meta['filepath']}.flac"
            track_meta['extension'] = 'flac'
        else:
            new_filepath = f"{track_meta['filepath']}.{track_meta['extension']}"
            if os.path.exists(new_filepath) and new_filepath != filepath:
                try:
                    os.remove(new_filepath)
                except OSError:
                    pass
            os.rename(filepath, new_filepath)
            track_meta['filepath'] = new_filepath
            
        # set_metadata otomatis menangani penulisan tag Mutagen + pengambilan lirik & pembuatan file .lrc
        await set_metadata(track_meta, user['user_id']) 

        if upload:
            await track_upload(track_meta, user, False)

    return track_meta


async def start_album(album_id: int, user: dict, upload=True, basefolder=None):
    client: TidalApi = user['tidal_api']
    
    album_data = await client.get_album(album_id)
    tracks_data = await client.get_album_tracks(album_id)
        
    album_meta = await get_album_metadata(album_id, album_data, tracks_data, user['r_id'], user_id=user['user_id'])
    if not album_meta.get('tracks'):
        raise Exception("Region-locked: Album ini kosong atau tidak tersedia di region akun ini.")

    if basefolder:
        album_folder = basefolder + f"/{album_meta['title']}"
    else:
        album_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder 
    os.makedirs(album_folder, exist_ok=True)

    if album_meta.get('cover') and os.path.exists(album_meta['cover']):
        try:
            target_cover = os.path.join(album_folder, "cover.jpg")
            shutil.copy(album_meta['cover'], target_cover)
        except Exception as e:
            LOGGER.warning(f"Gagal menyalin cover ke folder: {e}")

    try:
        track_id_sample = tracks_data['items'][0]['id']
        track_data_sample = await client.get_track(track_id_sample)
        session, quality = await get_stream_session(track_data_sample, user)
        stream_data = await client.get_stream_url(track_id_sample, quality, session)
        album_meta['quality'] = await get_quality(stream_data)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        if 'Asset is not ready' in str(e) or 'region-locked' in str(e).lower():
            raise Exception("Region-locked: Album tidak tersedia di akun ini.")
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
        'msg': user.get('bot_msg'),
        'title': album_meta['title'],
        'type': album_meta['type']
    }
    
    results = await run_concurrent_tasks(tasks, update_details, limit=Config.MAX_WORKERS)
    album_meta['tracks'] = [track for track in results if isinstance(track, dict)]
    album_meta['totaltracks'] = len(album_meta['tracks'])

    if not album_meta['tracks']:
        raise Exception("Region-locked: Tidak ada lagu yang berhasil diunduh pada album ini.")
    
    if upload:
        await album_upload(album_meta, user)

    return album_meta


async def start_playlist(playlist_id: str, user: dict, upload=True, basefolder=None):
    client: TidalApi = user['tidal_api']
    
    playlist_data = await client.get_playlist(playlist_id)
    total_tracks = playlist_data.get('numberOfTracks', 0)
    tracks_data = await client.get_playlist_tracks(playlist_id, total_tracks)
    
    playlist_meta = await get_playlist_metadata(playlist_id, playlist_data, tracks_data, user['r_id'], user_id=user['user_id'])

    if not playlist_meta['tracks']:
        raise Exception("Playlist ini kosong atau tidak berisi track yang valid.")

    playlist_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{playlist_meta['provider']}/{playlist_meta['artist']}/{playlist_meta['title']}"
    playlist_folder = sanitize_filepath(playlist_folder)
    playlist_meta['folderpath'] = playlist_folder 
    os.makedirs(playlist_folder, exist_ok=True)

    if playlist_meta.get('cover') and os.path.exists(playlist_meta['cover']):
        try:
            target_cover = os.path.join(playlist_folder, "cover.jpg")
            shutil.copy(playlist_meta['cover'], target_cover)
        except Exception as e:
            LOGGER.warning(f"Gagal menyalin cover ke folder playlist: {e}")

    try:
        track_id_sample = playlist_meta['tracks'][0]['itemid'] 
        track_data_sample = await client.get_track(track_id_sample)
        session, quality = await get_stream_session(track_data_sample, user)
        stream_data = await client.get_stream_url(track_id_sample, quality, session)
        playlist_meta['quality'] = await get_quality(stream_data)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        if 'Asset is not ready' in str(e) or 'region-locked' in str(e).lower():
            raise Exception("Region-locked: Playlist tidak tersedia di akun ini.")
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
        'msg': user.get('bot_msg'),
        'title': playlist_meta['title'],
        'type': playlist_meta['type']
    }
    
    limit_pekerja = Config.MAX_WORKERS if getattr(bot_set, 'playlist_conc', True) else 1
    results = await run_concurrent_tasks(tasks, update_details, limit=limit_pekerja)
    
    playlist_meta['tracks'] = [track for track in results if isinstance(track, dict)]
    playlist_meta['totaltracks'] = len(playlist_meta['tracks'])

    if not playlist_meta['tracks']:
        raise Exception("Region-locked: Tidak ada lagu pada playlist ini yang berhasil diunduh.")
    
    if upload:
        await playlist_upload(playlist_meta, user)


async def start_artist(artist_id: int, user: dict):
    client: TidalApi = user['tidal_api']

    artist_data = await client.get_artist(artist_id)
    artist_meta = await get_artist_metadata(artist_data, user['r_id'], user_id=user['user_id'])
    artist_meta['folderpath'] = sanitize_filepath(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{artist_meta['provider']}/{artist_meta['artist']}")
    artist_meta['albums'] = []
    
    artist_albums = await client.get_artist_albums(artist_id)
    artist_eps = await client.get_artist_albums_ep_singles(artist_id)

    albums = await sort_album_from_artist(artist_albums.get('items', []), user)
    ep_singles = await sort_album_from_artist(artist_eps.get('items', []), user)
    albums.extend(ep_singles)

    if not albums:
        raise Exception("Tidak ada album yang ditemukan untuk artis ini.")

    _, __, artist_zip, ___ = fetch_zip_settings(user)
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', bot_set.upload_mode)

    upload_album = True
    if bot_set.artist_batch:
        upload_album = True if (bot_set.upload_mode == 'Telegram' and user_mode == 'Telegram') else False
    if artist_zip or user_mode.title() in ['Gofile', 'Buzzheavier', 'Vikingfiles', 'Transferit', 'Pixeldrain', 'Terabox']: 
        upload_album = False

    for album in albums:
        try:
            alb_res = await start_album(album['id'], user, upload_album, artist_meta['folderpath'])
            if alb_res:
                artist_meta['albums'].append(alb_res)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            LOGGER.warning(f"Melewati album ID {album['id']} pada artis {artist_meta['title']}: {e}")
            continue

    if not artist_meta['albums']:
        raise Exception("Region-locked: Tidak ada album dari artis ini yang berhasil diunduh.")

    if not upload_album:
        await artist_upload(artist_meta, user)
