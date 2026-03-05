# [GANTI SELURUH FILE: bot/helpers/beatstars/handler.py]

import os
import re
import aiohttp
import aiofiles
import asyncio
from datetime import datetime
from urllib.parse import urlparse
from bot.logger import LOGGER
from bot.helpers.uploder import track_upload, artist_upload, album_upload
from bot.helpers.metadata import set_metadata, get_audio_extension
from bot.helpers.utils import post_art_poster, zip_handler, fetch_zip_settings, download_file, run_concurrent_tasks

# Import Mutagen
try:
    from mutagen.id3 import ID3, TPE2, COMM, TSSE, TENC
except ImportError:
    LOGGER.error("Mutagen belum terinstall. Fitur patching metadata tidak akan berjalan.")
    ID3, TPE2, COMM, TSSE, TENC = None, None, None, None, None

# Headers lengkap
ALGOLIA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "x-algolia-api-key": "b3513eb709fe8f444b4d5c191b63ea47", 
    "x-algolia-application-id": "NMMGZJQ6QI",
    "Origin": "https://www.beatstars.com",
    "Referer": "https://www.beatstars.com/",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "same-site"
}

PLACEHOLDER_COVER = "https://www.beatstars.com/assets/img/placeholder-track.png"

# --- HELPER FORMATTING ---
def parse_metadata_rich(data_list, tags_list=None, bpm=None):
    extracted = []
    if data_list:
        iterable = data_list.values() if isinstance(data_list, dict) else data_list
        for item in iterable:
            if isinstance(item, str):
                extracted.append(item)
            elif isinstance(item, dict):
                name = item.get('name') or item.get('slug') or item.get('title')
                if name:
                    extracted.append(str(name))
    
    if tags_list:
        if isinstance(tags_list, list):
            for tag in tags_list[:5]: 
                tag_name = ""
                if isinstance(tag, str):
                    tag_name = tag
                elif isinstance(tag, dict):
                    tag_name = tag.get('name', '')
                
                if tag_name and tag_name not in extracted:
                    extracted.append(tag_name)
        elif isinstance(tags_list, dict):
            for key, val in tags_list.items():
                if len(extracted) >= 10: break 
                if isinstance(val, str) and val not in extracted:
                    extracted.append(val)

    if bpm:
        extracted.append(f"{bpm} BPM")

    return ", ".join(extracted) if extracted else "BeatStars"

def format_date(timestamp):
    try:
        if not timestamp:
            return ""
        dt_object = datetime.fromtimestamp(int(timestamp))
        return dt_object.strftime("%Y-%m-%d")
    except Exception:
        return str(timestamp)

def clean_cover_url(url):
    if not url: return None
    url = url.replace(r'\/', '/')
    if "://" not in url and "//" in url:
        url = url.replace("//", "/")
    return url

# --- HELPER BARU: FIX EXTENSION ---
async def fix_extension(filepath):
    try:
        if not os.path.exists(filepath):
            return filepath
        real_ext = await get_audio_extension(filepath)
        current_ext = filepath.split('.')[-1].lower()
        if real_ext == 'm4a': real_ext = 'm4a' 
        
        if real_ext != current_ext:
            new_filepath = os.path.splitext(filepath)[0] + "." + real_ext
            os.rename(filepath, new_filepath)
            LOGGER.info(f"File direname sesuai konten: {current_ext} -> {real_ext}")
            return new_filepath
    except Exception as e:
        LOGGER.warning(f"Gagal cek ekstensi file: {e}")
    return filepath

# --- MANUAL METADATA PATCHER (AGRESSIVE CLEANER) ---
def patch_metadata_manual(filepath, album_artist):
    if not ID3: return
    try:
        audio = ID3(filepath)
    except Exception:
        return
    try:
        keys_to_delete = []
        for key in audio.keys():
            if key.startswith("COMM") or key.startswith("TENC") or key.startswith("TSSE") or key.startswith("TXXX"):
                keys_to_delete.append(key)
                continue
            frame = audio[key]
            if hasattr(frame, 'text'): 
                for text_val in frame.text:
                    text_str = str(text_val).lower()
                    if "processed by" in text_str or "sox" in text_str:
                        keys_to_delete.append(key)
                        break
        for key in list(set(keys_to_delete)): 
            if key in audio: del audio[key]
        if album_artist:
            audio.add(TPE2(encoding=3, text=str(album_artist)))
        audio.save(v2_version=3, v1=2)
    except Exception as e:
        LOGGER.error(f"Gagal patching metadata manual: {e}")


