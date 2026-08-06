# [GANTI SELURUH FILE: bot/helpers/beatport/metadata.py]

import copy
import re
import aiohttp
import os
import asyncio
import random
from config import Config 

# Import Mutagen untuk Tagging Lokal
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.mp3 import MP3, EasyMP3
from mutagen.id3 import TBPM, TKEY, TXXX, TPUB, TSRC, TPE4, TCOP

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .api import BeatportAPI, BeatportError
from bot.logger import LOGGER
from .manager import beatport_manager

FALLBACK_IMAGE_PATH = os.path.join(Config.WORK_DIR, "project-siesta.png")

QUALITY_MAP = {
    "lossless": "lossless",
    "high": "high",
    "medium": "medium"
}

def truncate_artist_list(artist_str: str, max_len: int = 200) -> str: 
    if len(artist_str) > max_len: return artist_str[:max_len] + "..."
    return artist_str

async def get_itunes_cover_url(metadata: dict, session: aiohttp.ClientSession) -> str | None:
    return None 

def custom_url_parse(link: str):
    match = re.search(r"beatport\.com/(?:[a-z]{2}/)?(?P<type>track|release|artist|playlists|chart)/.+?/(?P<id>\d+)", link)
    if not match: match = re.search(r"beatport\.com/(?:[a-z]{2}/)?(?P<type>track|release|artist|playlists|chart)/(?P<id>\d+)", link)
    if not match: raise BeatportError(f"URL tidak valid: {link}")
    
    m_type = match.group("type")
    if m_type == "release": m_type = "album"
    elif m_type in ["playlists", "chart"]: m_type = "playlist"
    
    return m_type, match.group("id"), {"is_chart": match.group("type") == "chart"}

async def _generate_artwork_url(dynamic_uri: str, size: int = 1400):
    if not dynamic_uri: return None
    res_pattern = re.compile(r"\d{3,4}x\d{3,4}")
    if re.search(res_pattern, dynamic_uri):
        dynamic_uri = re.sub(res_pattern, "{w}x{h}", dynamic_uri)
    return dynamic_uri.format(w=size, h=size)

async def _process_cover(metadata: dict, beatport_url: str):
    final = beatport_url
    if not final and os.path.exists(FALLBACK_IMAGE_PATH): final = FALLBACK_IMAGE_PATH
    return await create_cover_file(final, metadata)

