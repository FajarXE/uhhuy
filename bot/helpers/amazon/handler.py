# [FILE: bot/helpers/amazon/handler.py]

import asyncio, os, base64, shutil, urllib.parse as urlparse
from pathvalidate import sanitize_filepath
from bot.logger import LOGGER
from config import Config
from .manager import amazon_manager
from bot.helpers.aria2_helper import aria2_download
from bot.helpers.tidal.utils import ffmpeg_convert_and_tag
from bot.helpers.uploder import telegram_upload

async def start_amazon(url: str, user: dict):
    parsed = urlparse.urlparse(url)
    qs = urlparse.parse_qs(parsed.query)
    asin = qs['trackAsin'][0] if 'trackAsin' in qs else parsed.path.strip('/').split('/')[-1]
    
    if '/albums/' in parsed.path or '/album/' in parsed.path and 'trackAsin' not in qs:
        await start_album(asin, user)
    else:
        await start_track(asin, user)

async def start_album(album_asin: str, user: dict):
    client = amazon_manager.get_client(user.get('user_id'))
    if not client: raise Exception("Klien tidak aktif.")
    
    LOGGER.info(f"Amazon: Mencari daftar lagu Album {album_asin}")
    payload = {"asins": [album_asin], "features": ["expandTracklist"], "musicTerritory": client.region.upper(), "deviceId": client.tokens['device_id'], "deviceType": client.tokens.get('deviceTypeId', "A1KAXIG6VXSG8Y")}
    
    async with client.session.post(f"{client.base_url}{client.api_location}/api/muse/legacy/lookup", json=payload,
        headers={"X-Amz-Target": "com.amazon.musicensembleservice.MusicEnsembleService.lookup"}) as resp:
        data = await resp.json()
        
        # --- LOGIKA EXTRACTION LEBIH KUAT ---
        tracks = []
        # Cari di trackList utama
        tracks.extend(data.get("trackList", []))
        # Cari di dalam albumList
        for alb in data.get("albumList", []):
            tracks.extend(alb.get("trackList", []))
            
        track_asins = [t["asin"] for t in tracks if t.get("asin")]
        
    if not track_asins:
        raise Exception(f"Amazon tidak memberikan daftar lagu untuk album ini. Respons: {str(data)[:200]}")
        
    if 'bot_msg' in user: await user['bot_msg'].edit_text(f"💿 Ditemukan {len(track_asins)} lagu. Memulai unduhan...")
    for t_asin in track_asins:
        try: await start_track(t_asin, user)
        except Exception as e: LOGGER.error(f"Gagal: {t_asin} - {e}")

async def start_track(asin: str, user: dict):
    client = amazon_manager.get_client(user.get('user_id'))
    manifest = await client.get_playback_info(asin)
    
    meta = {'title': manifest['title'], 'artist': manifest['artist'] or 'VA', 'album': manifest['album'] or 'Single', 'provider': 'Amazon Music'}
    path = sanitize_filepath(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Amazon Music/{meta['artist']}/{meta['album']}")
    os.makedirs(path, exist_ok=True)
    
    enc, dec, final = f"{path}/{asin}.enc", f"{path}/{asin}.dec", f"{path}/{manifest['title']}.flac"
    await aria2_download(manifest['url'], enc, details={'msg': user.get('bot_msg'), 'title': manifest['title']})

    if manifest['kid']:
        from bot.helpers.amazon.drm import pypr, pydecrypt
        # Generate Challenge
        prd = "bot/helpers/amazon/drm/hisense_smarttv_hu32e5600fhwv_sl3000.prd"
        def get_keys():
            import base64
            kid = manifest['kid'].replace("-", "")
            header = base64.b64encode(pypr.PlayReadyHeaderBuilder(kid).build_header(key_specs=[(kid, kid)])).decode()
            cdm = pypr.Cdm.from_device(pypr.Device.load(prd))
            sid = cdm.open()
            chall = base64.b64encode(cdm.get_license_challenge(sid, pypr.PSSH(header).wrm_headers[0]).encode()).decode()
            return cdm, sid, chall
            
        cdm, sid, chall = await asyncio.to_thread(get_keys)
        lic = await client.get_license(chall, asin)
        
        def decrypt(l):
            cdm.parse_license(sid, base64.b64decode(l).decode())
            keys = [f"{k.key_id.hex}:{k.key.hex()}" for k in cdm.get_keys(sid)]
            cdm.close(sid)
            pydecrypt.decrypt_file(enc, dec, keys)
        await asyncio.to_thread(decrypt, lic)
    else:
        shutil.copy(enc, dec)

    await ffmpeg_convert_and_tag(dec, {**meta, 'filepath': final})
    await telegram_upload({**meta, 'filepath': final}, user)
    for f in [enc, dec]: 
        if os.path.exists(f): os.remove(f)
