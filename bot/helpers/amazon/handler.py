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
    
    # [FIX] Tambahkan argumen header_spec=None sesuai permintaan modul
    header = builder.build_header(
        version="4.0", 
        header_spec=None, 
        encryption_scheme="cenc", 
        key_specs=[(kid_clean, kid_clean)]
    )
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
    access_token = client.tokens.get('x-amz-access-token')
    customer_id = client.tokens.get('customerId') # [FIX] Ambil ID pengguna
    
    device_type_id = client.tokens.get('deviceTypeId') or "A1KAXIG6VXSG8Y"
    music_territory = client.region.upper() 
    
    lookup_url = f"{client.base_url}{client.api_location}/api/muse/legacy/lookup"
    
    lookup_payload = {
        "asins": [album_asin],
        "features": ["popularity", "expandTracklist", "trackLibraryAvailability", "collectionLibraryAvailability"],
        "requestedContent": "FULL_CATALOG", 
        "musicTerritory": music_territory, 
        "deviceId": device_id,
        "deviceType": device_type_id
    }
    
    # [FIX] Suntikkan customerId agar Amazon memberikan daftar lagu Premium
    if customer_id:
        lookup_payload["customerId"] = customer_id
        
    lookup_headers = {
        "X-Amz-Target": "com.amazon.musicensembleservice.MusicEnsembleService.lookup",
        "x-amz-access-token": access_token,
        "x-amzn-device-type-id": device_type_id,
        "x-amzn-hardware-device-type-id": device_type_id
    }
    
    track_asins = []
    async with client.session.post(lookup_url, json=lookup_payload, headers=lookup_headers) as resp:
        if resp.status == 200:
            data = await resp.json()
            for album in data.get("albumList", []):
                for track in album.get("trackList", []):
                    if track.get("asin"):
                        track_asins.append(track["asin"])
                        
    # [FIX] FALLBACK: Ekstraksi dari Web jika API TV tetap memblokir daftar lagu
    if not track_asins:
        LOGGER.warning(f"API tidak memberikan trackList untuk {album_asin}. Menggunakan Web Scraper...")
        web_url = f"https://music.amazon.com/albums/{album_asin}"
        web_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        
        try:
            import requests
            # [FIX] Menggunakan requests murni via to_thread untuk menghindari limitasi ukuran header aiohttp
            w_resp = await asyncio.to_thread(requests.get, web_url, headers=web_headers, timeout=15)
            if w_resp.status_code == 200:
                html_data = w_resp.text
                import re
                # Cari pola JSON state Amazon yang menyimpan ID lagu
                raw_asins = re.findall(r'"asin"\s*:\s*"([^"]+)"', html_data)
                for a in raw_asins:
                    if a != album_asin and a.startswith('B0') and len(a) == 10 and a not in track_asins:
                        track_asins.append(a)
        except Exception as weberr:
            LOGGER.warning(f"Web scraper fallback gagal: {weberr}")
                
    if not track_asins:
        raise Exception("Amazon menolak memberikan daftar lagu, dan fallback Web Scraper gagal menemukan ASIN.")
            
    LOGGER.info(f"Amazon: Ditemukan {len(track_asins)} lagu dalam album.")
    if 'bot_msg' in user:
        await user['bot_msg'].edit_text(f"💿 **Album Ditemukan!**\nMemulai unduhan {len(track_asins)} lagu...")

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
    
    # --- FIX 2: Penanganan Akses Ditolak (Premium/Unlimited check) ---
    try:
        manifest_data = await client.get_playback_info(asin)
    except Exception as e:
        err_str = str(e)
        if "Akses ditolak" in err_str or "EXPIRED_TOKEN" in err_str:
            raise Exception(f"Akses Ditolak: Lagu ini mewajibkan langganan Amazon Music Unlimited yang aktif atau tidak tersedia di wilayah akun Anda. Detail: {err_str}")
        raise e
    
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