# --- FUNGSI TAGGING LOKAL ---
async def write_extended_tags(filepath: str, meta: dict):
    """
    Menulis tag khusus: BPM, Key, CatNo, Label, UPC, ISRC, Barcode, Producer, Copyright.
    """
    try:
        ext = os.path.splitext(filepath)[1].lower()
        
        # 1. Handler M4A (iTunes)
        if ext in ['.m4a', '.mp4']:
            audio = MP4(filepath)
            
            # BPM
            if meta.get('bpm'):
                try: audio.tags['tmpo'] = [int(float(meta['bpm']))]
                except: audio.tags['----:com.apple.iTunes:BPM'] = str(meta['bpm']).encode('utf-8')

            # KEY
            if meta.get('key'):
                audio.tags['----:com.apple.iTunes:initialkey'] = str(meta['key']).encode('utf-8')
                audio.tags['----:com.apple.iTunes:KEY'] = str(meta['key']).encode('utf-8')

            # CATALOG NUMBER
            if meta.get('catalog_number'):
                audio.tags['----:com.apple.iTunes:CATALOGNUMBER'] = str(meta['catalog_number']).encode('utf-8')

            # COPYRIGHT (cpr)
            if meta.get('copyright'):
                audio.tags['\u00a9cpr'] = meta['copyright']
                audio.tags['----:com.apple.iTunes:cpr'] = str(meta['copyright']).encode('utf-8')
                audio.tags['----:com.apple.iTunes:COPYRIGHT'] = str(meta['copyright']).encode('utf-8')

            # LABEL
            if meta.get('label'):
                audio.tags['----:com.apple.iTunes:LABEL'] = str(meta['label']).encode('utf-8')
                audio.tags['\u00a9pub'] = meta['label'] 

            # ISRC
            if meta.get('isrc'):
                audio.tags['----:com.apple.iTunes:ISRC'] = str(meta['isrc']).encode('utf-8')

            # UPC / BARCODE
            if meta.get('upc'):
                audio.tags['----:com.apple.iTunes:UPC'] = str(meta['upc']).encode('utf-8')
                audio.tags['----:com.apple.iTunes:BARCODE'] = str(meta['upc']).encode('utf-8')

            # REMIXER
            if meta.get('remixer'):
                audio.tags['----:com.apple.iTunes:REMIXER'] = str(meta['remixer']).encode('utf-8')
            
            audio.save()

        # 2. Handler FLAC
        elif ext == '.flac':
            audio = FLAC(filepath)
            
            if meta.get('bpm'): audio.tags['BPM'] = str(meta['bpm'])
            
            if meta.get('key'): 
                audio.tags['INITIALKEY'] = str(meta['key'])
                audio.tags['KEY'] = str(meta['key'])
            
            if meta.get('catalog_number'): audio.tags['CATALOGNUMBER'] = str(meta['catalog_number'])
            
            if meta.get('copyright'):
                audio.tags['COPYRIGHT'] = str(meta['copyright'])
                audio.tags['cpr'] = str(meta['copyright'])

            if meta.get('label'): 
                audio.tags['LABEL'] = meta['label']
                audio.tags['ORGANIZATION'] = meta['label']
                audio.tags['PUBLISHER'] = meta['label']
            
            if meta.get('isrc'): audio.tags['ISRC'] = str(meta['isrc'])
            
            if meta.get('upc'):
                audio.tags['UPC'] = str(meta['upc'])
                audio.tags['BARCODE'] = str(meta['upc'])

            if meta.get('remixer'): audio.tags['REMIXER'] = str(meta['remixer'])

            audio.save()

        # 3. Handler MP3
        elif ext == '.mp3':
            audio = MP3(filepath, ID3=EasyMP3)
            from mutagen.id3 import ID3
            tags = ID3(filepath)
            
            if meta.get('bpm'): tags.add(TBPM(encoding=3, text=str(meta['bpm'])))
            if meta.get('key'): tags.add(TKEY(encoding=3, text=str(meta['key'])))
            if meta.get('catalog_number'): tags.add(TXXX(encoding=3, desc='CATALOGNUMBER', text=str(meta['catalog_number'])))
            if meta.get('label'): tags.add(TPUB(encoding=3, text=meta['label']))
            if meta.get('copyright'): tags.add(TCOP(encoding=3, text=str(meta['copyright'])))
            if meta.get('isrc'): tags.add(TSRC(encoding=3, text=str(meta['isrc'])))
            if meta.get('remixer'): tags.add(TPE4(encoding=3, text=str(meta['remixer'])))
            if meta.get('upc'): tags.add(TXXX(encoding=3, desc='BARCODE', text=str(meta['upc'])))
            
            tags.save()

    except Exception as e:
        LOGGER.warning(f"Gagal menulis extended tags Beatport: {e}")

# --- PROSES METADATA UTAMA ---

