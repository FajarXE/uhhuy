# [GANTI FILE: bot/helpers/qobuz/handler.py]

import shutil
import os
import traceback
import hashlib
import asyncio
from .utils import *
from config import Config
from pathvalidate import sanitize_filepath

from ..utils import *
from ..metadata import set_metadata, create_cover_file
from ..message import edit_message, send_message
from bot.logger import LOGGER

from bot.settings import bot_set 
from bot.helpers.qobuz.qopy import qobuz_manager
import bot.helpers.ui_manager as ui_manager

from ..uploder import track_upload, album_upload, artist_upload, playlist_upload

# --- IMPORTS UTILS FOR CUSTOM TAGS ---
try:
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3, TXXX
except ImportError:
    FLAC = None
    ID3 = None
    LOGGER.warning("Mutagen tidak terinstall. Custom tags mungkin tidak tersimpan.")
# --------------------------------------

async def force_custom_tags(filepath, metadata):
    if not os.path.exists(filepath):
        return
    ext = filepath.split('.')[-1].lower()
    target_keys = ['creation_time', 'RELEASETIME', 'ORIGINALDATE']
    tags_to_write = {k: str(metadata[k]) for k in target_keys if metadata.get(k)}
    if not tags_to_write:
        return

    def _save_tags():
        try:
            if ext == 'flac' and FLAC:
                try:
                    audio = FLAC(filepath)
                    for k, v in tags_to_write.items():
                        audio[k] = v
                    audio.save()
                except Exception:
                    pass
            elif ext == 'mp3' and ID3:
                try:
                    try:
                        audio = ID3(filepath)
                    except Exception:
                        audio = ID3()
                        audio.save(filepath)
                    for k, v in tags_to_write.items():
                        audio.add(TXXX(encoding=3, desc=k, text=v))
                    audio.save()
                except Exception:
                    pass
        except Exception:
            pass

    await asyncio.to_thread(_save_tags)

async def start_qobuz(url: str, user: dict):
    global_clients_list = user.get('qobuz_clients_list', [])
    tg_user_id = user.get('user_id')
    private_clients = await qobuz_manager.get_user_clients(tg_user_id)
    
    final_clients_list = []
    if private_clients:
        LOGGER.info(f"User {tg_user_id} menggunakan {len(private_clients)} akun pribadi Qobuz.")
        final_clients_list.extend(private_clients)
        
    final_clients_list.extend(global_clients_list)

    if not final_clients_list:
        raise Exception("Tidak ada klien Qobuz aktif (Global/Private).")

    cancel_id = None
    if user.get('bot_msg'):
        cancel_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]

    last_error = "Tidak ada error"
    
    for i, client in enumerate(final_clients_list):
        if cancel_id and cancel_id in ui_manager.GLOBAL_CANCEL_DICT:
            raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")

        user['qobuz_api'] = client
        c_label = getattr(client, 'label', str(client.user_id))
        
        try:
            # Update status di RAM Radar UI tanpa memicu spam EditMessage ke Telegram
            if cancel_id and cancel_id in ui_manager.GLOBAL_TASKS:
                ui_manager.GLOBAL_TASKS[cancel_id]['processed'] = f"Trying Account #{i+1} ({c_label})..."
            
            items, item_id, type_dict, content = await check_type(url, user)
            
            if items is None and item_id is None:
                raise QobuzContentUnavailableError("Gagal mendapatkan item/ID valid.")

            if items is not None:
                if not items:
                    raise Exception("Playlist/Artis kosong.")
                if type_dict['iterable_key'] == 'albums': 
                    await start_artist(items, user, content)
                else: 
                    await start_playlist(items, content, user)
            else:
                if type_dict.get("album") is True:
                    await start_album(item_id, user)
                elif type_dict.get("album") is False:
                    await start_track(item_id, user, None)
                else:
                    raise Exception("Tipe konten tidak diketahui.")
            
            return 

        except asyncio.CancelledError:
            raise
        except QobuzContentUnavailableError as e:
            last_error = f"{e}"
            LOGGER.warning(f"Akun {c_label} gagal mengambil konten Qobuz (Region Lock/Sample): {e}")
            continue 
        except Exception as e:
            last_error = f"{e}"
            LOGGER.error(f"Fatal Error Qobuz (Start): {e}\n{traceback.format_exc()}")
            break 

    raise Exception(f"Gagal memproses dengan semua akun Qobuz yang tersedia. Error terakhir: {last_error}")

