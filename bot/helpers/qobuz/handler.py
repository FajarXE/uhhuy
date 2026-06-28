# [GANTI FILE: bot/helpers/qobuz/handler.py]

import shutil
import os
import traceback
from .utils import *
from config import Config
from pathvalidate import sanitize_filepath

from ..utils import *
from ..metadata import set_metadata
from ..message import edit_message, send_message
from bot.logger import LOGGER

# [IMPORT PENTING] Manager Qobuz Baru & Settings
from bot.settings import bot_set 
from bot.helpers.qobuz.qopy import qobuz_manager

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

# Exception kustom
try:
    from .utils import QobuzContentUnavailableError
except ImportError:
    class QobuzContentUnavailableError(Exception):
        pass

async def force_custom_tags(filepath, metadata):
    if not os.path.exists(filepath): return
    ext = filepath.split('.')[-1].lower()
    target_keys = ['creation_time', 'RELEASETIME', 'ORIGINALDATE']
    tags_to_write = {k: str(metadata[k]) for k in target_keys if metadata.get(k)}
    if not tags_to_write: return

    try:
        if ext == 'flac' and FLAC:
            try:
                audio = FLAC(filepath)
                for k, v in tags_to_write.items(): audio[k] = v
                audio.save()
            except: pass
        elif ext == 'mp3' and ID3:
            try:
                try: audio = ID3(filepath)
                except: audio = ID3(); audio.save(filepath)
                for k, v in tags_to_write.items(): audio.add(TXXX(encoding=3, desc=k, text=v))
                audio.save()
            except: pass
    except: pass

async def start_qobuz(url:str, user:dict):
    # 1. Ambil daftar klien global (dari config)
    global_clients_list = user.get('qobuz_clients_list', [])
    
    # 2. Ambil daftar klien PRIBADI (Multi-Akun dari Database)
    tg_user_id = user.get('user_id')
    private_clients = await qobuz_manager.get_user_clients(tg_user_id)
    
    # 3. Gabungkan: Private (Prioritas) -> Global
    # Bot akan mencoba akun pribadi user urut dari akun ke-1, ke-2, dst.
    final_clients_list = []
    
    if private_clients:
        LOGGER.info(f"User {tg_user_id} menggunakan {len(private_clients)} akun pribadi Qobuz.")
        final_clients_list.extend(private_clients)
        
    final_clients_list.extend(global_clients_list)

    if not final_clients_list:
        return await edit_message(user['bot_msg'], "Kesalahan: Tidak ada klien Qobuz aktif (Global/Private).")

    last_error = "Tidak ada error"
    
    # 4. Loop Semua Akun yang tersedia
    for i, client in enumerate(final_clients_list):
        user['qobuz_api'] = client
        
        # Labeling agar user tahu akun mana yang dipakai
        c_label = getattr(client, 'label', str(client.user_id))
        
        try:
            await edit_message(user['bot_msg'], f"Mencoba Akun #{i+1} ({c_label})...")
            
            items, item_id, type_dict, content = await check_type(url, user)
            
            if items is None and item_id is None:
                 raise QobuzContentUnavailableError("Gagal mendapatkan item/ID valid.")

            # Jika berhasil dapat konten, jalankan proses download
            if items is not None:
                if not items:
                    await edit_message(user['bot_msg'], f"Playlist/Artis kosong.")
                    return 
                if type_dict['iterable_key'] == 'albums': 
                    await start_artist(items, user, content)
                else: 
                    await start_playlist(items, content, user)
            else:
                if type_dict.get("album") is True: await start_album(item_id, user)
                elif type_dict.get("album") is False: await start_track(item_id, user, None)
                else: raise Exception(f"Tipe konten tidak diketahui.")
            
            # [PENTING] Jika sampai sini, berarti sukses. Return agar tidak loop ke akun lain.
            await edit_message(user['bot_msg'], f"Selesai memproses dengan Akun {c_label}.")
            return 

        except QobuzContentUnavailableError as e:
            # Error spesifik konten (misal region lock), coba akun berikutnya
            last_error = f"{e}"
            LOGGER.warning(f"Akun {c_label} gagal mengambil metadata (Mungkin Region Lock): {e}")
            continue 
        except Exception as e:
            # Error coding/fatal lainnya
            last_error = f"{e}"
            LOGGER.error(f"Fatal Error Qobuz (Start): {e}\n{traceback.format_exc()}")
            break 

    # --- [FIX] LEMPAR ERROR AGAR PESAN TIDAK DIHAPUS OLEH SISTEM UTAMA ---
    raise Exception(f"Gagal memproses dengan semua akun Qobuz yang tersedia. Error terakhir: {last_error}")
    # ---------------------------------------------------------------------

