# [BUAT FILE BARU: bot/helpers/amazon/handler.py]

import asyncio
import os
from pathvalidate import sanitize_filepath
from bot.logger import LOGGER
from config import Config
from .manager import amazon_manager
from bot.helpers.aria2_helper import aria2_download
from bot.helpers.utils import ffmpeg_convert_and_tag
from bot.helpers.uploder import track_upload

# Import script external DRM
try:
    from .drm import pypr, pydecrypt
    from .drm.amazonmusic_manifest import AmazonManifest
except ImportError:
    pass

async def start_amazon(url: str, user: dict):
    # Parsing URL untuk menentukan ID dan Tipe (track/album/playlist)
    # Untuk POC, diasumsikan link tunggal track/album
    asin = url.split('/')[-1]
    await start_track(asin, user, url)

async def start_track(asin: str, user: dict, url: str):
    client = user.get('amazon_api') or amazon_manager.get_client()
    if not client:
        raise Exception("Tidak ada klien Amazon Music yang aktif.")

    LOGGER.info(f"Amazon: Mengambil info untuk {asin}")
    
    # 1. Parsing Manifest & Ekstrak Data (Adaptasi dari amazonmusic_manifest.py)
    manifest_data = await client.get_playback_info(asin)
    
    # Setup Metadata
    track_meta = {
        'title': manifest_data.get('title', asin),
        'artist': manifest_data.get('artist', 'Unknown Artist'),
        'album': manifest_data.get('album', 'Unknown Album'),
        'provider': 'Amazon Music',
        'type': 'track'
    }
    
    # Tentukan folder output
    folder_path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Amazon Music/{track_meta['artist']}/{track_meta['album']}"
    folder_path = sanitize_filepath(folder_path)
    os.makedirs(folder_path, exist_ok=True)
    track_meta['folderpath'] = folder_path

    # Extract Audio URL & PSSH
    audio_url = manifest_data.get('url') # Sesuaikan dengan struktur MPD parser Anda
    pssh_b64 = manifest_data.get('pssh') 
    
    enc_path = f"{folder_path}/{track_meta['title']}.enc.mp4"
    dec_path = f"{folder_path}/{track_meta['title']}.dec.mp4"
    final_path = f"{folder_path}/{track_meta['title']}.flac"

    # 2. Download segmen terenkripsi dengan Aria2
    details = None
    if 'bot_msg' in user:
        details = {'msg': user['bot_msg'], 'title': track_meta['title'], 'type': 'Track'}
        
    await aria2_download(audio_url, enc_path, details=details)

    # 3. Request License DRM & Dapatkan Keys
    license_data = await client.get_license(pssh_b64)
    prd_path = "bot/helpers/amazon/drm/hisense_smarttv_hu32e5600fhwv_sl3000.prd"
    
    # Eksekusi pypr.py di thread terpisah agar tidak memblokir loop
    keys = await asyncio.to_thread(pypr.extract_keys, license_data, prd_path)

    # 4. Dekripsi (Gunakan pydecrypt / mp4decrypt)
    LOGGER.info(f"Amazon: Mendekripsi dengan keys {keys}")
    await asyncio.to_thread(pydecrypt.decrypt_file, enc_path, dec_path, keys)

    # 5. Konversi & Tagging
    track_meta['filepath'] = final_path
    await ffmpeg_convert_and_tag(dec_path, track_meta)

    # Bersihkan file sementara
    try:
        os.remove(enc_path)
        os.remove(dec_path)
    except:
        pass

    # 6. Upload
    await track_upload(track_meta, user, disable_link=False)
