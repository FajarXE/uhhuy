# [FILE: bot/helpers/amazon/handler.py]

import asyncio
import os
import base64
import shutil
import aiohttp
import urllib.parse as urlparse
from pathvalidate import sanitize_filepath
from bot.logger import LOGGER
from config import Config
from .manager import amazon_manager
from bot.helpers.aria2_helper import aria2_download

# --- IMPORT EKOSISTEM UTAMA BOT ---
from bot.settings import bot_set
import bot.helpers.translations as lang
from bot.helpers.uploder import track_upload, album_upload
from bot.helpers.utils import run_concurrent_tasks, fetch_zip_settings, post_art_poster
from bot.helpers.message import edit_message
# ----------------------------------

def generate_challenge(kid, prd_path):
    from bot.helpers.amazon.drm.pypr import PlayReadyHeaderBuilder, PSSH, Device, Cdm
    kid_clean = kid.replace("-", "")
    builder = PlayReadyHeaderBuilder(kid_clean)
    header = builder.build_header(version="4.0", header_spec=None, encryption_scheme="cenc", key_specs=[(kid_clean, kid_clean)])
    playready_header = base64.b64encode(header).decode("ascii")
    
    device = Device.load(prd_path)
    cdm = Cdm.from_device(device)
    session_id = cdm.open()
    
    pssh_obj = PSSH(playready_header)
    challenge = cdm.get_license_challenge(session_id, pssh_obj.wrm_headers[0])
    challenge_b64 = base64.b64encode(challenge.encode("utf-8")).decode("utf-8")
    
    return cdm, session_id, challenge_b64

def parse_license_and_get_keys(cdm, session_id, license_b64):
    decoded_data = base64.b64decode(license_b64).decode("utf-8")
    cdm.parse_license(session_id, decoded_data)
    keys = []
    for key in cdm.get_keys(session_id):
        keys.append(f"{key.key_id.hex}:{key.key.hex()}")
    cdm.close(session_id)
    return keys

