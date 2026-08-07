# [GANTI SELURUH FILE: bot/helpers/moov/handler.py]

import os
import re
import shutil
import asyncio
import aiofiles
import hashlib
import traceback
import random
import aiohttp
from mutagen.flac import FLAC, Picture
from config import Config
from bot.logger import LOGGER
from ..message import edit_message
from .metadata import process_album_metadata, process_playlist_metadata, process_track_metadata
from ..uploder import album_upload, playlist_upload
from ..utils import (
    format_string, run_concurrent_tasks, zip_handler, 
    fetch_zip_settings, post_art_poster, download_file
)

SECRET_SALT = "F4:8E:09:CE:54:F7SeCrEtKkK"

def safe_name(name):
    return re.sub(r'[\/:*?"><|#]', '_', str(name)).strip()

async def start_moov(url: str, user: dict):
    clean_url = url.replace("#/", "/") 
    
    if "/album/" in clean_url:
        raw_id = clean_url.split("/album/")[-1]
        album_id = raw_id.split("?")[0].split("/")[0]
        await start_album(album_id, user)
        
    elif "/song/" in clean_url:
        raw_id = clean_url.split("/song/")[-1]
        track_id = raw_id.split("?")[0].split("/")[0]
        await start_track_single(track_id, user)

    elif "/chart/" in clean_url or "/playlist/" in clean_url:
        if "/chart/" in clean_url:
            raw_id = clean_url.split("/chart/")[-1]
        else:
            raw_id = clean_url.split("/playlist/")[-1]
            
        pid = raw_id.split("?")[0].split("/")[0]
        LOGGER.info(f"Moov: Terdeteksi Chart/Playlist ID: {pid}")
        await start_playlist(pid, user)

    elif "/share/" in clean_url and "/ADO/" in clean_url:
        try:
            parts = clean_url.split("/AUDIO/")
            left_part = parts[0].split("/ADO/")[-1]
            track_id = left_part.split("/")[0]
            right_part = parts[1]
            album_id = right_part.split("?")[0].split("/")[0]
            
            LOGGER.info(f"Share Link Parsed. Track: {track_id}, Album: {album_id}")
            await start_album(album_id, user, filter_track_id=track_id)
            
        except Exception as e:
            if "Gagal mengunduh" in str(e): raise e
            raise Exception(f"Gagal memparsing/memproses link Share Moov: {e}")
    else:
        raise Exception("Link Moov tidak dikenali. Mendukung: Album, Lagu, Chart, Playlist, dan Share Link.")

async def start_track_single(track_id, user):
    client = user['moov_api']
    try:
        track_data = await client.get_product_meta(track_id)
        if not track_data: raise Exception("Data lagu tidak ditemukan.")

        album_id = track_data.get('albumId') or track_data.get('album', {}).get('id')
        if not album_id: raise Exception("Gagal menemukan ID Album.")

        LOGGER.info(f"Downloading Single Track: {track_id} from Album: {album_id}")
        await start_album(album_id, user, filter_track_id=track_id)

    except Exception as e:
        raise Exception(f"Gagal memproses lagu: {e}")