async def start_album(item_id:int, user:dict, upload=True, basefolder=None):
    client = user['qobuz_api']
    
    # Ambil metadata. Jika gagal, RAISE Error untuk trigger retry akun lain
    album_meta, err = await get_album_metadata(item_id, user['r_id'], user)
    if err:
        raise QobuzContentUnavailableError(f"Album tidak tersedia di akun ini ({err}).")
    
    # --- FITUR BARU: MODE BOOKLET ONLY ---
    if user.get('booklet_only'):
        await edit_message(user['bot_msg'], f"🔍 Mencari booklet untuk album: `{album_meta['title']}`...")
        
        if album_meta.get('booklet_url'):
            album_folder = basefolder + f"/{album_meta['title']}" if basefolder else f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
            album_folder = sanitize_filepath(album_folder)
            booklet_path = None
            
            try:
                # Pastikan direktori tersedia sebelum mengunduh
                os.makedirs(album_folder, exist_ok=True)
                
                temp_path = os.path.join(album_folder, "Booklet.pdf")
                if not await download_file(album_meta['booklet_url'], temp_path): 
                    booklet_path = temp_path
            except Exception as e:
                await edit_message(user['bot_msg'], f"❌ Gagal mengunduh booklet: {e}")
                return
            
            if booklet_path and os.path.exists(booklet_path):
                try: 
                    await user['bot_msg'].reply_document(
                        document=booklet_path, 
                        caption=f"**Booklet**: {album_meta['title']}", 
                        file_name=f"{album_meta['title']} - Booklet.pdf"
                    )
                    await edit_message(user['bot_msg'], "✅ Booklet berhasil dikirim! Tugas selesai.")
                except Exception as e:
                    await edit_message(user['bot_msg'], f"❌ Gagal mengirim file Telegram: {e}")
            else:
                await edit_message(user['bot_msg'], "❌ File booklet gagal diproses/rusak.")
        else:
            await edit_message(user['bot_msg'], f"❌ Tidak ada booklet digital yang dirilis untuk album ini.")
        
        # RETURN EARLY: Hentikan eksekusi di sini agar lagu tidak diunduh!
        return
    # -------------------------------------
    
    # Coba ambil sampel track
    try: 
        track_meta = await client.get_track_url(album_meta['tracks'][0]['itemid'], user)
    except: 
        try: 
            track_meta = await client.get_track_url(album_meta['tracks'][1]['itemid'], user)
        except: 
            raise QobuzContentUnavailableError(f"Gagal mendapatkan URL track sampel album.")
            
    # --- [FIX] CEK APAKAH AKUN HANYA MENDAPATKAN SAMPEL ---
    if track_meta and track_meta.get('sample'):
        raise QobuzContentUnavailableError("Akun ini hanya dapat mengunduh sampel (Region Block / Akun Free). Beralih akun...")
    # ------------------------------------------------------
            
    _, album_meta['quality'] = await get_quality(track_meta, user)
    
    if upload: album_meta['poster_msg'] = await post_art_poster(user, album_meta)

    album_folder = basefolder + f"/{album_meta['title']}" if basefolder else f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['provider']}/{album_meta['artist']}/{album_meta['title']}"
    album_folder = sanitize_filepath(album_folder)
    album_meta['folderpath'] = album_folder
    
    tasks = []
    for track in album_meta['tracks']:
        tasks.append(start_track(track['itemid'], user, track, False, album_folder))
        
    update_details = {'text': lang.s.DOWNLOAD_PROGRESS, 'msg': user['bot_msg'], 'title': album_meta['title'], 'type': album_meta['type']}
    
    # [FIX] Tambahkan limit agar Aria2 tidak tersedak!
    task_results = await run_concurrent_tasks(tasks, update_details, limit=Config.MAX_WORKERS)
    
    successful_tracks = [album_meta['tracks'][i] for i, res in enumerate(task_results) if res]
    album_meta['tracks'] = successful_tracks
    album_meta['totaltracks'] = len(successful_tracks)

    if not successful_tracks: 
        raise QobuzContentUnavailableError("Tidak ada lagu yang berhasil diunduh di album ini.")

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    
    # Booklet (Untuk pengunduhan album normal)
    booklet_path = None
    if album_meta.get('booklet_url'):
        try:
            temp_path = os.path.join(album_meta['folderpath'], "Booklet.pdf")
            if not await download_file(album_meta['booklet_url'], temp_path): booklet_path = temp_path
        except: pass

    if album_meta.get('cover') and os.path.exists(album_meta['cover']):
        try: shutil.copy2(album_meta['cover'], os.path.join(album_meta['folderpath'], "cover.jpg"))
        except: pass

    if booklet_path and os.path.exists(booklet_path):
        try: await user['bot_msg'].reply_document(document=booklet_path, caption="Booklet", file_name=f"Booklet.pdf")
        except: pass

    # Zipping otomatis diurus uploader.py agar muncul progress bar
    if upload: await album_upload(album_meta, user)

