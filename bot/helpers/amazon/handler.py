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

async def amazon_convert_only(input_path, final_path):
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
    else:
        await start_track(asin, user, url)

async def start_album(album_asin: str, user: dict, url: str):
    LOGGER.info(f"Amazon: Mengambil info Album {album_asin}")
    user_id = user.get('user_id')
    client = user.get('amazon_api') or amazon_manager.get_client(user_id)
    
    if not client:
        raise Exception("Tidak ada klien Amazon Music yang aktif.")

    device_id = client.tokens.get('device_id')
    device_type_id = client.tokens.get('deviceTypeId') or "A1KAXIG6VXSG8Y"
    
    domain = urlparse.urlparse(url).netloc.lower()
    
    lookup_base = client.base_url
    api_loc = client.api_location
    music_territory = client.region.upper()
    
    if 'amazon.fr' in domain:
        lookup_base, api_loc, music_territory = "https://music.amazon.fr/", "EU", "FR"
    elif 'amazon.co.jp' in domain:
        lookup_base, api_loc, music_territory = "https://music.amazon.co.jp/", "FE", "JP"
    elif 'amazon.co.uk' in domain:
        lookup_base, api_loc, music_territory = "https://music.amazon.co.uk/", "EU", "UK"
    elif 'amazon.de' in domain:
        lookup_base, api_loc, music_territory = "https://music.amazon.de/", "EU", "DE"
    elif 'amazon.com.mx' in domain:
        lookup_base, api_loc, music_territory = "https://music.amazon.com.mx/", "NA", "MX"
    elif 'amazon.com.br' in domain:
        lookup_base, api_loc, music_territory = "https://music.amazon.com.br/", "NA", "BR"
    elif 'amazon.com' in domain:
        lookup_base, api_loc, music_territory = "https://music.amazon.com/", "NA", "US"

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
    
    tasks = []
    for t_asin in track_asins:
        # Panggil start_track dengan upload=False agar tidak membuat UI "Download Track" mandiri
        tasks.append(start_track(t_asin, user, url, upload=False))
        
    # Konfigurasi batas paralel (Sequential vs Concurrent)
    limit_pekerja = Config.MAX_WORKERS if getattr(bot_set, 'playlist_conc', True) else 1
    
    # Eksekusi paralel yang membungkus UI menjadi "Downloading Album"
    task_results = await run_concurrent_tasks(tasks, update_details, limit=limit_pekerja)
    
    album_tracks = [res for res in task_results if res]
    
    if not album_tracks:
        if 'bot_msg' in user:
            await edit_message(user['bot_msg'], "❌ Gagal: Tidak ada lagu yang berhasil diunduh.")
        return

    # Penyiapan Folder & Cover
    album_folder = album_tracks[0].get('folderpath', '')
    
    album_metadata = {
        'type': 'album',
        'title': album_title,
        'album': album_title,
        'artist': album_artist,
        'albumartist': album_artist,
        'folderpath': album_folder,
        'tracks': album_tracks,
        'provider': 'Amazon Music',
        'cover': album_cover or album_tracks[0].get('cover', ''),
        'quality': album_tracks[0].get('quality', 'UHD') if album_tracks else 'UHD'
    }
    
    # 1. Panggil fungsi pengeposan Art Poster
    poster_msg = await post_art_poster(user, album_metadata)
    
    if poster_msg:
        album_metadata['poster_msg'] = poster_msg
        if 'bot_msg' in user:
            try: 
                from bot.tgclient import aio
                await aio.delete_messages(user['chat_id'], user['bot_msg'].id)
            except: pass
    else:
        album_metadata['poster_msg'] = user.get('bot_msg')
        
    # 2. Serahkan keranjang ke mesin pengunggah
    await album_upload(album_metadata, user)

async def start_track(asin: str, user: dict, url: str, upload=True):
    user_id = user.get('user_id')
    client = user.get('amazon_api') or amazon_manager.get_client(user_id)
    
    if not client:
        raise Exception("Tidak ada klien Amazon Music yang aktif.")

    LOGGER.info(f"Amazon: Mengambil info untuk lagu {asin}")
    
    try:
        from bot.settings import bot_set
        user_data = bot_set.user_data.get(user_id, {})
        user_quality = user_data.get('amazon_qual', 'HD')
        
        if "FLAC" in user_quality.upper() or "HIRES" in user_quality.upper() or "MAX" in user_quality.upper() or "UHD" in user_quality.upper():
            target_q = "UHD"
        elif "HD" in user_quality.upper():
            target_q = "HD"
        else:
            target_q = "SD" 
            
        LOGGER.info(f"Amazon: Target batas maksimal kualitas: {target_q}")
        manifest_data = await client.get_playback_info(asin, target_quality=target_q)
        
    except Exception as e:
        err_str = str(e)
        if "Akses ditolak" in err_str or "EXPIRED_TOKEN" in err_str:
            raise Exception(f"Akses Ditolak: Mewajibkan langganan Amazon Music Unlimited yang aktif atau tidak tersedia. Detail: {err_str}")
        raise e
    
    codec = manifest_data.get('codec', 'flac').lower()
    if 'flac' in codec: ext = 'flac'
    elif 'opus' in codec: ext = 'opus'
    else: ext = 'm4a'
    
    track_meta = {
        'title': manifest_data.get('title', asin),
        'artist': manifest_data.get('artist', 'Unknown Artist'),
        'album': manifest_data.get('album', 'Unknown Album'),
        'albumartist': manifest_data.get('albumartist', 'Unknown Artist'),
        'tracknumber': manifest_data.get('tracknumber', 1),
        'totaltracks': manifest_data.get('totaltracks', 1),
        'discnumber': manifest_data.get('discnumber', 1),
        'release_date': manifest_data.get('release_date', ''),
        'genre': manifest_data.get('genre', ''),
        'copyright': manifest_data.get('copyright', ''),
        'publisher': manifest_data.get('publisher', ''),
        'isrc': manifest_data.get('isrc', ''),
        'composer': manifest_data.get('composer', ''),
        'cover': manifest_data.get('cover', ''),  
        'quality': target_q, 
        'provider': 'Amazon Music',
        'type': 'track'
    }
    
    folder_path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Amazon Music/{track_meta['artist']}/{track_meta['album']}"
    folder_path = sanitize_filepath(folder_path)
    os.makedirs(folder_path, exist_ok=True)
    
    final_path = f"{folder_path}/{track_meta['title']}.{ext}"
    track_meta['filepath'] = final_path
    track_meta['folderpath'] = folder_path

    audio_url = manifest_data.get('url') 
    kid = manifest_data.get('kid') 
    
    if not audio_url:
        raise Exception(f"Gagal menemukan Audio URL untuk lagu {asin}.")
        
    enc_path = f"{folder_path}/{track_meta['title']}.enc.mp4"
    dec_path = f"{folder_path}/{track_meta['title']}.dec.mp4"

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

    from bot.helpers.metadata import set_metadata
    await set_metadata(track_meta, user_id)

    # 3. Panggil uploader utama (Mendukung Cloud / Local / Telegram)
    if upload:
        await track_upload(track_meta, user, disable_link=False)
        
    return track_meta