async def start_album(album_id, user, upload=True, filter_track_id=None):
    client = user['moov_api']
    try:
        raw_data = await client.get_album_meta(album_id)
        if not raw_data: raise Exception("Metadata album kosong.")
        album_meta = await process_album_metadata(raw_data, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal metadata Moov: {e}")

    if filter_track_id:
        filtered_tracks = [
            t for t in album_meta['tracks'] 
            if str(t.get('itemid')) == str(filter_track_id)
        ]
        if not filtered_tracks:
            filtered_tracks = [
                t for t in album_meta['tracks'] 
                if str(filter_track_id) in str(t.get('itemid'))
            ]
        if not filtered_tracks:
            raise Exception(f"Lagu dengan ID {filter_track_id} tidak ditemukan di dalam album {album_id}.")
        album_meta['tracks'] = filtered_tracks

    base_dir = os.path.abspath(Config.DOWNLOAD_BASE_DIR)
    safe_artist = safe_name(album_meta['artist'])
    safe_title = safe_name(album_meta['title'])
    album_folder = os.path.join(base_dir, str(user['r_id']), "Moov", safe_artist, safe_title)
    
    album_meta['folderpath'] = album_folder

    if upload and not filter_track_id:
        try:
            # [FIX CAPTION] Tunggu dan simpan posternya ke dalam metadata!
            album_meta['poster_msg'] = await post_art_poster(user, album_meta)
        except Exception as e:
            LOGGER.error(f"Poster Error: {e}")

    tasks = []
    for track in album_meta['tracks']:
        # [FIX] Hapus turbo_mode karena sekarang menggunakan Aria2 murni
        tasks.append(download_track(track, user, album_folder))

    dl_type = 'Single Track' if filter_track_id else 'Album'
    
    ui_template = (
        "╭─ ᴘʀᴏɢʀᴇss\n"
        "│\n"
        "├ {0}\n"
        "│\n"
        "├ ᴅᴏɴᴇ : {1} / {2}\n"
        "│\n"
        "├ ᴛɪᴛʟᴇ : {3}\n"
        "│\n"
        "╰─ ᴛʏᴘᴇ : {4}"
    )
    
    update_details = {
        'text': ui_template,
        'msg': user['bot_msg'], 
        'title': album_meta['title'], 
        'type': dl_type
    }
    
    # [FIX] Pasang MAX_WORKERS agar rapi
    task_results = await run_concurrent_tasks(tasks, update_details, limit=Config.MAX_WORKERS)
    successful_tracks = [res for res in task_results if isinstance(res, dict) and res.get('filepath')]
    
    album_meta['tracks'] = successful_tracks
    
    if successful_tracks:
        if filter_track_id and len(successful_tracks) == 1:
            track_data = successful_tracks[0]
            album_meta.update(track_data)
            album_meta['tracks'] = successful_tracks
            album_meta['type'] = 'album'
    else:
        raise Exception("Gagal mengunduh lagu (Stream key kosong atau region blocked).")

    # Zipping dan upload diurus secara otomatis oleh uploader.py
    # agar Papan Global menampilkan transisi yang mulus tanpa kedipan!
    if upload:
        await album_upload(album_meta, user)

async def enrich_and_download_chart_track(shallow_track_meta, user, folderpath, album_cache):
    client = user['moov_api']
    track_id = shallow_track_meta.get('itemid')
    
    full_product = None
    album_id = None

    try:
        full_product = await client.get_product_meta(track_id)
        if full_product:
            album_id = full_product.get('albumId') or full_product.get('album', {}).get('id')
    except Exception: pass

    if not album_id:
        album_id = shallow_track_meta.get('moov_album_id')

    album_meta_full = None
    if album_id:
        if album_id in album_cache:
            album_meta_full = album_cache[album_id]
        else:
            try:
                raw_album = await client.get_album_meta(album_id)
                if raw_album:
                    album_meta_full = await process_album_metadata(raw_album, user['r_id'], user)
                    album_cache[album_id] = album_meta_full 
            except Exception as e: pass

    deep_meta = None

    if full_product:
        deep_meta = await process_track_metadata(
            full_product, 
            user['r_id'], 
            user, 
            cover=album_meta_full['cover'] if album_meta_full else None,
            album_meta=album_meta_full if album_meta_full else None
        )
    else:
        deep_meta = shallow_track_meta.copy()
        if album_meta_full:
            if album_meta_full.get('cover'): deep_meta['cover'] = album_meta_full['cover']
            if album_meta_full.get('label'): deep_meta['label'] = album_meta_full['label']
            if album_meta_full.get('date'):
                deep_meta['date'] = album_meta_full['date']
                deep_meta['year'] = album_meta_full['year']
            if album_meta_full.get('copyright'): deep_meta['copyright'] = album_meta_full['copyright']
            if album_meta_full.get('totaltracks'): deep_meta['totaltracks'] = album_meta_full['totaltracks']
            if album_meta_full.get('totalvolumes'): deep_meta['totalvolumes'] = album_meta_full['totalvolumes']
            if album_meta_full.get('upc'): deep_meta['upc'] = album_meta_full.get('upc')
            if album_meta_full.get('ean'): deep_meta['ean'] = album_meta_full.get('ean')

    deep_meta['folderpath'] = folderpath
    # [FIX] Hapus turbo_mode, otomatis menggunakan Aria2
    return await download_track(deep_meta, user, folderpath)

async def start_playlist(pid, user):
    client = user['moov_api']
    try:
        raw_data = await client.get_playlist_meta(pid)
        if not raw_data: raise Exception("Metadata playlist/chart kosong.")
        pl_meta = await process_playlist_metadata(raw_data, user['r_id'], user)
    except Exception as e:
        raise Exception(f"Gagal mengambil metadata Playlist/Chart: {e}")

    if not pl_meta.get('tracks'):
         raise Exception("Playlist/Chart ini kosong atau format tidak didukung.")

    base_dir = os.path.abspath(Config.DOWNLOAD_BASE_DIR)
    safe_title = safe_name(pl_meta['title'])
    pl_folder = os.path.join(base_dir, str(user['r_id']), "Moov", "Playlists", safe_title)
    pl_meta['folderpath'] = pl_folder

    try:
        # [FIX CAPTION] Tunggu dan simpan posternya ke dalam metadata!
        pl_meta['poster_msg'] = await post_art_poster(user, pl_meta)
    except: pass

    album_cache = {} 
    tasks = []
    
    for track in pl_meta['tracks']:
        tasks.append(enrich_and_download_chart_track(track, user, pl_folder, album_cache))

    ui_template = (
        "╭─ ᴘʀᴏɢʀᴇss\n"
        "│\n"
        "├ {0}\n"
        "│\n"
        "├ ᴅᴏɴᴇ : {1} / {2}\n"
        "│\n"
        "├ ᴛɪᴛʟᴇ : {3}\n"
        "│\n"
        "╰─ ᴛʏᴘᴇ : {4}"
    )

    update_details = {
        'text': ui_template, 
        'msg': user['bot_msg'], 
        'title': pl_meta['title'], 
        'type': 'Playlist'
    }
    
    # [FIX] Pasang MAX_WORKERS agar rapi
    task_results = await run_concurrent_tasks(tasks, update_details, limit=Config.MAX_WORKERS)
    successful_tracks = [res for res in task_results if isinstance(res, dict) and res.get('filepath')]
    
    pl_meta['tracks'] = successful_tracks
    if not successful_tracks:
        raise Exception("Gagal mengunduh semua lagu dari Playlist ini (Cek Log untuk detail).")

    # Zipping dan upload diurus secara otomatis oleh uploader.py
    # agar Papan Global menampilkan transisi yang mulus tanpa kedipan!
    await playlist_upload(pl_meta, user)

async def apply_mutagen_tags(filepath, meta, cover_path, lyrics=None):
    try:
        audio = FLAC(filepath)
        audio.delete() 
        
        # --- BASIC ---
        if meta.get('title'): audio['TITLE'] = meta.get('title')
        if meta.get('artist'): 
            audio['ARTIST'] = meta.get('artist')
            audio['PERFORMER'] = meta.get('artist')
        if meta.get('albumartist'): audio['ALBUMARTIST'] = meta.get('albumartist')
        if meta.get('album'): audio['ALBUM'] = meta.get('album')
        if meta.get('genre'): audio['GENRE'] = meta.get('genre')
        if meta.get('composer'): audio['COMPOSER'] = meta.get('composer')
        if meta.get('producer'): audio['PRODUCER'] = meta.get('producer')
        
        # --- COPYRIGHT ---
        final_cpr = meta.get('copyright')
        if not final_cpr: final_cpr = meta.get('label')
             
        if final_cpr:
            audio['COPYRIGHT'] = str(final_cpr)
            audio['RIGHTS'] = str(final_cpr) 

        if meta.get('label'):
            audio['ORGANIZATION'] = meta.get('label')
            audio['LABEL'] = meta.get('label')
            audio['PUBLISHER'] = meta.get('label') 

        # --- TRACK/DISC ---
        if meta.get('tracknumber'): audio['TRACKNUMBER'] = str(meta.get('tracknumber'))
        if meta.get('disk'): audio['DISCNUMBER'] = str(meta.get('disk'))
        
        t_tracks = meta.get('totaltracks')
        if t_tracks and str(t_tracks) != 'None':
            audio['TRACKTOTAL'] = str(t_tracks)
            audio['TOTALTRACKS'] = str(t_tracks)
        
        t_vols = meta.get('totalvolumes')
        if t_vols and str(t_vols) != 'None':
            audio['DISCTOTAL'] = str(t_vols)
            audio['TOTALDISCS'] = str(t_vols)

        # --- DATES ---
        if meta.get('date'):
            d = str(meta.get('date'))
            audio['DATE'] = d
            audio['YEAR'] = d[:4]
            audio['ORIGINALDATE'] = d
            audio['RELEASEDATE'] = d

        # --- ISRC ---
        if meta.get('isrc'):
            audio['ISRC'] = str(meta.get('isrc'))

        # --- BARCODE ---
        upc_val = meta.get('upc') or meta.get('ean') or meta.get('barcode')
        if upc_val:
            val = str(upc_val)
            audio['BARCODE'] = val
            audio['UPC'] = val
            audio['EAN'] = val

        # --- EXPLICIT ---
        if meta.get('explicit') == "True":
            audio['ITUNESADVISORY'] = '1'
            audio['RATING'] = 'Explicit'
        else:
            audio['ITUNESADVISORY'] = '0'

        # --- LYRICS ---
        if lyrics and isinstance(lyrics, str) and len(lyrics) > 10:
            audio['LYRICS'] = lyrics
            audio['UNSYNCEDLYRICS'] = lyrics 
        
        # --- COVER ---
        if cover_path and os.path.exists(cover_path):
            try:
                p = Picture()
                with open(cover_path, 'rb') as f:
                    p.data = f.read()
                p.type = 3 
                p.mime = 'image/jpeg'
                p.desc = 'Front Cover'
                audio.add_picture(p)
            except: pass
            
        audio.save()
        return int(audio.info.length)
        
    except Exception as e:
        LOGGER.error(f"Mutagen Error: {e}")
        return 0

# --- HYBRID DOWNLOADER ---
async def download_track(track_meta, user, folderpath):
    meta = track_meta.copy()
    client = user['moov_api']
    
    if not meta.get('itemid'): return False

    file_meta = None
    target_quality = meta.get('moov_quality_code', 'LL')
    album_context_id = meta.get('moov_album_id')

    # STEP 1: API Checkout
    try:
        file_meta = await client.get_track_file_meta(
            meta['itemid'], target_quality, album_id=album_context_id
        )
    except Exception as e:
        LOGGER.warning(f"Moov Stream Check Error ({target_quality}): {e}")

    if not file_meta and target_quality != 'LL':
        try:
            file_meta = await client.get_track_file_meta(
                meta['itemid'], 'LL', album_id=album_context_id
            )
            if file_meta: meta['quality'] = 'FLAC 16bit' 
        except: pass

    if not file_meta:
        return False
        
    play_url = file_meta.get('playUrl')
    content_key = file_meta.get('contentKey')
    if not play_url or not content_key: return False

    # STEP 2: Key Processing
    key_bytes = None
    try:
        m = hashlib.md5()
        m.update((content_key + SECRET_SALT).encode('UTF-8'))
        key_bytes = bytes.fromhex(m.hexdigest())
    except Exception as e: return False

    try:
        raw_filename = await format_string(Config.TRACK_NAME_FORMAT, meta, user)
        safe_filename = safe_name(raw_filename)
        
        track_temp_dir = os.path.join(folderpath, f"temp_{meta['itemid']}")
        if os.path.exists(track_temp_dir): shutil.rmtree(track_temp_dir)
        os.makedirs(track_temp_dir, exist_ok=True)

        final_filepath = os.path.join(folderpath, f"{safe_filename}.flac")
        
        key_filepath = os.path.join(track_temp_dir, "key.bin")
        async with aiofiles.open(key_filepath, 'wb') as f:
            await f.write(key_bytes)

        # COVER
        cover_local_path = None
        target_url = meta.get('cover_url')
        if target_url:
            cover_local_path = os.path.join(track_temp_dir, "cover.jpg")
            try:
                import aiohttp
                headers = {'User-Agent': 'Mozilla/5.0'}
                async with aiohttp.ClientSession() as session:
                    async with session.get(target_url, headers=headers, timeout=30) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            async with aiofiles.open(cover_local_path, 'wb') as f:
                                await f.write(data)
                        else: cover_local_path = None
            except: cover_local_path = None
        
        if not cover_local_path and meta.get('cover') and os.path.exists(meta.get('cover')):
            cover_local_path = os.path.join(track_temp_dir, "cover_fallback.jpg")
            shutil.copy(meta['cover'], cover_local_path)

        # STEP 3: M3U8
        hls_headers = {'User-Agent': 'Moov-Android/1.0/hls-hr'} 
        m3u8_content = None
        
        for _ in range(3): 
            try:
                async with client.session.get(play_url, headers=hls_headers) as resp:
                    if resp.status == 200: 
                        m3u8_content = await resp.text()
                        break
                    else: pass
            except: await asyncio.sleep(1)
        
        if not m3u8_content:
            shutil.rmtree(track_temp_dir)
            return False

        target_duration = 10
        media_sequence = 0
        for line in m3u8_content.splitlines():
            if line.startswith("#EXT-X-TARGETDURATION"):
                target_duration = line.split(":")[1].strip()
            if line.startswith("#EXT-X-MEDIA-SEQUENCE"):
                media_sequence = int(line.split(":")[1].strip())

        remote_segments = [line.strip() for line in m3u8_content.splitlines() if line and not line.startswith('#')]
        local_segment_names = []
        
        # --- STEP 4: AIOHTTP TURBO ENGINE (SUPER CEPAT UNTUK HLS) ---
        # Kita membuang Aria2 karena overhead RPC-nya membuat unduhan HLS menjadi sangat lambat.
        # Sebagai gantinya, kita gunakan 32 koneksi Python murni untuk menyedot pecahan lagu sekaligus!
        semaphore = asyncio.Semaphore(32)
        seg_tasks = []
        
        async def turbo_segment_worker(url, path, headers_dict, sem):
            async with sem:
                for attempt in range(4): # Coba ulang hingga 4x jika gagal
                    try:
                        async with client.session.get(url, headers=headers_dict, timeout=30) as resp:
                            if resp.status == 200:
                                data = await resp.read()
                                async with aiofiles.open(path, 'wb') as f:
                                    await f.write(data)
                                return True
                    except:
                        pass
                    await asyncio.sleep(0.5) # Jeda sedikit sebelum mencoba lagi
                return False

        for index, seg_url in enumerate(remote_segments):
            seg_name = f"seg_{index:04d}.flac"
            seg_path = os.path.join(track_temp_dir, seg_name)
            local_segment_names.append(seg_name)
            seg_tasks.append(turbo_segment_worker(seg_url, seg_path, hls_headers, semaphore))
            
        seg_results = await asyncio.gather(*seg_tasks)
        
        if not all(seg_results):
            LOGGER.error("Moov Turbo Mode: Gagal mengunduh beberapa segmen.")
            shutil.rmtree(track_temp_dir)
            return False
        # ------------------------------------------------------------

        # Local M3U8 Gen
        local_m3u8_path = os.path.join(track_temp_dir, "local.m3u8")
        iv_line = ""
        iv_match = re.search(r'IV=0x([0-9a-fA-F]+)', m3u8_content)
        if iv_match: iv_line = f",IV=0x{iv_match.group(1)}"
            
        async with aiofiles.open(local_m3u8_path, 'w') as f:
            await f.write("#EXTM3U\n")
            await f.write("#EXT-X-VERSION:3\n")
            await f.write(f"#EXT-X-TARGETDURATION:{target_duration}\n")
            await f.write(f"#EXT-X-MEDIA-SEQUENCE:{media_sequence}\n")
            await f.write(f'#EXT-X-KEY:METHOD=AES-128,URI="key.bin"{iv_line}\n')
            for seg_name in local_segment_names:
                await f.write(f"#EXTINF:{target_duration},\n")
                await f.write(f"{seg_name}\n")
            await f.write("#EXT-X-ENDLIST\n")

        # STEP 5: FFmpeg Optimized (Menjahit segmen hasil Aria2)
        cmd = [
            'ffmpeg', '-y',
            '-allowed_extensions', 'ALL',
            '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
            '-threads', '0',      
            '-i', local_m3u8_path,
            '-c', 'flac', 
            final_filepath
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        
        if process.returncode != 0:
            LOGGER.error(f"FFmpeg Error: {stderr.decode()}")
            shutil.rmtree(track_temp_dir)
            return False

        if not os.path.exists(final_filepath) or os.path.getsize(final_filepath) == 0:
            return False
            
        meta['filesize'] = os.path.getsize(final_filepath)
        meta['filepath'] = os.path.abspath(final_filepath)
        meta['filename'] = os.path.basename(final_filepath)
        meta['is_downloaded'] = True

        # STEP 6: Lyrics & Tags
        lyrics_text = None
        try:
            track_id = str(meta.get('itemid', ''))
            if track_id: lyrics_text = await client.get_lyrics(track_id)
        except: pass

        real_duration = await apply_mutagen_tags(final_filepath, meta, cover_local_path, lyrics=lyrics_text)
        if real_duration > 0: meta['duration'] = real_duration
            
        if cover_local_path and os.path.exists(cover_local_path):
            album_cover_path = os.path.join(folderpath, "cover.jpg")
            if not os.path.exists(album_cover_path):
                shutil.copy(cover_local_path, album_cover_path)
            meta['cover'] = album_cover_path
        else:
            meta['cover'] = None

        if lyrics_text and isinstance(lyrics_text, str):
            try:
                lrc_path = final_filepath.rsplit('.', 1)[0] + ".lrc"
                async with aiofiles.open(lrc_path, 'w', encoding='utf-8') as f:
                    await f.write(lyrics_text)
            except: pass

        shutil.rmtree(track_temp_dir)

    except Exception as e:
        LOGGER.error(f"DL Crash: {e}\n{traceback.format_exc()}")
        if os.path.exists(track_temp_dir): shutil.rmtree(track_temp_dir)
        return False
        
    return meta