async def process_track_metadata(track_id: str, r_id: str, user: dict, pre_data: dict = None, fetch_stream: bool = True, album_pre_data: dict = None):
    user_id = user.get('user_id')
    active_client = beatport_manager.get_client(user_id)
    if not active_client: raise BeatportError("Tidak ada akun Beatport.")
    
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    # 1. Get Track Data
    track_data = pre_data
    if not track_data:
        for _ in range(2):
            try:
                track_data = await active_client.get_track(track_id)
                if track_data: break
            except: 
                await asyncio.sleep(1)
    
    if not track_data: raise BeatportError(f"Track {track_id} not found.")

    # 2. Get Album Data
    album_data = album_pre_data 
    if not album_data:
        try:
            rel_id = track_data.get("release", {}).get("id")
            if rel_id:
                album_data = await active_client.get_release(rel_id)
        except: pass
    
    if not album_data: album_data = {} 

    metadata['itemid'] = track_id
    metadata['title'] = track_data.get("name")
    if track_data.get("mix_name"): metadata['title'] += f" ({track_data.get('mix_name')})"
    
    artist_raw = ", ".join([a.get("name") for a in track_data.get("artists", [])])
    
    # Ambil Remixer
    remixers = track_data.get("remixers", [])
    remixer_raw = ", ".join([r.get("name") for r in remixers])
    metadata['remixer'] = remixer_raw
    
    albumartist_raw = ", ".join([a.get("name") for a in album_data.get("artists", [])])
    metadata['artist'] = truncate_artist_list(artist_raw)
    metadata['albumartist'] = truncate_artist_list(albumartist_raw)
    
    metadata['album'] = album_data.get("name", "Unknown Album")
    
    metadata['date'] = track_data.get("publish_date", "")[:10]
    metadata['year'] = metadata['date'][:4]
    metadata['explicit'] = track_data.get("explicit", False)
    
    metadata['tracknumber'] = str(track_data.get("number", 1)).zfill(2)
    metadata['totaltracks'] = str(album_data.get("track_count", 1))

    # [DATA EKSTRA LENGKAP]
    metadata['bpm'] = str(track_data.get('bpm', ''))
    
    key_data = track_data.get('key')
    if isinstance(key_data, dict): metadata['key'] = key_data.get('name')
    else: metadata['key'] = str(key_data) if key_data else ''

    # Catalog & Label
    metadata['catalog_number'] = track_data.get('release', {}).get('catalog_number') or album_data.get('catalog_number', '')
    metadata['label'] = track_data.get('release', {}).get('label', {}).get('name') or album_data.get('label', {}).get('name', '')
    metadata['publisher'] = metadata['label']
    
    # Generate Copyright
    if metadata['year'] and metadata['label']:
        metadata['copyright'] = f"© {metadata['year']} {metadata['label']}"
    else:
        metadata['copyright'] = ""

    # ISRC & UPC
    metadata['isrc'] = track_data.get('isrc', '')
    metadata['upc'] = track_data.get('release', {}).get('upc') or album_data.get('upc', '')
    
    # Cover Logic
    bp_cover = None
    if track_data.get("release", {}).get("image", {}).get("dynamic_uri"):
        bp_cover = await _generate_artwork_url(track_data.get("release").get("image").get("dynamic_uri"))
    elif album_data.get("image", {}).get("dynamic_uri"):
        bp_cover = await _generate_artwork_url(album_data.get("image").get("dynamic_uri"))
    
    metadata['cover'] = await _process_cover(metadata, bp_cover)
    metadata['thumbnail'] = await create_cover_file(await _generate_artwork_url(bp_cover, 80), metadata, True)

    # Stream Logic
    pref_qual = beatport_manager.get_user_quality(user_id)
    
    if pref_qual == "lossless":
        metadata['quality'] = "FLAC"
        metadata['extension'] = "flac"
    elif pref_qual == "high":
        metadata['quality'] = "AAC 256"
        metadata['extension'] = "m4a"
    else:
        metadata['quality'] = "AAC 128"
        metadata['extension'] = "m4a"

    metadata['download_url'] = None

    if fetch_stream:
        stream_loc = None
        target_q_code = QUALITY_MAP.get(pref_qual, "medium")

        try:
            await asyncio.sleep(random.uniform(1.0, 2.0)) 
            
            sd = await active_client.get_track_download(track_id, target_q_code)
            stream_loc = sd.get('location')
        except Exception:
            stream_loc = None

        if not stream_loc and pref_qual == "lossless":
            try:
                await asyncio.sleep(random.uniform(2.0, 3.0))
                
                sd = await active_client.get_track_download(track_id, QUALITY_MAP["high"])
                stream_loc = sd.get('location')
                
                if stream_loc:
                    metadata['quality'] = "AAC 256"
                    metadata['extension'] = "m4a"
            except Exception:
                pass 

        if not stream_loc:
            raise BeatportError(f"Gagal mendapatkan link download (Target: {pref_qual}).")
            
        metadata['download_url'] = stream_loc

    return metadata