async def start_track(item_id:int, user:dict, track_meta:dict | None, upload=True, basefolder=None, disable_link=False, disable_msg=False):
    client = user['qobuz_api']

    is_single_track = track_meta is None
    
    if is_single_track:
        track_meta, err = await get_track_metadata(item_id, user['r_id'], None, user)
        if err: 
            # --- [FIX] PAKSA PINDAH AKUN JIKA METADATA DIBLOKIR ---
            raise QobuzContentUnavailableError(f"Gagal memuat metadata: {err}")
            
        filepath = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{track_meta['provider']}/{track_meta['albumartist']}/{track_meta['album']}"
        filepath = sanitize_filepath(filepath)
    else: 
        filepath = basefolder
    
    try:
        raw_data = await client.get_track_url(item_id, user)
        # --- [FIX] CEK SAMPEL PADA TRACK TUNGGAL ---
        if raw_data and raw_data.get('sample'):
            raise QobuzContentUnavailableError("Track hanya tersedia sebagai sampel (Region Block / Akun Free).")
        # -------------------------------------------
        url = raw_data['url']
    except QobuzContentUnavailableError as e:
        # Jika track ini diunduh sendirian, pindah akun!
        if is_single_track:
            raise e
        
        # Jika bagian dari album, skip lagu ini agar lagu lain yang tersedia tetap jalan
        from bot.logger import LOGGER
        LOGGER.warning(f"Track ID {item_id} hanya sampel (Region Block/Free). Skipping...")
        return False
    except Exception as e:
        from bot.logger import LOGGER
        LOGGER.warning(f"Gagal mendapatkan URL Track ID {item_id}: {e}. Skipping...")
        return False 
        
    try:
        track_meta['extension'], track_meta['quality'] = await get_quality(raw_data, user)
        raw_filename = await format_string(Config.TRACK_NAME_FORMAT, track_meta, user)
        
        # --- LOGIKA FOLDER DISC UNTUK MULTI-DISC ALBUM ---
        target_dir = filepath
        try:
            total_vol = int(track_meta.get('totalvolume', 1))
            # Jika total volume lebih dari 1, buat sub-folder "Disc X"
            if total_vol > 1:
                vol_num = track_meta.get('volume', '1')
                target_dir = f"{filepath}/Disc {vol_num}"
        except Exception:
            pass
        
        full_path = f"{target_dir}/{sanitize_filepath(raw_filename)}.{track_meta['extension']}"
        # -------------------------------------------------
        
        track_meta['filepath'] = full_path

        # --- [FIX UTAMA] SUNTIKAN RADAR ARIA2 ---
        details = None
        if upload and 'bot_msg' in user:
            task_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
            details = {
                'msg': user['bot_msg'],
                'title': track_meta.get('title', 'Unknown'),
                'type': track_meta.get('type', 'Track').capitalize(),
                'task_id': task_id
            }

        # Jalankan Aria2 dengan mengirimkan "details" UI
        err = await download_file(url, full_path, details=details)
        if err is not None:
            return False
        # ----------------------------------------
        
        await set_metadata(track_meta, user['user_id'])
        await force_custom_tags(full_path, track_meta)
        
        if upload: 
            await track_upload(track_meta, user, disable_link)
            
        return True
    except Exception as e:
        from bot.logger import LOGGER
        LOGGER.error(f"Error processing track {item_id}: {e}")
        return False

