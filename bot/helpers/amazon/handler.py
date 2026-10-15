# [FILE: bot/helpers/amazon/handler.py]

import asyncio
import os
import base64
import shutil
import hashlib
import copy
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
from bot.helpers.uploder import track_upload, album_upload, playlist_upload
from bot.helpers.utils import run_concurrent_tasks, fetch_zip_settings, post_art_poster
from bot.helpers.message import edit_message
from bot.helpers.metadata import metadata as base_meta, set_metadata, create_cover_file
# ----------------------------------

_REPROVISION_LOCK = asyncio.Lock()
_HAS_REPROVISIONED = False


def _reprovision_prd_sync(prd_path: str):
    """Meregenerasi leaf certificate perangkat PlayReady (.prd) secara internal menggunakan pypr."""
    try:
        from bot.helpers.amazon.drm.pypr import Device, ECCKey, Certificate, BCertCertType
    except ImportError:
        from bot.helpers.amazon.pypr import Device, ECCKey, Certificate, BCertCertType
    from Crypto.Random import get_random_bytes

    if not os.path.exists(prd_path):
        alt_path = prd_path.replace("/drm/", "/").replace("\\drm\\", "\\")
        if os.path.exists(alt_path):
            prd_path = alt_path
        else:
            return

    device = Device.load(prd_path)
    if device.group_key is None or device.group_certificate.get(0).get_type() != BCertCertType.DEVICE:
        return

    device.group_certificate.remove(0)
    encryption_key = ECCKey.generate()
    signing_key = ECCKey.generate()
    device.encryption_key = encryption_key
    device.signing_key = signing_key

    new_cert = Certificate.new_leaf_cert(
        cert_id=get_random_bytes(16),
        security_level=device.group_certificate.get_security_level(),
        client_id=get_random_bytes(16),
        signing_key=signing_key,
        encryption_key=encryption_key,
        group_key=device.group_key,
        parent=device.group_certificate,
    )
    device.group_certificate.prepend(new_cert)
    device.dump(prd_path)


def generate_challenge(kid, prd_path):
    try:
        from bot.helpers.amazon.drm.pypr import PlayReadyHeaderBuilder, PSSH, Device, Cdm
    except ImportError:
        from bot.helpers.amazon.pypr import PlayReadyHeaderBuilder, PSSH, Device, Cdm
        
    kid_clean = kid.replace("-", "")
    builder = PlayReadyHeaderBuilder(kid_clean)
    header = builder.build_header(version="4.0", header_spec=None, encryption_scheme="cenc", key_specs=[(kid_clean, kid_clean)])
    playready_header = base64.b64encode(header).decode("ascii")
    
    if not os.path.exists(prd_path):
        alt_path = prd_path.replace("/drm/", "/").replace("\\drm\\", "\\")
        if os.path.exists(alt_path):
            prd_path = alt_path
        else:
            raise Exception(f"File PRD Device (hisense) tidak ditemukan! Path dicari: {prd_path}")
    
    device = Device.load(prd_path)
    cdm = Cdm.from_device(device)
    session_id = cdm.open()
    
    pssh_obj = PSSH(playready_header)
    challenge = cdm.get_license_challenge(session_id, pssh_obj.wrm_headers[0])
    challenge_b64 = base64.b64encode(challenge.encode("utf-8")).decode("utf-8")
    
    return challenge_b64, session_id, cdm


def parse_license_and_get_keys(cdm, session_id, license_b64):
    decoded_data = base64.b64decode(license_b64).decode("utf-8")
    try:
        cdm.parse_license(session_id, decoded_data)
        keys = []
        for key in cdm.get_keys(session_id):
            keys.append(f"{key.key_id.hex}:{key.key.hex()}")
        return keys
    finally:
        try:
            cdm.close(session_id)
        except Exception:
            pass