async def process_album_metadata(album_id: str, r_id: str, user: dict):
    user_id = user.get('user_id')
    active_client = beatport_manager.get_client(user_id)
    if not active_client: raise BeatportError("No Beatport Account.")

    album_data = await active_client.get_release(album_id)
    if not album_data: raise BeatportError("Album not found.")
    
    tracks_raw = album_data.get("tracks", [])
    need_full_fetch = not tracks_raw or (tracks_raw and isinstance(tracks_raw[0], str))
        
    if need_full_fetch:
        tracks_raw = []
        p = 1
        while True:
            try:
                res = await active_client.get_release_tracks(album_id, page=p)
                if not res.get("results"): break
                tracks_raw.extend(res.get("results"))
                if not res.get("next"): break
                p += 1
                await asyncio.sleep(0.5)
            except: break

    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['itemid'] = album_id
    metadata['title'] = album_data.get("name")
    metadata['album'] = metadata['title']
    metadata['artist'] = album_data.get("artists", [{}])[0].get("name", "Unknown")
    metadata['type'] = 'album'
    metadata['provider'] = 'Beatport'

    metadata['date'] = album_data.get("publish_date", "")[:10]
    metadata['year'] = metadata['date'][:4]
    metadata['totaltracks'] = str(len(tracks_raw))
    metadata['totalvolume'] = "1"
    
    metadata['catalog_number'] = album_data.get('catalog_number', '')
    metadata['label'] = album_data.get('label', {}).get('name', '')
    if metadata['year'] and metadata['label']:
        metadata['copyright'] = f"© {metadata['year']} {metadata['label']}"
    metadata['upc'] = album_data.get('upc', '')

    pref_qual = beatport_manager.get_user_quality(user_id)
    metadata['quality'] = pref_qual.capitalize()

    bp_cover = await _generate_artwork_url(album_data.get("image", {}).get("dynamic_uri"))
    metadata['cover'] = await _process_cover(metadata, bp_cover)
    metadata['thumbnail'] = await create_cover_file(await _generate_artwork_url(bp_cover, 80), metadata, True)

    metadata['tracks'] = []
    album_explicit = False
    
    for i, track_item in enumerate(tracks_raw):
        try:
            t_data = track_item
            t_id = None
            if isinstance(track_item, dict):
                t_id = track_item.get('id')
                if not t_id and track_item.get('track'): 
                    t_data = track_item.get('track')
                    t_id = t_data.get('id')
            elif isinstance(track_item, str):
                t_id = track_item.split('/')[-1]

            if not t_id: continue

            t_meta = await process_track_metadata(str(t_id), r_id, user, 
                                                pre_data=t_data if isinstance(t_data, dict) else None, 
                                                fetch_stream=False, 
                                                album_pre_data=album_data)
            
            t_meta['tracknumber'] = str(i + 1).zfill(2)
            t_meta['totaltracks'] = metadata['totaltracks']
            t_meta['cover'] = metadata['cover']
            
            if not t_meta.get('copyright'): t_meta['copyright'] = metadata.get('copyright')

            if t_meta.get('explicit'): album_explicit = True
            metadata['tracks'].append(t_meta)
            
        except Exception as e:
            LOGGER.error(f"Skip track {i+1}: {e}")
            continue

    metadata['explicit'] = album_explicit
    if not metadata['tracks']: raise BeatportError("Album kosong/Gagal memproses track.")
    return metadata