async def get_global_asin(url: str, current_asin: str) -> str:
    """Mengunjungi tautan secara anonim untuk mengekstrak ASIN Global (Shared Catalog)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            # Kunjungi web tanpa cookie/token apapun (Mode Incognito)
            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    import re
                    
                    # 1. Cari ASIN Global di URL Canonical / OpenGraph
                    matches = re.findall(r'(?:albums|tracks|playlists)/(B0[A-Z0-9]{8})', html)
                    if matches:
                        LOGGER.info(f"Amazon Scraper: Menemukan ASIN Global dari URL -> {matches[0]}")
                        return matches[0]
                        
                    # 2. Fallback: Cari ASIN Global di dalam state JSON halaman
                    matches_json = re.findall(r'"asin":"(B0[A-Z0-9]{8})"', html)
                    if matches_json:
                        LOGGER.info(f"Amazon Scraper: Menemukan ASIN Global dari JSON -> {matches_json[0]}")
                        return matches_json[0]
    except Exception as e:
        LOGGER.debug(f"Amazon Scraper Gagal (Abaikan): {e}")
        pass
        
    # Jika gagal mencuri (misal karena diblokir WAF/Captcha), kembalikan ASIN aslinya
    return current_asin

async def amazon_convert_only(input_path, final_path):
    import shutil
    import os
    
    # --- 1. JALAN PINTAS UNTUK ATMOS / 360RA (.m4a) ---
    if final_path.lower().endswith('.m4a'):
        LOGGER.info(f"Amazon Bypass FFmpeg: Memindahkan langsung kontainer asli untuk {final_path}")
        shutil.move(input_path, final_path)
        return
    # --------------------------------------------------

    # --- 2. PENANGANAN FALLBACK FLAC & SD ---
    # Perhatikan bagian ini! Kita WAJIB memasukkan "final_path" di ujung array `cmd`
    if final_path.lower().endswith('.flac'):
        # Jika Amazon mengembalikan FLAC, paksa FFmpeg untuk merakit ulang (-c:a flac)
        cmd = ['ffmpeg', '-y', '-i', input_path, '-map', '0:a:0', '-c:a', 'flac', final_path]
    else:
        # Untuk format standar lainnya
        cmd = ['ffmpeg', '-y', '-i', input_path, '-map', '0:a:0', '-c:a', 'copy', final_path]
    
    LOGGER.info(f"Amazon FFmpeg CMD: {' '.join(cmd)}")
    
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    
    if proc.returncode != 0:
        LOGGER.error(f"FFmpeg gagal: {stderr.decode()}")
        # PENTING: Hapus file mentah (.dec.mp4) jika FFmpeg gagal 
        # agar tidak menjadi sampah ganda yang menyusup ke dalam file ZIP!
        try:
            os.remove(input_path)
        except:
            pass
        raise Exception("Gagal mengekstrak audio dari kontainer (FFmpeg Error).")

async def start_amazon(url: str, user: dict):
    parsed = urlparse.urlparse(url)
    qs = urlparse.parse_qs(parsed.query)
    
    if 'trackAsin' in qs:
        asin = qs['trackAsin'][0]
        await start_track(asin, user, url)
        return
    
    asin = parsed.path.strip('/').split('/')[-1]
    
    if '/albums/' in parsed.path or '/album/' in parsed.path:
        await start_album(asin, user, url)
    # --- TAMBAHKAN RUTE PLAYLIST DI SINI ---
    elif '/playlists/' in parsed.path or '/playlist/' in parsed.path:
        await start_playlist(asin, user, url)
    # ---------------------------------------
    else:
        await start_track(asin, user, url)

async def start_playlist(playlist_asin: str, user: dict, url: str):
    playlist_asin = await get_global_asin(url, current_asin=playlist_asin)
    LOGGER.info(f"Amazon: Mengambil info Playlist {playlist_asin}")
    user_id = user.get('user_id')
    client = user.get('amazon_api') or amazon_manager.get_client(user_id, url=url)
    
    if not client:
        raise Exception("Tidak ada klien Amazon Music yang aktif.")

    device_id = client.tokens.get('device_id')
    device_type_id = client.tokens.get('deviceTypeId') or "A1KAXIG6VXSG8Y"
    lookup_base = client.base_url
    api_loc = client.api_location
    music_territory = client.region.upper()

    lookup_url = f"{lookup_base}{api_loc}/api/muse/legacy/lookup"
    
    lookup_headers = {
        "X-Amz-Target": "com.amazon.musicensembleservice.MusicEnsembleService.lookup",
        "x-amzn-device-type-id": device_type_id,
        "x-amzn-hardware-device-type-id": device_type_id
    }
    
    track_asins = []
    playlist_title = "Unknown Playlist"
    playlist_owner = "Amazon Music"
    playlist_cover = ""
    
    enum_options = ["MUSIC_SUBSCRIPTION", "FULL_CATALOG"]
    
    for req_content in enum_options:
        lookup_payload = {
            "asins": [playlist_asin],
            "features": ["popularity", "expandTracklist", "trackLibraryAvailability", "collectionLibraryAvailability"],
            "requestedContent": req_content, 
            "musicTerritory": music_territory, 
            "deviceId": device_id,
            "deviceType": device_type_id
        }
        
        try:
            async with client.session.post(lookup_url, json=lookup_payload, headers=lookup_headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Targetkan playlistList, bukan albumList
                    for pl in data.get("playlistList", []):
                        playlist_title = pl.get("title", playlist_title)
                        playlist_owner = pl.get("author", pl.get("owner", playlist_owner))
                        playlist_cover = pl.get("image", playlist_cover)
                        
                        for track in pl.get("tracks", []):
                            if isinstance(track, dict) and track.get("asin"):
                                track_asins.append(track["asin"])
                                
            track_asins = list(dict.fromkeys(track_asins))
            
            if track_asins:
                LOGGER.info(f"Amazon: Berhasil mendapat {len(track_asins)} lagu Playlist dari Region {music_territory} ({req_content})")
                break
        except Exception as e:
            continue
            
    if not track_asins:
        raise Exception(f"Amazon tidak mengembalikan daftar lagu untuk playlist {playlist_asin}. Pastikan link valid.")

    if 'bot_msg' in user:
        await edit_message(user['bot_msg'], f"💽 **Playlist Ditemukan!**\nMemulai unduhan {len(track_asins)} lagu...")

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS, 
        'msg': user.get('bot_msg'), 
        'title': playlist_title, 
        'type': 'Playlist'
    }
    
    tasks = []
    total_lagu = len(track_asins)
    for index, t_asin in enumerate(track_asins, start=1):
        # Paksa nama album menjadi nama Playlist, dan artis album menjadi pembuat Playlist
        tasks.append(start_track(
            t_asin, user, url, upload=False, 
            forced_track_num=index, forced_total_tracks=total_lagu, 
            forced_album_title=playlist_title, forced_album_artist=playlist_owner
        ))
        
    limit_pekerja = Config.MAX_WORKERS if getattr(bot_set, 'playlist_conc', True) else 1
    task_results = await run_concurrent_tasks(tasks, update_details, limit=limit_pekerja)
    
    playlist_tracks = []
    for index, res in enumerate(task_results, start=1):
        if isinstance(res, dict):
            playlist_tracks.append(res)
        else:
            LOGGER.error(f"Amazon [Playlist Track {index}] GAGAL DIUNDUH! Penyebab: {res}")

    if not playlist_tracks:
         raise Exception("Semua lagu dalam playlist gagal diunduh.")

    playlist_folder = playlist_tracks[0].get('folderpath', '') if playlist_tracks else ''
    sample_track = playlist_tracks[0] if playlist_tracks else {}
    
    safe_cover = playlist_tracks[0].get('cover', '')
    if safe_cover and not os.path.exists(safe_cover):
        safe_cover = ''
        
    is_explicit = any("[explicit]" in str(t.get('title', '')).lower() for t in playlist_tracks)

    playlist_metadata = {
        'type': 'playlist',
        'title': playlist_title,
        'album': playlist_title,
        'artist': playlist_owner,
        'albumartist': playlist_owner,
        'folderpath': playlist_folder,
        'tracks': playlist_tracks,
        'provider': 'Amazon Music',
        'cover': safe_cover,  
        'quality': sample_track.get('quality', 'UHD'),
        'release_date': sample_track.get('release_date', 'Unknown'),
        'date': sample_track.get('release_date', 'Unknown')[:4] if sample_track.get('release_date') else 'Unknown',
        'totaltracks': str(len(playlist_tracks)),
        'totalvolume': '1',    
        'total_volumes': '1',  
        'explicit': str(is_explicit)     
    }

    if playlist_metadata.get('cover') and os.path.exists(playlist_metadata['cover']):
        try:
            shutil.copy2(playlist_metadata['cover'], os.path.join(playlist_folder, "cover.jpg"))
        except:
            pass
    
    poster_msg = await post_art_poster(user, playlist_metadata)
    
    if poster_msg:
        playlist_metadata['poster_msg'] = poster_msg
    else:
        playlist_metadata['poster_msg'] = user.get('bot_msg')
        
    from bot.helpers.uploder import playlist_upload
    await playlist_upload(playlist_metadata, user)

async def start_album(album_asin: str, user: dict, url: str):
    # --- FIX: CURI ASIN GLOBAL SEBELUM MEMANGGIL API ---
    album_asin = await get_global_asin(url, current_asin=album_asin)
    # ---------------------------------------------------
    LOGGER.info(f"Amazon: Mengambil info Album {album_asin}")
    user_id = user.get('user_id')
    # --- FIX: Paksa Manager membaca URL agar tidak salah region ---
    client = user.get('amazon_api') or amazon_manager.get_client(user_id, url=url)
    # -------------------------------------------------------------
    
    if not client:
        raise Exception("Tidak ada klien Amazon Music yang aktif.")

    device_id = client.tokens.get('device_id')
    device_type_id = client.tokens.get('deviceTypeId') or "A1KAXIG6VXSG8Y"
    
    domain = urlparse.urlparse(url).netloc.lower()
    
    # --- FIX: PERCAYAKAN 100% PADA REGION AKUN (JANGAN TERTIPU DOMAIN URL) ---
    lookup_base = client.base_url
    api_loc = client.api_location
    music_territory = client.region.upper()
    
    # (Seluruh blok 'if amazon.fr in domain' hingga 'elif amazon.com in domain' DIHAPUS)
    # ------------------------------------------------------------------------

    lookup_url = f"{lookup_base}{api_loc}/api/muse/legacy/lookup"
    
    lookup_headers = {
        "X-Amz-Target": "com.amazon.musicensembleservice.MusicEnsembleService.lookup",
        "x-amzn-device-type-id": device_type_id,
        "x-amzn-hardware-device-type-id": device_type_id
    }
    
    track_asins = []
    album_title = "Unknown Album"
    album_artist = "Unknown Artist"
    album_cover = ""
    
    enum_options = ["MUSIC_SUBSCRIPTION", "FULL_CATALOG"]
    
    for req_content in enum_options:
        lookup_payload = {
            "asins": [album_asin],
            "features": ["popularity", "expandTracklist", "trackLibraryAvailability", "collectionLibraryAvailability"],
            "requestedContent": req_content, 
            "musicTerritory": music_territory, 
            "deviceId": device_id,
            "deviceType": device_type_id
        }
        
        try:
            async with client.session.post(lookup_url, json=lookup_payload, headers=lookup_headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    for album in data.get("albumList", []):
                        album_title = album.get("title", album_title)
                        album_artist = album.get("primaryArtistName", album_artist)
                        album_cover = album.get("image", album_cover)
                        
                        for track in album.get("tracks", []):
                            if isinstance(track, dict) and track.get("asin"):
                                track_asins.append(track["asin"])
                                
                    if not track_asins:
                        for track in data.get("trackList", []):
                            if isinstance(track, dict) and track.get("asin"):
                                track_asins.append(track["asin"])
                                
            track_asins = list(dict.fromkeys(track_asins))
            
            if track_asins:
                LOGGER.info(f"Amazon: Berhasil mendapat {len(track_asins)} lagu dari Region {music_territory} ({req_content})")
                break
        except Exception as e:
            continue
            
    if not track_asins:
        raise Exception(f"Amazon tidak mengembalikan daftar lagu untuk album {album_asin}. Pastikan link valid.")

    if 'bot_msg' in user:
        await edit_message(user['bot_msg'], f"💿 **Data Ditemukan!**\nMemulai unduhan {len(track_asins)} lagu...")

    # --- PERBAIKAN: GUNAKAN RUN_CONCURRENT_TASKS ALA QOBUZ ---
    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS, 
        'msg': user.get('bot_msg'), 
        'title': album_title, 
        'type': 'Album'
    }
    
    # --- FIX: Paksa penomoran dan NAMA ALBUM sesuai urutan indeks di album ---
    tasks = []
    total_lagu = len(track_asins)
    for index, t_asin in enumerate(track_asins, start=1):
        # Panggil start_track dengan upload=False agar tidak membuat UI "Download Track" mandiri
        # Kirimkan indeks asli dan nama album utama!
        tasks.append(start_track(
            t_asin, user, url, upload=False, 
            forced_track_num=index, forced_total_tracks=total_lagu, forced_album_title=album_title
        ))
    # ------------------------------------------------------------
        
    # Konfigurasi batas paralel (Sequential vs Concurrent)
    limit_pekerja = Config.MAX_WORKERS if getattr(bot_set, 'playlist_conc', True) else 1
    
    # Eksekusi paralel yang membungkus UI menjadi "Downloading Album"
    task_results = await run_concurrent_tasks(tasks, update_details, limit=limit_pekerja)
    
    # --- FIX: BONGKAR KEGAGALAN DIAM-DIAM (SILENT FAIL) ---
    album_tracks = []
    for index, res in enumerate(task_results, start=1):
        if isinstance(res, dict):
            album_tracks.append(res)
        else:
            # Jika 'res' bukan dictionary, berarti itu adalah Exception/Error!
            # (Baris import LOGGER sudah dihapus dari sini)
            LOGGER.error(f"Amazon [Track {index}] GAGAL DIUNDUH! Penyebab: {res}")
    # --------------------------------------------------------

    # Penyiapan Folder & Cover
    album_folder = album_tracks[0].get('folderpath', '') if album_tracks else ''
    sample_track = album_tracks[0] if album_tracks else {}
    
    # --- JARING PENGAMAN: Validasi Fisik Cover ---
    safe_cover = sample_track.get('cover', '')
    if safe_cover and not os.path.exists(safe_cover):
        safe_cover = ''
    # ---------------------------------------------
        
    try:
        max_disc = max(int(t.get('discnumber', 1)) for t in album_tracks)
    except:
        max_disc = 1

    # 1. Update setiap lagu dengan total_volume yang akurat dari kalkulasi album
    for t in album_tracks:
        t['totalvolume'] = str(max_disc)

    # 2. Deteksi otomatis label Explicit dari judul Album atau Lagu
    is_explicit = "[explicit]" in album_title.lower() or any("[explicit]" in str(t.get('title', '')).lower() for t in album_tracks)

    album_metadata = {
        'type': 'album',
        'title': album_title,
        'album': album_title,
        'artist': album_artist,
        'albumartist': album_artist,
        'folderpath': album_folder,
        'tracks': album_tracks,
        'provider': 'Amazon Music',
        'cover': safe_cover,  
        'quality': sample_track.get('quality', 'UHD'),
        'release_date': sample_track.get('release_date', 'Unknown'),
        'date': sample_track.get('release_date', 'Unknown')[:4] if sample_track.get('release_date') else 'Unknown',
        'totaltracks': str(len(album_tracks)),
        
        # --- FIX: Injeksi Variabel Poster ---
        'totalvolume': str(max_disc),    
        'total_volumes': str(max_disc),  
        'explicit': str(is_explicit)     
    }

    # --- FIX: COPY COVER KE DALAM FOLDER AGAR IKUT TER-ZIP ---
    if album_metadata.get('cover') and os.path.exists(album_metadata['cover']):
        try:
            # Salin gambar sebagai cover.jpg ke dalam folder utama album
            shutil.copy2(album_metadata['cover'], os.path.join(album_folder, "cover.jpg"))
        except Exception as e:
            LOGGER.warning(f"Gagal menyalin cover ke folder ZIP: {e}")
    # ---------------------------------------------------------
    
    # 1. Panggil fungsi pengeposan Art Poster
    poster_msg = await post_art_poster(user, album_metadata)
    
    # --- FIX UI RADAR: Tiru persis gaya Qobuz ---
    # JANGAN menghapus user['bot_msg'] agar pesan status unduhan sebelumnya
    # dapat di-edit dan diubah menjadi Progress Bar Upload oleh message.py!
    
    if poster_msg:
        album_metadata['poster_msg'] = poster_msg
    else:
        album_metadata['poster_msg'] = user.get('bot_msg')
        
    # 2. Langsung serahkan keranjang ke mesin pengunggah
    from bot.helpers.uploder import album_upload
    await album_upload(album_metadata, user)

async def start_track(asin: str, user: dict, url: str, upload=True, forced_track_num=None, forced_total_tracks=None, forced_album_title=None, forced_album_artist=None):
    user_id = user.get('user_id')
    # --- FIX: Paksa Manager membaca URL agar tidak salah region ---
    client = user.get('amazon_api') or amazon_manager.get_client(user_id, url=url)
    # -------------------------------------------------------------
    
    if not client:
        raise Exception("Tidak ada klien Amazon Music yang aktif.")

    LOGGER.info(f"Amazon: Mengambil info untuk lagu {asin}")
    
    try:
        from bot.settings import bot_set
        user_data = bot_set.user_data.get(user_id, {})
        user_quality = user_data.get('amazon_qual', 'HD')
        
        # Pengecekan Kualitas Secara Presisi
        if "AC-4" in user_quality.upper(): target_q = "AC-4"
        elif "EC-3" in user_quality.upper(): target_q = "EC-3"
        elif "MHA1" in user_quality.upper(): target_q = "MHA1"
        elif "MHM1" in user_quality.upper(): target_q = "MHM1"
        elif "FLAC" in user_quality.upper() or "HIRES" in user_quality.upper() or "MAX" in user_quality.upper() or "UHD" in user_quality.upper(): target_q = "UHD"
        elif "HD" in user_quality.upper(): target_q = "HD"
        elif "LD" in user_quality.upper(): target_q = "LD"
        else: target_q = "SD" 
            
        LOGGER.info(f"Amazon: Target batas maksimal kualitas: {target_q}")
        manifest_data = await client.get_playback_info(asin, target_quality=target_q)

    except Exception as e:
        err_str = str(e)
        if "Akses ditolak" in err_str or "EXPIRED_TOKEN" in err_str:
            raise Exception(f"Akses Ditolak: Mewajibkan langganan Amazon Music Unlimited yang aktif atau tidak tersedia. Detail: {err_str}")
        raise e
    
    # --- PENENTUAN KUALITAS & FORMAT NYATA (ACTUAL QUALITY) ---
    codec = manifest_data.get('codec', 'flac').lower()
    
    if 'flac' in codec: 
        ext = 'flac'
        actual_q = target_q if target_q in ['HD', 'UHD'] else 'HD'
    elif 'opus' in codec: 
        ext = 'opus'
        actual_q = target_q if target_q in ['SD', 'LD'] else 'SD'
    elif 'ec-3' in codec:
        ext = 'm4a'  
        actual_q = 'EC-3'
    elif 'ac-4' in codec:
        ext = 'm4a'  
        actual_q = 'AC-4'
    elif 'mha1' in codec:
        ext = 'm4a'  
        actual_q = 'MHA1'
    elif 'mhm1' in codec:
        ext = 'm4a'  
        actual_q = 'MHM1'
    else: 
        ext = 'm4a'
        actual_q = target_q if target_q in ['SD', 'LD'] else 'SD'
        
    # --- TAMBAHAN DETEKSI EXPLICIT ---
    raw_title = manifest_data.get('title', asin)
    raw_album = manifest_data.get('album', 'Unknown Album')
    
    # Deteksi otomatis dari judul atau album
    is_explicit_track = "[explicit]" in str(raw_title).lower() or "[explicit]" in str(raw_album).lower()

    track_meta = {
        'title': raw_title,
        'artist': manifest_data.get('artist', 'Unknown Artist'),
        'album': forced_album_title if forced_album_title else raw_album,
        'albumartist': forced_album_artist if forced_album_artist else manifest_data.get('albumartist', 'Unknown Artist'),
        # --- FIX: Gunakan nomor paksaan dari Album jika tersedia ---
        'tracknumber': forced_track_num if forced_track_num else manifest_data.get('tracknumber', 1),
        'totaltracks': forced_total_tracks if forced_total_tracks else manifest_data.get('totaltracks', 1),
        'discnumber': manifest_data.get('discnumber', 1),
        
        # --- Pemetaan Volume & Explicit untuk file Audio ---
        'volume': str(manifest_data.get('discnumber', 1)),
        'totalvolume': '1', 
        'explicit': is_explicit_track,
        
        'release_date': manifest_data.get('release_date', ''),
        'genre': manifest_data.get('genre', ''),
        'copyright': manifest_data.get('copyright', ''),
        'publisher': manifest_data.get('publisher', ''),
        'isrc': manifest_data.get('isrc', ''),
        'composer': manifest_data.get('composer', ''),
        'cover': manifest_data.get('cover', ''),  
        
        # --- FIX: Gunakan kualitas asli file, bukan kualitas target ---
        'quality': actual_q, 
        
        'provider': 'Amazon Music',
        'type': 'track'
    }
    
    # --- FIX 1: SEDOT LIRIK OTOMATIS MENGGUNAKAN MESIN BAWAAN BOT ---
    try:
        from bot.helpers.lyrics.manager import lyrics_manager
        if lyrics_manager:
            # Cari lirik berdasarkan Judul dan Artis
            lirik = await lyrics_manager.get_lyrics(track_meta['title'], track_meta['artist'])
            if lirik:
                track_meta['lyrics'] = lirik
    except Exception as e:
        LOGGER.debug(f"Pencarian lirik diabaikan/gagal: {e}")
    # ----------------------------------------------------------------
    
    # --- FIX 2: PENOMORAN FILE & PENGELOMPOKAN FOLDER ALBUM ---
    # Gunakan zfill(2) agar nomor track selalu 2 digit (01, 02, dst)
    track_num = str(track_meta['tracknumber']).zfill(2)
    
    # Bersihkan karakter ilegal dari nama menggunakan sanitize_filepath
    clean_title = sanitize_filepath(track_meta['title'])
    
    # --- FIX: Gunakan ALBUM ARTIST untuk nama folder agar tidak terserak! ---
    raw_album_artist = track_meta.get('albumartist') or track_meta.get('artist') or 'Various Artists'
    clean_album_artist = sanitize_filepath(raw_album_artist)
    
    clean_album = sanitize_filepath(track_meta['album'])
    
    # Format Nama File Baru
    file_name = f"{track_num} - {clean_title}"
    folder_path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Amazon Music/{clean_album_artist}/{clean_album}"
    
    os.makedirs(folder_path, exist_ok=True)
    
    final_path = f"{folder_path}/{file_name}.{ext}"
    track_meta['filepath'] = final_path
    track_meta['folderpath'] = folder_path

    audio_url = manifest_data.get('url') 
    kid = manifest_data.get('kid') 
    
    if not audio_url:
        raise Exception(f"Gagal menemukan Audio URL untuk lagu {asin}.")
        
    # Sesuaikan juga nama file enkripsi dan dekripsi sementaranya
    enc_path = f"{folder_path}/{file_name}.enc.mp4"
    dec_path = f"{folder_path}/{file_name}.dec.mp4"
    # -----------------------------------------------

    # --- PERBAIKAN RADAR ARIA2: Bisukan Radar Jika Di Dalam Album ---
    details = None
    if upload and 'bot_msg' in user:
        details = {
            'msg': user['bot_msg'], 
            'title': track_meta.get('title', 'Unknown'), 
            'type': track_meta.get('type', 'Track').capitalize()
        }
        
    # --- FIX: Gunakan Try-Except standar untuk Aria2 ---
    try:
        await aria2_download(audio_url, enc_path, details=details)
    except Exception as e:
        LOGGER.error(f"Gagal mengunduh dengan Aria2: {e}")
        return False

    if kid:
        LOGGER.info(f"Amazon: Memulai proses DRM untuk KID {kid}")
        prd_path = "bot/helpers/amazon/drm/hisense_smarttv_hu32e5600fhwv_sl3000.prd"
        cdm, session_id, challenge_b64 = await asyncio.to_thread(generate_challenge, kid, prd_path)
        license_b64 = await client.get_license(challenge_b64, asin)
        keys = await asyncio.to_thread(parse_license_and_get_keys, cdm, session_id, license_b64)

        def run_decryption(enc, dec, key_list):
            from bot.helpers.amazon.drm import pydecrypt
            keys_by_track, keys_by_kid = pydecrypt.parse_keys(key_list)
            try:
                pydecrypt.decrypt_mp4_file(enc, dec, keys_by_track, keys_by_kid)
            except SystemExit:
                raise Exception("Dekripsi digagalkan oleh pydecrypt (KID tidak cocok).")

        await asyncio.to_thread(run_decryption, enc_path, dec_path, keys)
    else:
        shutil.copy(enc_path, dec_path)

    await amazon_convert_only(dec_path, final_path)

    try:
        os.remove(enc_path)
        os.remove(dec_path)
    except:
        pass

    # --- FIX: DETEKSI KUALITAS FISIK SECARA NYATA (HD vs UHD) ---
    if ext == 'flac':
        try:
            from mutagen.flac import FLAC
            audio = FLAC(final_path)
            bps = audio.info.bits_per_sample
            sr = audio.info.sample_rate
            
            # Simpan data teknis ini agar ikut tertulis ke dalam tag metadata file
            track_meta['bit_depth'] = bps
            track_meta['sample_rate'] = sr
            
            # Standar Amazon: 24-bit atau di atas 48kHz = UHD (Hi-Res), Sisanya HD (CD Quality)
            if bps > 16 or sr > 48000:
                track_meta['quality'] = 'UHD'
            else:
                track_meta['quality'] = 'HD'
        except Exception as e:
            LOGGER.debug(f"Gagal membedah info FLAC: {e}")
    # ------------------------------------------------------------

    from bot.helpers.metadata import set_metadata
    await set_metadata(track_meta, user_id)

    # 3. Panggil uploader utama (Mendukung Cloud / Local / Telegram)
    if upload:
        from bot.helpers.uploder import track_upload
        await track_upload(track_meta, user, disable_link=False)
        
    return track_meta