async def start_album(item_id: int, user: dict, upload=True, basefolder=None):
    client = user['qobuz_api']
    
    album_meta, err = await get_album_metadata(item_id, user['r_id'], user)
    if err or not album_meta:
        raise QobuzContentUnavailableError(f"Album tidak tersedia di akun ini ({err}).")
    
    # --- MODE BOOKLET ONLY (-b) ---
    if user.get('booklet_only'):
        if album_meta.get('booklet_url'):
            album_folder = basefolder + f"/{album_meta['title']}" if basefolder else f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
            album_folder = sanitize_filepath(album_folder)
            os.makedirs(album_folder, exist_ok=True)
            
            temp_path = os.path.join(album_folder, f"{sanitize_filepath(album_meta['title'])} - Booklet.pdf")
            err_dl = await download_file(album_meta['booklet_url'], temp_path)
            if not err_dl and os.path.exists(temp_path):
                await send_message(
                    user,
                    temp_path,
                    'doc',
                    caption=f"📑 **Booklet**: {album_meta['title']}"
                )
            else:
                await send_message(user, f"❌ Gagal mengunduh booklet untuk `{album_meta['title']}`.", 'text')
        else:
            await send_message(user, f"❌ Tidak ada booklet digital yang dirilis untuk album `{album_meta['title']}`.", 'text')
        return None
    # ------------------------------
    
    # Cek sampel pada track pertama (dan fallback ke track ke-2 hanya jika jumlah track > 1)
    track_meta = None
    try: 
        track_meta = await client.get_track_url(album_meta['tracks'][0]['itemid'], user)
    except asyncio.CancelledError:
        raise
    except Exception: 
        if len(album_meta['tracks']) > 1:
            try: 
                track_meta = await client.get_track_url(album_meta['tracks'][1]['itemid'], user)
            except asyncio.CancelledError:
                raise
            except Exception: 
                raise QobuzContentUnavailableError("Gagal mendapatkan URL track sampel album.")
        else:
            raise QobuzContentUnavailableError("Gagal mendapatkan URL track sampel album.")
            
    if not track_meta or track_meta.get('sample'):
        raise QobuzContentUnavailableError("Akun ini hanya dapat mengunduh sampel (Region Block / Akun Free). Beralih akun...")
            
    _, album_meta['quality'] = await get_quality(track_meta, user)
    
    if upload:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    album_folder = basefolder + f"/{album_meta['title']}" if basefolder else f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder
    
    tasks = []
    for track in album_meta['tracks']:
        tasks.append(start_track(track['itemid'], user, track, False, album_folder))
        
    update_details = {'text': lang.s.DOWNLOAD_PROGRESS, 'msg': user.get('bot_msg'), 'title': album_meta['title'], 'type': album_meta['type']}
    
    task_results = await run_concurrent_tasks(tasks, update_details, limit=Config.MAX_WORKERS)
    
    successful_tracks = [album_meta['tracks'][i] for i, res in enumerate(task_results) if res is True]
    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks: 
        raise QobuzContentUnavailableError("Tidak ada lagu yang berhasil diunduh di album ini.")

    # Booklet (Untuk pengunduhan album normal)
    booklet_path = None
    if album_meta.get('booklet_url'):
        try:
            temp_path = os.path.join(album_meta['folderpath'], "Booklet.pdf")
            if not await download_file(album_meta['booklet_url'], temp_path):
                booklet_path = temp_path
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    if album_meta.get('cover') and os.path.exists(album_meta['cover']):
        try:
            shutil.copy2(album_meta['cover'], os.path.join(album_meta['folderpath'], "cover.jpg"))
        except Exception:
            pass

    if upload and booklet_path and os.path.exists(booklet_path):
        user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', bot_set.upload_mode)
        if user_mode == 'Telegram':
            try:
                await send_message(user, booklet_path, 'doc', caption=f"📑 **Booklet**: {album_meta['title']}")
            except Exception:
                pass

    if upload:
        await album_upload(album_meta, user)

    return album_meta