async def start_artist(albums, user, artist):
    artist_meta = await get_artist_meta(artist[0])
    artist_meta['folderpath'] = sanitize_filepath(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Qobuz/{artist[0]['name']}")

    upload_album = True
    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    
    if bot_set.artist_batch: upload_album = True if bot_set.upload_mode == 'Telegram' else False
    if artist_zip: upload_album = False 

    for album in albums: await start_album(album['id'], user, upload_album, artist_meta['folderpath'])

    if not upload_album:
        # Zipping otomatis diurus uploader.py
        await artist_upload(artist_meta, user)

async def start_playlist(tracks, playlist, user):
    client = user['qobuz_api']
    play_meta = await get_playlist_meta(playlist[0], tracks, user['r_id'], user)
    
    playlist_folder = None
    playlist_sort = False if bot_set.upload_mode == 'Telegram' else bot_set.playlist_sort
    
    if not playlist_sort:
        playlist_folder = sanitize_filepath(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Qobuz/{play_meta['title']}")
    play_meta['folderpath'] = playlist_folder
    
    # Coba ambil sampel kualitas
    try:
        track_meta = await client.get_track_url(tracks[0]['id'], user)
        # --- [FIX] CEK APAKAH AKUN HANYA MENDAPATKAN SAMPEL ---
        if track_meta and track_meta.get('sample'):
            raise QobuzContentUnavailableError("Akun ini hanya dapat mengunduh sampel (Region Block / Akun Free). Beralih akun...")
        # ------------------------------------------------------
        _, play_meta['quality'] = await get_quality(track_meta, user)
    except QobuzContentUnavailableError as e:
        raise e # Lemparkan ke luar agar memicu pergantian akun
    except:
        play_meta['quality'] = "Unknown"

    update_details = {'text': lang.s.DOWNLOAD_PROGRESS, 'msg': user['bot_msg'], 'title': play_meta['title'], 'type': play_meta['type']}
    play_meta['poster_msg'] = await post_art_poster(user, play_meta)

    # --- DETEKSI MODE UPLOAD ---
    upload = True
    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    
    user_id = user.get('user_id')
    raw_user_data = bot_set.user_data.get(user_id) or bot_set.user_data.get(str(user_id)) or {}
    user_mode = raw_user_data.get('upload_mode', 'Telegram')
    
    # Jika mode Cloud (Gofile/Buzz/Viking), matikan upload per track
    if user_mode.title() in ['Gofile', 'Buzzheavier', 'Vikingfiles']:
        upload = False

    # [FIX] SATUKAN LOGIC CONCURRENT & SEQUENTIAL MENGGUNAKAN RADAR PINTAR ARIA2
    if bot_set.playlist_conc:
        limit_pekerja = Config.MAX_WORKERS
    else:
        limit_pekerja = 1 # Sequential (Kerjakan 1 per 1 agar berurutan)

    tasks = []
    for track in play_meta['tracks']: 
        # PAKSA argumen upload menjadi False agar fokus mendownload seluruh playlist terlebih dahulu
        tasks.append(start_track(track['itemid'], user, track, False, playlist_folder, bot_set.disable_sort_link, True))
    
    # Radar Pintar akan otomatis membuat ID Cancel unik & memantau kecepatan Aria2!
    task_results = await run_concurrent_tasks(tasks, update_details, limit=limit_pekerja)
    
    successful_tracks = [play_meta['tracks'][i] for i, res in enumerate(task_results) if res]
    play_meta['tracks'] = successful_tracks
    play_meta['totaltracks'] = len(successful_tracks)

    # Copy Cover
    if play_meta.get('cover') and os.path.exists(play_meta['cover']):
        try: shutil.copy2(play_meta['cover'], os.path.join(play_meta['folderpath'], "cover.jpg"))
        except: pass

    # Sort Playlist jika diminta
    if playlist_zip and playlist_sort: 
        play_meta['folderpath'] = await move_sorted_playlist(play_meta, user)
       
    # SETELAH SEMUA LAGU SELESAI DIUNDUH, BARU LAKUKAN BATCH UPLOAD
    if not play_meta['tracks']:
        await edit_message(user['bot_msg'], "Gagal: Tidak ada lagu yang berhasil diunduh.")
        return
        
    # Zipping dan upload borongan diurus secara otomatis oleh uploader.py
    await playlist_upload(play_meta, user)