async def process_artist_metadata(artist_id: str, r_id: str, user: dict):
    user_id = user.get('user_id')
    active_client = beatport_manager.get_client(user_id)
    if not active_client: 
        raise BeatportError("Tidak ada akun Beatport yang aktif.")

    artist_data = await active_client.get_artist(artist_id)
    if not artist_data: 
        raise BeatportError("Artis tidak ditemukan.")

    releases = []
    p = 1
    while True:
        try:
            res = await active_client.get_artist_releases(artist_id, page=p)
            results = res.get("results", [])
            if not results: 
                break
            releases.extend(results)
            if not res.get("next") or len(releases) >= res.get("count", 0): 
                break
            p += 1
            await asyncio.sleep(0.5)
        except Exception:
            break

    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['itemid'] = artist_id
    metadata['title'] = artist_data.get("name", "Unknown Artist")
    metadata['artist'] = metadata['title']
    metadata['type'] = 'artist'
    metadata['provider'] = 'Beatport'

    img_uri = artist_data.get("image", {}).get("dynamic_uri")
    bp_cover = await _generate_artwork_url(img_uri)
    metadata['cover'] = await _process_cover(metadata, bp_cover)
    metadata['thumbnail'] = await create_cover_file(await _generate_artwork_url(bp_cover, 80), metadata, True)

    metadata['releases'] = releases
    if not releases:
        raise BeatportError("Artis ini tidak memiliki rilis/album yang dapat diunduh.")
        
    return metadata

async def process_playlist_metadata(playlist_id: str, r_id: str, user: dict, extra: dict):
    user_id = user.get('user_id')
    active_client = beatport_manager.get_client(user_id)
    is_chart = extra.get("is_chart")
    
    # [FIX] FALLBACK LOGIC: Playlist <-> Chart
    # Jika endpoint playlist return 404, coba endpoint chart (dan sebaliknya)
    pl_data = None
    used_endpoint = "playlist"
    
    try:
        if is_chart:
            pl_data = await active_client.get_chart(playlist_id)
            used_endpoint = "chart"
        else:
            pl_data = await active_client.get_playlist(playlist_id)
            used_endpoint = "playlist"
    except Exception as e:
        if "404" in str(e):
            LOGGER.info(f"Beatport {used_endpoint} {playlist_id} not found, trying switch...")
            try:
                if used_endpoint == "playlist":
                    pl_data = await active_client.get_chart(playlist_id)
                    used_endpoint = "chart"
                    is_chart = True # Switch flag
                else:
                    pl_data = await active_client.get_playlist(playlist_id)
                    used_endpoint = "playlist"
                    is_chart = False
            except:
                raise BeatportError(f"Konten tidak ditemukan (ID: {playlist_id}).")
        else:
            raise e
    
    # Fetch Tracks dengan endpoint yang BENAR
    tracks = []
    p = 1
    fetch_func = active_client.get_chart_tracks if is_chart else active_client.get_playlist_tracks

    while True:
        try:
            res = await fetch_func(playlist_id, page=p)
            if not res.get("results"): break
            tracks.extend(res.get("results"))
            if len(tracks) >= res.get("count", 0): break
            p += 1
            await asyncio.sleep(0.5) 
        except: break

    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['title'] = pl_data.get("name")
    metadata['type'] = 'playlist'
    metadata['provider'] = 'Beatport'
    metadata['totaltracks'] = str(len(tracks))
    
    pref_qual = beatport_manager.get_user_quality(user_id)
    metadata['quality'] = pref_qual.capitalize()

    img_uri = pl_data.get("image", {}).get("dynamic_uri")
    if not img_uri and not is_chart and pl_data.get("release_images"):
        img_uri = pl_data.get("release_images")[0] 
        
    bp_cover = await _generate_artwork_url(img_uri)
    metadata['cover'] = await _process_cover(metadata, bp_cover)

    metadata['tracks'] = []
    album_cache = {}

    for i, t_item in enumerate(tracks):
        try:
            raw_t = t_item.get("track") if not is_chart else t_item
            if not raw_t: continue
            
            rel_id = raw_t.get("release", {}).get("id")
            alb_dat = None
            if rel_id:
                if rel_id in album_cache: alb_dat = album_cache[rel_id]
                else:
                    try:
                        alb_dat = await active_client.get_release(rel_id)
                        album_cache[rel_id] = alb_dat
                        await asyncio.sleep(0.2) 
                    except: pass

            t_meta = await process_track_metadata(str(raw_t['id']), r_id, user, 
                                                pre_data=raw_t, 
                                                fetch_stream=False, 
                                                album_pre_data=alb_dat)
            
            t_meta['tracknumber'] = str(i + 1).zfill(2)
            metadata['tracks'].append(t_meta)
        except: continue
    return metadata