# --- LOCAL COVER DOWNLOADER ---
async def download_local_cover(session, url, folderpath):
    if not url: return PLACEHOLDER_COVER
    filename = "cover.jpg"
    filepath = os.path.join(folderpath, filename)
    try:
        async with session.get(url, allow_redirects=True, timeout=15) as resp:
            if resp.status == 200:
                content = await resp.read()
                if not content: return PLACEHOLDER_COVER
                with open(filepath, 'wb') as f: f.write(content)
                return filepath
            else:
                return PLACEHOLDER_COVER
    except Exception:
        return PLACEHOLDER_COVER

# --- HANDLER UTAMA ---
async def start_beatstars(link: str, user: dict):
    parsed = urlparse(link)
    path = parsed.path.strip("/")
    path_parts = path.split("/")

    if path.startswith("beat/") or "/beat/" in link:
        track_regex = r'(\d+)$'
        track_match = re.search(track_regex, path)
        if track_match:
            track_id = track_match.group(1)
            LOGGER.info(f"BeatStars Track Mode: ID {track_id}")
            await process_single_track(user, track_id)
        else:
            raise Exception("Link Beat tidak valid: Tidak dapat menemukan ID Lagu.")
    else:
        if not path_parts or not path_parts[0]:
             raise Exception("Link tidak valid: Tidak dapat menemukan username artis.")
        permalink = path_parts[0]
        reserved_words = ['beat', 'tracks', 'feed', 'services', 'publishing', 'dashboard', 'playlists', 'collection', 'musician']
        
        if permalink.lower() in reserved_words:
             raise Exception(f"Link tidak valid: '{permalink}' adalah halaman sistem, bukan nama artis.")
             
        LOGGER.info(f"BeatStars Artist Mode: {permalink}")
        await process_artist(user, permalink)

# --- PROCESS SINGLE TRACK ---
async def process_single_track(user, track_id):
    url = f"https://main.v2.beatstars.com/beat?id={track_id}&fields=details"
    
    async with aiohttp.ClientSession(headers=ALGOLIA_HEADERS) as session:
        async with session.get(url) as resp:
            if resp.status != 200: raise Exception(f"BeatStars API Error: {resp.status}")
            data = await resp.json()
    
        if not data.get('response', {}).get('data'): raise Exception("Track tidak ditemukan.")
        details = data['response']['data']['details']
        
        folderpath = f"{user['bot_msg'].chat.id}-beatstars-{details.get('track_id')}"
        os.makedirs(folderpath, exist_ok=True)

        raw_cover = details.get('artwork', {}).get('original')
        clean_url = clean_cover_url(raw_cover)
        local_cover_path = await download_local_cover(session, clean_url, folderpath)

    release_date_fmt = format_date(details.get('release_date_time', 0))
    artist_name = details.get('musician', {}).get('display_name')
    track_title = details.get('title')
    bpm = details.get('bpm', 0)
    tags = details.get('tags', []) 
    duration_ms = details.get('duration', 0)
    
    copyright_txt = details.get('copyright', '') 
    if not copyright_txt:
        year = release_date_fmt[:4] if release_date_fmt else "2024"
        copyright_txt = f"© {year} {artist_name}"

    rich_genre = parse_metadata_rich(details.get('genre', []), tags, bpm)

    filename = f"{artist_name} - {track_title}.mp3"
    filename = re.sub(r'[\\/*?:"<>|]', "", filename)
    filepath = f"{folderpath}/{filename}"

    stream_url = details.get('stream_url')
    if not stream_url:
        stream_url = f"https://main.v2.beatstars.com/stream?id={details.get('track_id')}&return=audio"

    # --- FULL ARIA2 + HYBRID AIOHTTP FALLBACK ---
    details_aria = {
        'msg': user['bot_msg'],
        'title': track_title,
        'type': 'Track',
        'headers': ALGOLIA_HEADERS # Inject Spoofing Header
    }
    
    err = await download_file(stream_url, filepath, retries=1, details=details_aria)
    if err:
        LOGGER.warning(f"BeatStars: Aria2 ditolak. Mengaktifkan AIOHTTP Turbo Fallback...")
        async with aiohttp.ClientSession(headers=ALGOLIA_HEADERS) as session:
            async with session.get(stream_url) as r:
                r.raise_for_status()
                async with aiofiles.open(filepath, 'wb') as f:
                    async for chunk in r.content.iter_chunked(256 * 1024):
                        if chunk: await f.write(chunk)
    # --------------------------------------------

    filepath = await fix_extension(filepath)

    meta = {
        'title': track_title, 'artist': artist_name, 'albumartist': artist_name,
        'performer': artist_name, 'composer': artist_name, 'album': f"{artist_name} - Singles",
        'tracknumber': 1, 'totaltracks': 1, 'volume': 1, 'totalvolume': 1,
        'copyright': copyright_txt, 'isrc': '', 'release_date': release_date_fmt,
        'date': release_date_fmt[:4] if release_date_fmt else '', 'cover': local_cover_path,
        'provider': 'BeatStars', 'type': 'track', 'itemid': str(details.get('track_id')),
        'genre': rich_genre, 'duration': str(duration_ms), 'explicit': False,
        'description': None, 'comment': None, 'filepath': filepath, 'folderpath': folderpath
    }

    await set_metadata(meta, user['user_id'])
    patch_metadata_manual(filepath, artist_name)
    await track_upload(meta, user)