async def get_global_asin(url: str, current_asin: str) -> str:
    """Mengunjungi tautan secara anonim untuk mengekstrak ASIN Global (Shared Catalog)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    try:
        import re
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    matches = re.findall(r'(?:albums|tracks|playlists)/(B0[A-Z0-9]{8})', html)
                    if matches:
                        LOGGER.info(f"Amazon Scraper: Menemukan ASIN Global dari URL -> {matches[0]}")
                        return matches[0]
                        
                    matches_json = re.findall(r'"asin":"(B0[A-Z0-9]{8})"', html)
                    if matches_json:
                        LOGGER.info(f"Amazon Scraper: Menemukan ASIN Global dari JSON -> {matches_json[0]}")
                        return matches_json[0]
    except Exception as e:
        LOGGER.debug(f"Amazon Scraper Gagal (Abaikan): {e}")
        
    return current_asin


async def amazon_convert_only(input_path, final_path):
    if final_path.lower().endswith('.m4a'):
        LOGGER.info(f"Amazon Bypass FFmpeg: Memindahkan langsung kontainer asli untuk {final_path}")
        shutil.move(input_path, final_path)
        return

    if final_path.lower().endswith('.flac'):
        cmd = ['ffmpeg', '-y', '-i', input_path, '-map', '0:a:0', '-c:a', 'flac', final_path]
    else:
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
        try:
            os.remove(input_path)
        except Exception:
            pass
        raise Exception("Gagal mengekstrak audio dari kontainer (FFmpeg Error).")


async def start_amazon(url: str, user: dict):
    parsed = urlparse.urlparse(url)
    qs = urlparse.parse_qs(parsed.query)
    
    if 'trackAsin' in qs:
        asin = qs['trackAsin'][0]
        res = await start_track(asin, user, url)
        if not res:
            raise Exception("Gagal mengunduh lagu Amazon Music.")
        return
    
    asin = parsed.path.strip('/').split('/')[-1]
    
    if '/albums/' in parsed.path or '/album/' in parsed.path:
        await start_album(asin, user, url)
    elif '/playlists/' in parsed.path or '/playlist/' in parsed.path:
        await start_playlist(asin, user, url)
    else:
        res = await start_track(asin, user, url)
        if not res:
            raise Exception("Gagal mengunduh lagu Amazon Music.")


async def start_playlist(playlist_asin: str, user: dict, url: str):
    user_id = user.get('user_id')
    client = user.get('amazon_api') or amazon_manager.get_client(user_id, url=url)
    
    if not client:
        raise Exception("Tidak ada klien Amazon Music yang aktif.")
        
    # [FIX 1] Kunci klien ke dalam user dict agar start_track memakai akun yang sama
    user['amazon_api'] = client

    LOGGER.info(f"Amazon: Mengambil info Playlist {playlist_asin} (Akun Region: {client.region.upper()})")

    device_id = client.tokens.get('device_id')
    device_type_id = client.tokens.get('deviceTypeId') or "A1I3OANZGDNGEE"
    customer_id = client.tokens.get('customerId')
    access_token = client.tokens.get('x-amz-access-token')

    lookup_base = client.base_url
    api_loc = client.api_location
    music_territory = "GB" if client.region.lower() == "uk" else ("AU" if client.region.lower() in ["au", "nz"] else client.region.upper())
    lookup_url = f"{lookup_base}{api_loc}/api/muse/legacy/lookup"
    
    import uuid
    import json
    lookup_headers = {
        "x-amzn-requestid": str(uuid.uuid4()),
        "X-Amz-Target": "com.amazon.musicensembleservice.MusicEnsembleService.lookup",
        "x-amz-access-token": access_token,
        "x-amzn-device-type-id": device_type_id,
        "x-amzn-hardware-device-type-id": device_type_id
    }
    
    track_asins = []
    playlist_title = "Unknown Playlist"
    playlist_owner = "Amazon Music"
    playlist_cover = ""

    # [FIX 2] Coba ASIN asli dari URL lebih dulu; jika kosong baru fallback ke ASIN Global
    global_asin = await get_global_asin(url, current_asin=playlist_asin)
    asin_candidates = [playlist_asin]
    if global_asin and global_asin != playlist_asin:
        asin_candidates.append(global_asin)
    
    for candidate_asin in asin_candidates:
        for req_content in ["MUSIC_SUBSCRIPTION", "FULL_CATALOG"]:
            lookup_payload = {
                "customerId": customer_id,
                "asins": [candidate_asin],
                "features": ["popularity", "expandTracklist", "trackLibraryAvailability", "collectionLibraryAvailability"],
                "requestedContent": req_content, 
                "musicTerritory": music_territory, 
                "deviceId": device_id,
                "deviceType": device_type_id
            }
            
            try:
                async with client.session.post(lookup_url, json=lookup_payload, headers=lookup_headers) as resp:
                    resp_text = await resp.text()
                    
                    if resp.status in [400, 401, 403]:
                        LOGGER.info("Amazon: Token API Playlist kedaluwarsa, mencoba refresh...")
                        if await client.refresh_access_token():
                            lookup_headers["x-amz-access-token"] = client.tokens.get('x-amz-access-token')
                            async with client.session.post(lookup_url, json=lookup_payload, headers=lookup_headers) as retry_resp:
                                resp_text = await retry_resp.text()
                                if retry_resp.status != 200:
                                    continue
                        else:
                            continue
                    elif resp.status != 200:
                        continue

                    data = json.loads(resp_text)
                    for pl in data.get("playlistList", []):
                        playlist_title = pl.get("title", playlist_title)
                        playlist_owner = pl.get("author", pl.get("owner", playlist_owner))
                        playlist_cover = pl.get("image", playlist_cover)
                        
                        for track in pl.get("tracks", []):
                            if isinstance(track, dict) and track.get("asin"):
                                track_asins.append(track["asin"])
                                
                track_asins = list(dict.fromkeys(track_asins))
                if track_asins:
                    LOGGER.info(f"Amazon: Berhasil mendapat {len(track_asins)} lagu Playlist (ASIN: {candidate_asin}, Region: {music_territory}, Mode: {req_content})")
                    break
            except Exception as e:
                LOGGER.error(f"Amazon Lookup Error: {e}")
                continue
        if track_asins:
            break
            
    if not track_asins:
        raise Exception(f"Amazon tidak mengembalikan daftar lagu untuk playlist {playlist_asin}. Pastikan link valid.")

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS, 
        'msg': user.get('bot_msg'), 
        'title': playlist_title, 
        'type': 'Playlist'
    }
    
    tasks = []
    total_lagu = len(track_asins)
    for index, t_asin in enumerate(track_asins, start=1):
        tasks.append(start_track(
            t_asin, user, url, upload=False, 
            forced_track_num=index, forced_total_tracks=total_lagu, 
            forced_album_title=playlist_title, forced_album_artist=playlist_owner
        ))
        
    limit_pekerja = Config.MAX_WORKERS if getattr(bot_set, 'playlist_conc', True) else 1
    task_results = await run_concurrent_tasks(tasks, update_details, limit=limit_pekerja)
    
    playlist_tracks = [res for res in task_results if isinstance(res, dict)]
    if not playlist_tracks:
        raise Exception("Semua lagu dalam playlist gagal diunduh.")

    playlist_folder = playlist_tracks[0].get('folderpath', '')
    sample_track = playlist_tracks[0]
    
    safe_cover = sample_track.get('cover', '')
    if safe_cover and not os.path.exists(str(safe_cover)):
        safe_cover = ''
        
    is_explicit = any(t.get('explicit') or "[explicit]" in str(t.get('title', '')).lower() for t in playlist_tracks)

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
        'thumbnail': safe_cover,
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
        except Exception:
            pass
    
    poster_msg = await post_art_poster(user, playlist_metadata)
    playlist_metadata['poster_msg'] = poster_msg if poster_msg else user.get('bot_msg')
        
    await playlist_upload(playlist_metadata, user)


async def start_album(album_asin: str, user: dict, url: str):
    user_id = user.get('user_id')
    client = user.get('amazon_api') or amazon_manager.get_client(user_id, url=url)
    
    if not client:
        raise Exception("Tidak ada klien Amazon Music yang aktif.")
        
    user['amazon_api'] = client

    LOGGER.info(f"Amazon: Mengambil info Album {album_asin} (Akun Region: {client.region.upper()})")

    device_id = client.tokens.get('device_id')
    device_type_id = client.tokens.get('deviceTypeId') or "A1I3OANZGDNGEE"
    customer_id = client.tokens.get('customerId')
    access_token = client.tokens.get('x-amz-access-token')
    
    lookup_base = client.base_url
    api_loc = client.api_location
    music_territory = "GB" if client.region.lower() == "uk" else ("AU" if client.region.lower() in ["au", "nz"] else client.region.upper())
    lookup_url = f"{lookup_base}{api_loc}/api/muse/legacy/lookup"
    
    import uuid
    import json
    lookup_headers = {
        "x-amzn-requestid": str(uuid.uuid4()),
        "X-Amz-Target": "com.amazon.musicensembleservice.MusicEnsembleService.lookup",
        "x-amz-access-token": access_token,
        "x-amzn-device-type-id": device_type_id,
        "x-amzn-hardware-device-type-id": device_type_id
    }
    
    track_asins = []
    album_title = "Unknown Album"
    album_artist = "Unknown Artist"
    album_cover = ""

    global_asin = await get_global_asin(url, current_asin=album_asin)
    asin_candidates = [album_asin]
    if global_asin and global_asin != album_asin:
        asin_candidates.append(global_asin)
    
    for candidate_asin in asin_candidates:
        for req_content in ["MUSIC_SUBSCRIPTION", "FULL_CATALOG"]:
            lookup_payload = {
                "customerId": customer_id,
                "asins": [candidate_asin],
                "features": ["popularity", "expandTracklist", "trackLibraryAvailability", "collectionLibraryAvailability", "albumArtist", "fullAlbumDetails"],
                "requestedContent": req_content, 
                "musicTerritory": music_territory, 
                "deviceId": device_id,
                "deviceType": device_type_id
            }
            
            try:
                async with client.session.post(lookup_url, json=lookup_payload, headers=lookup_headers) as resp:
                    resp_text = await resp.text()
                    
                    if resp.status in [400, 401, 403]:
                        LOGGER.info("Amazon: Token API Album kedaluwarsa, mencoba refresh...")
                        if await client.refresh_access_token():
                            lookup_headers["x-amz-access-token"] = client.tokens.get('x-amz-access-token')
                            async with client.session.post(lookup_url, json=lookup_payload, headers=lookup_headers) as retry_resp:
                                resp_text = await retry_resp.text()
                                if retry_resp.status != 200:
                                    continue
                        else:
                            continue
                    elif resp.status != 200:
                        continue
                    
                    data = json.loads(resp_text) or {}
                    
                    # 1. Cek dari asinList (Format string ASIN murni root)
                    for asin_item in data.get("asinList", []):
                        if isinstance(asin_item, str) and asin_item.startswith("B0"):
                            track_asins.append(asin_item)

                    # 2. Cek langsung dari trackList utama
                    if not track_asins:
                        for track in data.get("trackList", []):
                            if isinstance(track, dict) and track.get("asin"):
                                track_asins.append(track["asin"])
                                if album_title == "Unknown Album" and isinstance(track.get("album"), dict):
                                    album_title = track["album"].get("title", album_title)
                                if album_artist == "Unknown Artist" and isinstance(track.get("artist"), dict):
                                    album_artist = track["artist"].get("name", album_artist)

                    # 3. Cek dari albumList (Standar)
                    if not track_asins:
                        for album in data.get("albumList", []):
                            if not isinstance(album, dict):
                                continue
                            album_title = album.get("title", album_title)
                            album_artist = album.get("primaryArtistName", album_artist)
                            album_cover = album.get("image", album_cover)
                            
                            for track in album.get("tracks", []):
                                if isinstance(track, dict) and track.get("asin"):
                                    track_asins.append(track["asin"])
                                    
                    # 4. Cek dari containerList (Format alternatif)
                    if not track_asins:
                        for container in data.get("containerList", []):
                            if not isinstance(container, dict):
                                continue
                            album_title = container.get("title", album_title)
                            album_artist = container.get("author", container.get("primaryArtistName", album_artist))
                            album_cover = container.get("image", album_cover)
                            
                            for track in container.get("tracks", []):
                                if isinstance(track, dict) and track.get("asin"):
                                    track_asins.append(track["asin"])

                    # 5. Cek dari itemList
                    if not track_asins:
                        for item in data.get("itemList", []):
                            if isinstance(item, dict) and item.get("asin"):
                                track_asins.append(item["asin"])
                                
                track_asins = list(dict.fromkeys(track_asins))
                if track_asins:
                    LOGGER.info(f"Amazon: Berhasil mendapat {len(track_asins)} lagu (ASIN: {candidate_asin}, Region: {music_territory}, Mode: {req_content})")
                    break
            except Exception as e:
                LOGGER.error(f"Amazon Lookup Error: {e}")
                continue
                
        if track_asins:
            break
            
    if not track_asins:
        raise Exception(f"Amazon tidak mengembalikan daftar lagu untuk album {album_asin}. Pastikan link valid.")

    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS, 
        'msg': user.get('bot_msg'), 
        'title': album_title, 
        'type': 'Album'
    }
    
    tasks = []
    total_lagu = len(track_asins)
    for index, t_asin in enumerate(track_asins, start=1):
        tasks.append(start_track(
            t_asin, user, url, upload=False, 
            forced_track_num=index, forced_total_tracks=total_lagu, 
            forced_album_title=album_title, forced_album_artist=album_artist
        ))
        
    limit_pekerja = Config.MAX_WORKERS if getattr(bot_set, 'playlist_conc', True) else 1
    task_results = await run_concurrent_tasks(tasks, update_details, limit=limit_pekerja)
    
    album_tracks = [res for res in task_results if isinstance(res, dict)]
    if not album_tracks:
        raise Exception(f"Semua lagu dalam album '{album_title}' gagal diunduh.")

    album_folder = album_tracks[0].get('folderpath', '')
    sample_track = album_tracks[0]
    
    safe_cover = sample_track.get('cover', '')
    if safe_cover and not os.path.exists(str(safe_cover)):
        safe_cover = ''
        
    try:
        max_disc = max(int(t.get('discnumber', 1)) for t in album_tracks)
    except Exception:
        max_disc = 1

    for t in album_tracks:
        t['totalvolume'] = str(max_disc)

    is_explicit = "[explicit]" in album_title.lower() or any(t.get('explicit') or "[explicit]" in str(t.get('title', '')).lower() for t in album_tracks)

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
        'thumbnail': safe_cover,
        'quality': sample_track.get('quality', 'UHD'),
        'release_date': sample_track.get('release_date', 'Unknown'),
        'date': sample_track.get('release_date', 'Unknown')[:4] if sample_track.get('release_date') else 'Unknown',
        'totaltracks': str(len(album_tracks)),
        'totalvolume': str(max_disc),    
        'total_volumes': str(max_disc),  
        'explicit': str(is_explicit)     
    }

    if album_metadata.get('cover') and os.path.exists(album_metadata['cover']):
        try:
            shutil.copy2(album_metadata['cover'], os.path.join(album_folder, "cover.jpg"))
        except Exception as e:
            LOGGER.warning(f"Gagal menyalin cover ke folder ZIP: {e}")
    
    poster_msg = await post_art_poster(user, album_metadata)
    album_metadata['poster_msg'] = poster_msg if poster_msg else user.get('bot_msg')
        
    await album_upload(album_metadata, user)


async def start_track(
    asin: str, user: dict, url: str, upload=True, 
    forced_track_num=None, forced_total_tracks=None, 
    forced_album_title=None, forced_album_artist=None
):
    global _HAS_REPROVISIONED
    user_id = user.get('user_id')
    client = user.get('amazon_api') or amazon_manager.get_client(user_id, url=url)
    
    if not client:
        raise Exception("Tidak ada klien Amazon Music yang aktif.")

    LOGGER.info(f"Amazon: Mengambil info untuk lagu {asin} (Akun Region: {client.region.upper()})")
    
    try:
        user_data = bot_set.user_data.get(user_id, {})
        user_quality = user_data.get('amazon_qual', getattr(amazon_manager, 'quality', 'HD'))
        
        if "AC-4" in user_quality.upper(): target_q = "AC-4"
        elif "EC-3" in user_quality.upper(): target_q = "EC-3"
        elif "MHA1" in user_quality.upper(): target_q = "MHA1"
        elif "MHM1" in user_quality.upper(): target_q = "MHM1"
        elif any(k in user_quality.upper() for k in ["FLAC", "HIRES", "MAX", "UHD"]): target_q = "UHD"
        elif "HD" in user_quality.upper(): target_q = "HD"
        elif "LD" in user_quality.upper(): target_q = "LD"
        else: target_q = "SD" 
            
        LOGGER.info(f"Amazon: Target batas maksimal kualitas: {target_q}")
        try:
            manifest_data = await client.get_playback_info(asin, target_quality=target_q)
        except Exception as first_err:
            # Jika unduhan track tunggal lintas-negara gagal (CONTENT_NOT_ELIGIBLE), coba ekstrak Global ASIN dari URL
            if upload and "CONTENT_NOT_ELIGIBLE" in str(first_err) and "trackAsin=" not in url:
                global_t_asin = await get_global_asin(url, current_asin=asin)
                if global_t_asin and global_t_asin != asin:
                    LOGGER.info(f"Amazon: Mencoba ulang track dengan Global ASIN {global_t_asin}...")
                    asin = global_t_asin
                    manifest_data = await client.get_playback_info(asin, target_quality=target_q)
                else:
                    raise first_err
            else:
                raise first_err

    except Exception as e:
        err_str = str(e)
        if "Akses ditolak" in err_str or "EXPIRED_TOKEN" in err_str:
            raise Exception(f"Akses Ditolak: Mewajibkan langganan Amazon Music Unlimited yang aktif atau tidak tersedia. Detail: {err_str}")
        raise e
    
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
        
    raw_title = manifest_data.get('title', asin)
    raw_album = manifest_data.get('album', 'Unknown Album')
    is_explicit_track = "[explicit]" in str(raw_title).lower() or "[explicit]" in str(raw_album).lower()

    track_meta = copy.deepcopy(base_meta)
    track_meta['tempfolder'] += f"{user['r_id']}-temp/"
    track_meta.update({
        'itemid': asin,
        'title': raw_title,
        'artist': manifest_data.get('artist', 'Unknown Artist'),
        'album': forced_album_title if forced_album_title else raw_album,
        'albumartist': forced_album_artist if forced_album_artist else manifest_data.get('albumartist', 'Unknown Artist'),
        'tracknumber': str(forced_track_num if forced_track_num else manifest_data.get('tracknumber', 1)).zfill(2),
        'totaltracks': str(forced_total_tracks if forced_total_tracks else manifest_data.get('totaltracks', 1)),
        'discnumber': manifest_data.get('discnumber', 1),
        'volume': str(manifest_data.get('discnumber', 1)),
        'totalvolume': '1', 
        'explicit': is_explicit_track,
        'release_date': manifest_data.get('release_date', ''),
        'date': manifest_data.get('release_date', ''),
        'genre': manifest_data.get('genre', ''),
        'copyright': manifest_data.get('copyright', ''),
        'publisher': manifest_data.get('publisher', ''),
        'isrc': manifest_data.get('isrc', ''),
        'composer': manifest_data.get('composer', ''),
        'quality': actual_q,
        'extension': ext,
        'provider': 'Amazon Music',
        'type': 'track'
    })

    # [FIX] Unduh URL Cover menjadi file gambar lokal agar Mutagen & Album ZIP memiliki sampul fisik
    raw_cover_url = manifest_data.get('cover', '')
    if raw_cover_url and str(raw_cover_url).startswith('http'):
        local_cover = await create_cover_file(raw_cover_url, track_meta)
        track_meta['cover'] = local_cover
        track_meta['thumbnail'] = local_cover
    else:
        track_meta['cover'] = None
        track_meta['thumbnail'] = None
    
    track_num = track_meta['tracknumber']
    clean_title = sanitize_filepath(track_meta['title'])
    raw_album_artist = track_meta.get('albumartist') or track_meta.get('artist') or 'Various Artists'
    clean_album_artist = sanitize_filepath(raw_album_artist)
    clean_album = sanitize_filepath(track_meta['album'])
    
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
        
    enc_path = f"{folder_path}/{file_name}.enc.mp4"
    dec_path = f"{folder_path}/{file_name}.dec.mp4"

    # [FIX] Suntikkan task_id dan action agar tombol /cancel berfungsi
    details = None
    if upload and 'bot_msg' in user and user['bot_msg']:
        task_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
        details = {
            'msg': user['bot_msg'], 
            'title': track_meta.get('title', 'Unknown'), 
            'type': 'Track',
            'action': 'Download',
            'task_id': task_id
        }
        
    try:
        dl_ok = await aria2_download(audio_url, enc_path, details=details)
        if not dl_ok or not os.path.exists(enc_path):
            if os.path.exists(enc_path):
                try: os.remove(enc_path)
                except Exception: pass
            return False
    except Exception as e:
        LOGGER.error(f"Gagal mengunduh dengan Aria2: {e}")
        return False

    if kid:
        LOGGER.info(f"Amazon: Memulai proses DRM untuk KID {kid}")
        prd_path = "bot/helpers/amazon/drm/hisense_smarttv_hu32e5600fhwv_sl3000.prd"
        
        # [FIX] Gunakan Lock & Thread-Safe Reprovision internal agar tidak race condition saat concurrent download
        if not _HAS_REPROVISIONED:
            async with _REPROVISION_LOCK:
                if not _HAS_REPROVISIONED:
                    try:
                        LOGGER.info("Amazon DRM: Meregenerasi leaf certificate CDM (Reprovision) Hisense...")
                        await asyncio.to_thread(_reprovision_prd_sync, prd_path)
                        _HAS_REPROVISIONED = True
                        LOGGER.info("Reprovision CDM Berhasil!")
                    except Exception as e:
                        LOGGER.warning(f"Gagal melakukan reprovision internal: {e}")
        
        challenge_b64, session_id, cdm = await asyncio.to_thread(generate_challenge, kid, prd_path)
        license_b64 = await client.get_license(challenge_b64, asin)
        keys = await asyncio.to_thread(parse_license_and_get_keys, cdm, session_id, license_b64)

        def run_decryption(enc, dec, key_list):
            try:
                from bot.helpers.amazon.drm import pydecrypt
            except ImportError:
                from bot.helpers.amazon import pydecrypt
            keys_by_track, keys_by_kid = pydecrypt.parse_keys(key_list)
            try:
                pydecrypt.decrypt_mp4_file(enc, dec, keys_by_track, keys_by_kid)
            except SystemExit:
                raise Exception("Dekripsi digagalkan oleh pydecrypt (KID tidak cocok atau file korup).")

        try:
            await asyncio.to_thread(run_decryption, enc_path, dec_path, keys)
        except Exception as dec_err:
            for p in (enc_path, dec_path):
                if os.path.exists(p):
                    try: os.remove(p)
                    except Exception: pass
            raise dec_err
    else:
        shutil.copy(enc_path, dec_path)

    await amazon_convert_only(dec_path, final_path)

    for p in (enc_path, dec_path):
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass

    if ext == 'flac':
        try:
            from mutagen.flac import FLAC
            audio = FLAC(final_path)
            bps = audio.info.bits_per_sample
            sr = audio.info.sample_rate
            
            track_meta['bit_depth'] = bps
            track_meta['sample_rate'] = sr
            track_meta['bps'] = str(bps)
            
            if bps > 16 or sr > 48000:
                track_meta['quality'] = 'UHD'
            else:
                track_meta['quality'] = 'HD'
        except Exception as e:
            LOGGER.debug(f"Gagal membedah info FLAC: {e}")

    # set_metadata otomatis mengurus pengambilan lirik (LRCLib/Musixmatch/Genius) & penulisan Cover Art
    await set_metadata(track_meta, user_id)

    def _inject_manual_tags():
        try:
            raw_date = str(track_meta.get('date') or track_meta.get('release_date') or '').strip()
            if raw_date and raw_date != 'None':
                year_only = raw_date[:4] 
                
                if ext == 'flac':
                    from mutagen.flac import FLAC
                    audio = FLAC(final_path)
                    audio['DATE'] = raw_date 
                    audio['YEAR'] = year_only
                    audio['ORIGINALDATE'] = raw_date
                    audio.save()
                    
                elif ext == 'm4a':
                    from mutagen.mp4 import MP4
                    audio = MP4(final_path)
                    audio['\xa9day'] = raw_date 
                    audio.save()
                    
                elif ext == 'mp3':
                    from mutagen.mp3 import MP3
                    from mutagen.id3 import ID3, TDRC, TYER
                    audio = MP3(final_path, ID3=ID3)
                    if audio.tags is None:
                        audio.add_tags()
                    audio.tags.add(TDRC(encoding=3, text=raw_date))
                    audio.tags.add(TYER(encoding=3, text=year_only))
                    audio.save()

                elif ext in ['opus', 'ogg']:
                    try:
                        from mutagen.oggopus import OggOpus
                        audio = OggOpus(final_path)
                    except Exception:
                        from mutagen.oggvorbis import OggVorbis
                        audio = OggVorbis(final_path)
                        
                    audio['DATE'] = raw_date 
                    audio['YEAR'] = year_only
                    audio['ORIGINALDATE'] = raw_date
                    audio.save()
        except Exception as e:
            LOGGER.debug(f"Gagal injeksi tanggal manual Amazon: {e}")
            
    await asyncio.to_thread(_inject_manual_tags)

    if upload:
        await track_upload(track_meta, user, disable_link=False)
        
    return track_meta
