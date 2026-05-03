# [FILE: bot/helpers/amazon/handler.py]

import asyncio
import os
import base64
import shutil
import urllib.parse as urlparse
from pathvalidate import sanitize_filepath
from bot.logger import LOGGER
from config import Config
from .manager import amazon_manager
from bot.helpers.aria2_helper import aria2_download
from bot.helpers.tidal.utils import ffmpeg_convert_and_tag
from bot.helpers.uploder import telegram_upload

def generate_challenge(kid, prd_path):
    from bot.helpers.amazon.drm.pypr import PlayReadyHeaderBuilder, PSSH, Device, Cdm
    kid_clean = kid.replace("-", "")
    builder = PlayReadyHeaderBuilder(kid_clean)
    header = builder.build_header(version="4.0", encryption_scheme="cenc", key_specs=[(kid_clean, kid_clean)])
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

async def start_amazon(url: str, user: dict):
    parsed = urlparse.urlparse(url)
    qs = urlparse.parse_qs(parsed.query)
    
    # 1. Jika URL adalah track spesifik dari dalam album (mengandung trackAsin)
    if 'trackAsin' in qs:
        asin = qs['trackAsin'][0]
        await start_track(asin, user, url)
        return
    
    # Ambil ASIN utama dari URL
    asin = parsed.path.strip('/').split('/')[-1]
    
    # 2. Pisahkan penanganan antara Link Album dan Link Track biasa
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

    # --- REQUEST DATA ALBUM UNTUK MENDAPATKAN SEMUA ID LAGU ---
    device_id = client.tokens.get('device_id')
    access_token = client.tokens.get('x-amz-access-token')
    marketplace_id = client.tokens.get('marketplaceId', 'US')
    device_type_id = client.tokens.get('deviceTypeId', "A1KAXIG6VXSG8Y")
    
    lookup_url = f"{client.base_url}{client.api_location}/api/muse/legacy/lookup"
    lookup_payload = {
        "asins": [album_asin],
        "features": ["expandTracklist"],
        "requestedContent": "MUSIC_SUBSCRIPTION",
        "musicTerritory": marketplace_id,
        "deviceId": device_id,
        "deviceType": device_type_id
    }
    lookup_headers = {
        "X-Amz-Target": "com.amazon.musicensembleservice.MusicEnsembleService.lookup",
        "x-amz-access-token": access_token
    }
    
    track_asins = []
    async with client.session.post(lookup_url, json=lookup_payload, headers=lookup_headers) as resp:
        if resp.status == 200:
            data = await resp.json()
            tracks = data.get("trackList", [])
            # Kumpulkan semua ASIN lagu (bukan ASIN Album)
            track_asins = [t.get("asin") for t in tracks if t.get("asin")]
            
    if not track_asins:
        raise Exception("Gagal mengambil daftar lagu. Pastikan link Album valid.")
        
    LOGGER.info(f"Amazon: Ditemukan {len(track_asins)} lagu dalam album.")
    if 'bot_msg' in user:
        await user['bot_msg'].edit_text(f"💿 **Album Ditemukan!**\nMemulai unduhan {len(track_asins)} lagu...")

    # Unduh lagu satu per satu secara berurutan
    for t_asin in track_asins:
        try:
            await start_track(t_asin, user, url)
        except Exception as e:
            LOGGER.error(f"Gagal mengunduh track {t_asin}: {e}")
            continue

async def start_track(asin: str, user: dict, url: str):
    user_id = user.get('user_id')
    client = user.get('amazon_api') or amazon_manager.get_client(user_id)
    
    if not client:
        raise Exception("Tidak ada klien Amazon Music yang aktif.")

    LOGGER.info(f"Amazon: Mengambil info untuk lagu {asin}")
    
    manifest_data = await client.get_playback_info(asin)
    
    track_meta = {
        'title': manifest_data.get('title', asin),
        'artist': manifest_data.get('artist', 'Unknown Artist'),
        'album': manifest_data.get('album', 'Unknown Album'),
        'provider': 'Amazon Music',
        'type': 'track'
    }
    
    folder_path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Amazon Music/{track_meta['artist']}/{track_meta['album']}"
    folder_path = sanitize_filepath(folder_path)
    os.makedirs(folder_path, exist_ok=True)
    track_meta['folderpath'] = folder_path

    audio_url = manifest_data.get('url') 
    kid = manifest_data.get('kid') 
    
    if not audio_url:
        raise Exception(f"Gagal menemukan Audio URL untuk lagu {asin}.")
        
    enc_path = f"{folder_path}/{track_meta['title']}.enc.mp4"
    dec_path = f"{folder_path}/{track_meta['title']}.dec.mp4"
    final_path = f"{folder_path}/{track_meta['title']}.flac"

    details = None
    if 'bot_msg' in user:
        details = {'msg': user['bot_msg'], 'title': track_meta['title'], 'type': 'Track'}
        
    await aria2_download(audio_url, enc_path, details=details)

    if kid:
        LOGGER.info(f"Amazon: Memulai proses DRM untuk KID {kid}")
        prd_path = "bot/helpers/amazon/drm/hisense_smarttv_hu32e5600fhwv_sl3000.prd"
        cdm, session_id, challenge_b64 = await asyncio.to_thread(generate_challenge, kid, prd_path)
        license_b64 = await client.get_license(challenge_b64, asin)
        keys = await asyncio.to_thread(parse_license_and_get_keys, cdm, session_id, license_b64)

        LOGGER.info(f"Amazon: Mendekripsi file dengan keys {keys}")
        from bot.helpers.amazon.drm import pydecrypt
        await asyncio.to_thread(pydecrypt.decrypt_file, enc_path, dec_path, keys)
    else:
        LOGGER.info("Amazon: Trek ini bersifat Free/Unencrypted (Tanpa DRM), melewati dekripsi.")
        shutil.copy(enc_path, dec_path)

    track_meta['filepath'] = final_path
    await ffmpeg_convert_and_tag(dec_path, track_meta)

    try:
        os.remove(enc_path)
        os.remove(dec_path)
    except:
        pass

    await telegram_upload(track_meta, user)
