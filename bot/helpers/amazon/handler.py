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
from bot.helpers.uploder import telegram_upload

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

# --- FUNGSI BARU: Pengekstrak FFmpeg Tangguh Khusus Amazon ---
async def amazon_convert_and_tag(input_path, track_meta):
    output_path = track_meta['filepath']
    image_url = track_meta.get('image', '')
    
    cover_path = f"{input_path}_cover.jpg"
    if image_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as resp:
                    if resp.status == 200:
                        with open(cover_path, 'wb') as f:
                            f.write(await resp.read())
                        track_meta['thumb'] = cover_path
        except Exception as e:
            LOGGER.warning(f"Gagal mengunduh cover: {e}")
            cover_path = None
    else:
        cover_path = None

    cmd = ['ffmpeg', '-y', '-i', input_path]
    if cover_path and os.path.exists(cover_path):
        # Muxing audio + sampul gambar tanpa rekode (aman untuk MP4 FLAC)
        cmd.extend(['-i', cover_path, '-map', '0:a:0', '-map', '1:v:0', '-c:v', 'copy'])
    else:
        cmd.extend(['-map', '0:a:0'])
    
    cmd.extend(['-c:a', 'copy'])
    
    if output_path.endswith('.flac') and cover_path and os.path.exists(cover_path):
        cmd.extend(['-disposition:v', 'attached_pic'])
        
    cmd.append(output_path)
    
    LOGGER.info(f"Amazon FFmpeg CMD: {' '.join(cmd)}")
    
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    
    if proc.returncode != 0:
        LOGGER.error(f"FFmpeg gagal: {stderr.decode()}")
        raise Exception("Gagal mengekstrak audio dari kontainer (FFmpeg Error).")
        
    try:
        if output_path.endswith('.flac'):
            from mutagen.flac import FLAC, Picture
            audio = FLAC(output_path)
            audio['title'] = track_meta['title']
            audio['artist'] = track_meta['artist']
            audio['album'] = track_meta['album']
            if cover_path and os.path.exists(cover_path):
                pic = Picture()
                with open(cover_path, "rb") as f:
                    pic.data = f.read()
                pic.type = 3
                pic.mime = "image/jpeg"
                audio.add_picture(pic)
            audio.save()
        elif output_path.endswith('.m4a'):
            from mutagen.mp4 import MP4, MP4Cover
            audio = MP4(output_path)
            audio['\xa9nam'] = track_meta['title']
            audio['\xa9ART'] = track_meta['artist']
            audio['\xa9alb'] = track_meta['album']
            if cover_path and os.path.exists(cover_path):
                with open(cover_path, "rb") as f:
                    audio['covr'] = [MP4Cover(f.read(), imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()
        elif output_path.endswith('.opus') or output_path.endswith('.ogg'):
            from mutagen.oggopus import OggOpus
            audio = OggOpus(output_path)
            audio['title'] = track_meta['title']
            audio['artist'] = track_meta['artist']
            audio['album'] = track_meta['album']
            audio.save()
    except Exception as e:
        LOGGER.warning(f"Gagal menulis tag Mutagen: {e}")

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
    device_type_id = client.tokens.get('deviceTypeId') or "A1KAXIG6VXSG8Y"
    music_territory = client.region.upper() 
    
    lookup_url = f"{client.base_url}{client.api_location}/api/muse/legacy/lookup"
    
    lookup_headers = {
        "X-Amz-Target": "com.amazon.musicensembleservice.MusicEnsembleService.lookup",
        "x-amz-access-token": access_token,
        "x-amzn-device-type-id": device_type_id,
        "x-amzn-hardware-device-type-id": device_type_id
    }
    
    # Fungsi pembantu untuk mencari ASIN lagu di seluruh struktur JSON (Sangat Tangguh)
    def extract_track_asins(obj):
        found = []
        if isinstance(obj, dict):
            # Cek apakah objek ini adalah sebuah lagu (biasanya punya ASIN dan nomor trek/durasi)
            if 'asin' in obj and any(k in obj for k in ['trackNumber', 'trackNum', 'durationSeconds', 'duration']):
                found.append(obj['asin'])
            # Telusuri ke dalam setiap kunci dictionary
            for v in obj.values():
                found.extend(extract_track_asins(v))
        elif isinstance(obj, list):
            # Telusuri setiap item di dalam list
            for item in obj:
                found.extend(extract_track_asins(item))
        return found

    track_asins = []
    # Loop pada enum untuk memastikan Amazon membuka katalog yang tepat
    for req_content in ["MUSIC_SUBSCRIPTION", "FULL_CATALOG"]:
        lookup_payload = {
            "asins": [album_asin],
            "features": ["popularity", "expandTracklist", "trackLibraryAvailability", "collectionLibraryAvailability"],
            "requestedContent": req_content, 
            "musicTerritory": music_territory, 
            "deviceId": device_id,
            "deviceType": device_type_id
        }
        if client.tokens.get('customerId'):
            lookup_payload["customerId"] = client.tokens.get('customerId')
            
        try:
            async with client.session.post(lookup_url, json=lookup_payload, headers=lookup_headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Ambil semua ASIN lagu yang ditemukan di dalam JSON secara otomatis
                    discovered = extract_track_asins(data)
                    for asin in discovered:
                        # Pastikan itu lagu (B0...), bukan ASIN album itu sendiri, dan unik
                        if asin != album_asin and asin.startswith('B0') and asin not in track_asins:
                            track_asins.append(asin)
            
            if track_asins:
                LOGGER.info(f"Amazon: Berhasil menemukan {len(track_asins)} lagu dengan metode rekursif ({req_content}).")
                break
        except Exception as e:
            LOGGER.debug(f"Percobaan enum {req_content} gagal: {e}")
            continue
            
    if not track_asins:
        raise Exception(f"Gagal mendapatkan daftar lagu untuk {album_asin}. Ini bisa disebabkan oleh pembatasan wilayah (Regional Lock) atau tautan tidak valid.")
            
    if 'bot_msg' in user:
        await user['bot_msg'].edit_text(f"💿 **Data Ditemukan!**\nMemulai unduhan {len(track_asins)} lagu...")

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
    
    try:
        manifest_data = await client.get_playback_info(asin)
    except Exception as e:
        err_str = str(e)
        if "Akses ditolak" in err_str or "EXPIRED_TOKEN" in err_str:
            raise Exception(f"Akses Ditolak: Lagu ini mewajibkan langganan Amazon Music Unlimited yang aktif atau tidak tersedia di wilayah akun Anda. Detail: {err_str}")
        raise e
    
    # Penentuan ekstensi secara dinamis berdasarkan Codec
    codec = manifest_data.get('codec', 'flac').lower()
    if 'flac' in codec:
        ext = 'flac'
    elif 'opus' in codec:
        ext = 'opus'
    else:
        ext = 'm4a'
    
    track_meta = {
        'title': manifest_data.get('title', asin),
        'artist': manifest_data.get('artist', 'Unknown Artist'),
        'album': manifest_data.get('album', 'Unknown Album'),
        'image': manifest_data.get('image', ''),
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
        
        def run_decryption(enc, dec, key_list):
            from bot.helpers.amazon.drm import pydecrypt
            keys_by_track, keys_by_kid = pydecrypt.parse_keys(key_list)
            pydecrypt.decrypt_mp4_file(enc, dec, keys_by_track, keys_by_kid)

        await asyncio.to_thread(run_decryption, enc_path, dec_path, keys)
    else:
        LOGGER.info("Amazon: Trek ini bersifat Free/Unencrypted (Tanpa DRM), melewati dekripsi.")
        shutil.copy(enc_path, dec_path)

    # Mengekstrak & Men-tag file menggunakan fungsi mandiri
    await amazon_convert_and_tag(dec_path, track_meta)

    try:
        os.remove(enc_path)
        os.remove(dec_path)
    except:
        pass

    await telegram_upload(track_meta, user)