async def start_track(item_id: int, user: dict, track_meta: dict | None, upload=True, basefolder=None, disable_link=False, disable_msg=False):
    client = user['qobuz_api']
    is_single_track = track_meta is None
    
    if is_single_track:
        track_meta, err = await get_track_metadata(item_id, user['r_id'], None, user)
        if err or not track_meta: 
            raise QobuzContentUnavailableError(f"Gagal memuat metadata: {err}")
            
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)
    else: 
        filepath = basefolder
    
    try:
        raw_data = await client.get_track_url(item_id, user)
        if not raw_data or raw_data.get('sample') or not raw_data.get('url'):
            raise QobuzContentUnavailableError("Track hanya tersedia sebagai sampel (Region Block / Akun Free).")
        url = raw_data['url']
    except asyncio.CancelledError:
        raise
    except QobuzContentUnavailableError as e:
        if is_single_track:
            raise e
        LOGGER.warning(f"Track ID {item_id} hanya sampel (Region Block/Free). Skipping...")
        return False
    except Exception as e:
        LOGGER.warning(f"Gagal mendapatkan URL Track ID {item_id}: {e}. Skipping...")
        return False 
        
    try:
        # Jika berasal dari playlist yang menunda pengunduhan cover, unduh cover-nya sekarang (ter-cache per album)
        if not track_meta.get('cover') and track_meta.get('_raw_q_meta'):
            raw_q = track_meta.pop('_raw_q_meta', None)
            cover_url = await resolve_qobuz_cover_url(track_meta, raw_q, user)
            track_meta['cover'] = await create_cover_file(cover_url, track_meta)
            track_meta['thumbnail'] = await create_cover_file(cover_url, track_meta, True)

        track_meta['extension'], track_meta['quality'] = await get_quality(raw_data, user)
        raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
        
        target_dir = filepath
        try:
            total_vol = int(track_meta.get('totalvolume', 1))
            if total_vol > 1:
                vol_num = track_meta.get('volume', '1')
                target_dir = f"{filepath}/Disc {vol_num}"
        except Exception:
            pass
        
        full_path = f"{target_dir}/{sanitize_filepath(raw_filename)}.{track_meta['extension']}"
        track_meta['filepath'] = full_path

        details = None
        if upload and user.get('bot_msg'):
            task_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
            details = {
                'msg': user['bot_msg'],
                'title': track_meta.get('title', 'Unknown'),
                'type': 'Track',
                'action': 'Download',
                'task_id': task_id
            }

        err = await download_file(url, full_path, details=details)
        if err is not None:
            return False
        
        await set_metadata(track_meta, user['user_id'])
        await force_custom_tags(full_path, track_meta)
        
        if upload: 
            await track_upload(track_meta, user, disable_link)
            
        return True
    except asyncio.CancelledError:
        raise
    except Exception as e:
        LOGGER.error(f"Error processing track {item_id}: {e}")
        return False

async def start_artist(albums, user, artist):
    artist_meta = await get_artist_meta(artist[0])
    artist_meta['folderpath'] = sanitize_filepath(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Qobuz/{artist[0]['name']}")
    artist_meta['albums'] = []

    upload_album = True
    _, _, artist_zip, _ = fetch_zip_settings(user)
    user_mode = bot_set.user_data.get(user['user_id'], {}).get('upload_mode', bot_set.upload_mode)
    
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
        except QobuzContentUnavailableError as e:
            LOGGER.warning(f"Melewati album ID {album['id']} pada artis {artist_meta['title']} karena tidak tersedia: {e}")
            continue

    if not artist_meta['albums']:
        raise QobuzContentUnavailableError("Tidak ada album dari artis ini yang berhasil diunduh di akun ini.")

    if not upload_album:
        await artist_upload(artist_meta, user)

async def start_playlist(tracks, playlist, user):
    client = user['qobuz_api']
    play_meta = await get_playlist_meta(playlist[0], tracks, user['r_id'], user)
    
    playlist_folder = None
    playlist_sort = False if bot_set.upload_mode == 'Telegram' else bot_set.playlist_sort
    
    if not playlist_sort:
        playlist_folder = sanitize_filepath(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Qobuz/{play_meta['title']}")
    play_meta['folderpath'] = playlist_folder
    
    try:
        track_meta = await client.get_track_url(play_meta['tracks'][0]['itemid'], user)
        if not track_meta or track_meta.get('sample'):
            raise QobuzContentUnavailableError("Akun ini hanya dapat mengunduh sampel (Region Block / Akun Free). Beralih akun...")
        _, play_meta['quality'] = await get_quality(track_meta, user)
    except asyncio.CancelledError:
        raise
    except QobuzContentUnavailableError as e:
        raise e
    except Exception:
        play_meta['quality'] = "Unknown"

    update_details = {'text': lang.s.DOWNLOAD_PROGRESS, 'msg': user.get('bot_msg'), 'title': play_meta['title'], 'type': play_meta['type']}
    play_meta['poster_msg'] = await post_art_poster(user, play_meta)

    playlist_zip, _, _, _ = fetch_zip_settings(user)
    limit_pekerja = Config.MAX_WORKERS if bot_set.playlist_conc else 1

    tasks = []
    for track in play_meta['tracks']: 
        tasks.append(start_track(track['itemid'], user, track, False, playlist_folder, bot_set.disable_sort_link, True))
    
    task_results = await run_concurrent_tasks(tasks, update_details, limit=limit_pekerja)
    
    successful_tracks = [play_meta['tracks'][i] for i, res in enumerate(task_results) if res is True]
    play_meta['tracks'] = successful_tracks
    play_meta['totaltracks'] = len(successful_tracks)

    if play_meta.get('cover') and os.path.exists(play_meta['cover']):
        try:
            shutil.copy2(play_meta['cover'], os.path.join(play_meta['folderpath'], "cover.jpg"))
        except Exception:
            pass

    if playlist_zip and playlist_sort: 
        play_meta['folderpath'] = await move_sorted_playlist(play_meta, user)
       
    if not play_meta['tracks']:
        raise QobuzContentUnavailableError("Tidak ada lagu pada playlist ini yang berhasil diunduh.")
        
    await playlist_upload(play_meta, user)