# --- PROCESS ARTIST (ALBUM BATCH MODE) ---
async def process_artist(user, permalink):
    async with aiohttp.ClientSession(headers=ALGOLIA_HEADERS) as session:
        artist_url = f"https://main.v2.beatstars.com/musician?permalink={permalink}"
        async with session.get(artist_url) as resp:
            if resp.status != 200: raise Exception(f"Gagal mengambil profil artis: {resp.status}")
            artist_data = await resp.json()
        
        try: user_id_num = int(artist_data['response']['data']['profile']['user_id'])
        except: raise Exception("Profil artis tidak valid.")
            
        member_id = f"MR{user_id_num}"
        query_url = "https://nmmgzjq6qi-dsn.algolia.net/1/indexes/public_prod_inventory_track_index_bycustom/query?x-algolia-agent=Algolia%20for%20JavaScript%20(4.12.0)%3B%20Browser"
        
        all_tracks = []
        page = 0
        
        await user['bot_msg'].edit(f"Mengambil daftar lagu: {permalink}...")
        
        folderpath = f"{user['bot_msg'].chat.id}-beatstars-artist-{permalink}"
        os.makedirs(folderpath, exist_ok=True)
        
        while True:
            payload = {
                "query": "", "page": page, "hitsPerPage": 1000, "facets": ["*"],
                "facetFilters": [[f"profile.memberId:{member_id}"]], "maxValuesPerFacet": 1000
            }
            async with session.post(query_url, json=payload) as resp:
                if resp.status != 200: break
                search_res = await resp.json()

            hits = search_res.get('hits', [])
            if not hits: break
            
            for hit in hits:
                track_id = hit.get('v2Id')
                stream_url = f"https://main.v2.beatstars.com/stream?id={track_id}&return=audio"
                raw_cover = hit.get('artwork', {}).get('sizes', {}).get('original')
                clean_url = clean_cover_url(raw_cover)
                
                ts = hit.get('releaseTimestamp') or hit.get('releaseDate') or 0
                date_fmt = format_date(ts)
                
                artist_name = hit.get('metadata', {}).get('artistName')
                bpm = hit.get('metadata', {}).get('bpm', 0)
                tags = hit.get('metadata', {}).get('tags', [])
                rich_genre = parse_metadata_rich(hit.get('metadata', {}).get('genres', []), tags, bpm)
                copyright_txt = f"© {date_fmt[:4] if date_fmt else '2024'} {artist_name}"

                all_tracks.append({
                    'title': hit.get('title'), 'artist': artist_name, 'albumartist': artist_name,
                    'performer': artist_name, 'composer': artist_name, 'album': f"{artist_name} - BeatStars Collection",
                    'cover': clean_url, 'itemid': str(track_id), 'url': stream_url, 'genre': rich_genre,
                    'copyright': copyright_txt, 'isrc': '', 'volume': 1, 'totalvolume': 1,
                    'duration': str(hit.get('duration', '')), 'explicit': False, 'release_date': date_fmt,
                    'date': date_fmt[:4] if date_fmt else '', 'description': None, 'comment': None
                })
            page += 1
            if page >= search_res.get('nbPages', 0): break

    if not all_tracks: raise Exception("Tidak ada track ditemukan.")

    album_meta = {
        'type': 'album', 'title': f"Tracks by {permalink}", 'artist': all_tracks[0]['artist'],
        'albumartist': all_tracks[0]['artist'], 'cover': all_tracks[0]['cover'], 'provider': 'BeatStars',
        'folderpath': folderpath, 'poster_msg': None, 'zip_path': None, 'tracks': []
    }

    # --- [FIX UI] KIRIM POSTER DI AWAL SEBELUM DOWNLOAD ---
    try:
        album_meta['poster_msg'] = await post_art_poster(user, album_meta)
    except Exception as e:
        LOGGER.error(f"Gagal mengirim poster: {e}")
    # ------------------------------------------------------

    LOGGER.info(f"Ditemukan {len(all_tracks)} track. Memulai unduhan...")

    # --- FUNGSI WORKER CONCURRENT ---
    async def _process_artist_track(t, i, total_items):
        try:
            filename = f"{t['artist']} - {t['title']}.mp3"
            filename = re.sub(r'[\\/*?:"<>|]', "", filename)
            filepath = f"{folderpath}/{filename}"
            
            details_aria = {'headers': ALGOLIA_HEADERS}
            err = await download_file(t['url'], filepath, retries=1, details=details_aria)
            
            if err:
                LOGGER.warning(f"BeatStars: Aria2 gagal. Fallback AIOHTTP Turbo: {t['title']}")
                async with aiohttp.ClientSession(headers=ALGOLIA_HEADERS) as fallback_session:
                    async with fallback_session.get(t['url']) as r:
                        r.raise_for_status()
                        async with aiofiles.open(filepath, 'wb') as f:
                            async for chunk in r.content.iter_chunked(256 * 1024):
                                if chunk: await f.write(chunk)
            
            filepath = await fix_extension(filepath)
            
            t['filepath'] = filepath
            t['folderpath'] = folderpath
            t['tracknumber'] = i + 1
            t['totaltracks'] = total_items
            t['type'] = 'track'
            
            async with aiohttp.ClientSession(headers=ALGOLIA_HEADERS) as img_session:
                local_cov = await download_local_cover(img_session, t['cover'], folderpath)
            t['cover'] = local_cov

            await set_metadata(t, user['user_id'])
            patch_metadata_manual(filepath, t['albumartist'])
            return t
        except Exception as e:
            LOGGER.error(f"Error track {t['title']}: {e}")
            return None
    # --------------------------------

    tasks = [_process_artist_track(t, i, len(all_tracks)) for i, t in enumerate(all_tracks)]
    update_details = {
        'msg': user['bot_msg'], 
        'title': f"Tracks by {permalink}", 
        'type': 'Artist',
        'action': 'Download'
    }
    
    # Eksekusi Pararel Penuh!
    results = await run_concurrent_tasks(tasks, update_details, limit=4)
    successful_tracks = [r for r in results if r]

    if not successful_tracks: raise Exception("Gagal mengunduh semua track.")

    album_meta['tracks'] = successful_tracks

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    if artist_zip or album_zip or playlist_zip:
        await edit_message(user['bot_msg'], "Sedang membuat file Zip...")
        album_meta['zip_path'] = await zip_handler(folderpath)

    await edit_message(user['bot_msg'], "🚀 Memproses Upload...")
    await album_upload(album_meta, user)
