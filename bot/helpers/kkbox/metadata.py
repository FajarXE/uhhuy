# [GANTI FILE: bot/helpers/kkbox/metadata.py]

import copy
import re
import aiohttp
import asyncio
import logging
import os 
from datetime import datetime
from urllib.parse import urlparse
from config import Config 

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .manager import kkbox_manager, KKBoxError
from bot.logger import LOGGER

QUALITY_MAP_DISPLAY = {
    "128k": ("MP3 128k", "mp3"),
    "192k": ("MP3 192k", "mp3"),
    "320k": ("AAC 320k", "m4a"),
    "hifi": ("FLAC 16-bit", "flac"),
    "hires": ("FLAC 24-bit", "flac")
}
QUALITY_ORDER = ["hires", "hifi", "320k", "192k", "128k"]

def custom_url_parse(link: str):
    url = urlparse(link)
    path_match = None
    if url.hostname == 'play.kkbox.com':
        path_match = re.match(r'^\/(track|album|artist|playlist)\/([a-zA-Z0-9-_]{18})', url.path)
    elif url.hostname == 'www.kkbox.com':
        path_match = re.match(r'^\/[a-z]{2}\/[a-z]{2}\/(song|album|artist|playlist)\/([a-zA-Z0-9-_]{18})', url.path)
    else:
        raise KKBoxError(f'URL tidak valid: {link}')
    if not path_match:
        raise KKBoxError(f'URL tidak valid: {link}')
    
    type = path_match.group(1)
    if type == 'song': type = 'track'
    
    return type, path_match.group(2), {}

async def _process_cover(metadata: dict, url_template: str):
    size = 1400
    file_type = "jpg"
    
    url = url_template
    if not url: return None 

    if size > 2048:
        url = url.replace('fit/{width}x{height}', 'original')
        url = url.replace('cropresize/{width}x{height}', 'original')
    else:
        url = url.replace('{width}', str(size))
        url = url.replace('{height}', str(size))
    url = url.replace('{format}', file_type)
    
    return await create_cover_file(url, metadata)

async def _scrape_kkbox_date(album_id: str, known_prefix: str = None):
    regions = ['sg', 'my', 'tw', 'hk', 'jp']
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/"
    }

    async with aiohttp.ClientSession() as session:
        for region in regions:
            url = f"https://www.kkbox.com/{region}/en/album/{album_id}"
            try:
                async with session.get(url, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        
                        if known_prefix and len(known_prefix) == 7: 
                            escaped_prefix = re.escape(known_prefix)
                            smart_pattern = rf"{escaped_prefix}[-/\.](\d{{2}})"
                            match = re.search(smart_pattern, html)
                            if match:
                                day = match.group(1)
                                full_date = f"{known_prefix}-{day}"
                                LOGGER.info(f"KKBox Scrape ({region}): Smart Match ditemukan -> {full_date}")
                                return full_date

                        match = re.search(r'"datePublished":\s*"(\d{4}-\d{2}-\d{2})"', html)
                        if match: 
                            LOGGER.info(f"KKBox Scrape ({region}): Found JSON Date {match.group(1)}")
                            return match.group(1)
                        
                        match = re.search(r'<meta\s+property="music:release_date"\s+content="(\d{4}-\d{2}-\d{2})"', html)
                        if match: 
                            LOGGER.info(f"KKBox Scrape ({region}): Found Meta Date {match.group(1)}")
                            return match.group(1)

                        match = re.search(r'Release Date\s*[:：]\s*(\d{4}[-/\.]\d{2}[-/\.]\d{2})', html, re.IGNORECASE)
                        if match: 
                            raw_date = match.group(1).replace('/', '-').replace('.', '-')
                            LOGGER.info(f"KKBox Scrape ({region}): Found Text Date {raw_date}")
                            return raw_date

            except Exception as e:
                continue
                
    return None

async def _scrape_playlist_ids(playlist_id: str):
    regions = ['tw', 'hk', 'sg', 'my', 'jp']
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    async with aiohttp.ClientSession() as session:
        for region in regions:
            url = f"https://www.kkbox.com/{region}/en/playlist/{playlist_id}"
            try:
                async with session.get(url, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        matches = re.findall(r'\/song\/([a-zA-Z0-9-_]{10,})', html)
                        if matches:
                            found_ids = list(set(matches))
                            LOGGER.info(f"KKBox Scrape ({region}): Berhasil menemukan {len(found_ids)} lagu via Web Scraping.")
                            return found_ids
            except Exception:
                continue
    
    return []

async def process_track_metadata(track_id: str, r_id: str, user: dict, pre_data: dict = None, alb_info_pre: dict = None):
    client = user['kkbox_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    try:
        if pre_data:
            track_data = pre_data
        else:
            songs_list = await asyncio.to_thread(client.get_songs, [track_id])
            if not songs_list:
                raise KKBoxError(f"Track {track_id} tidak ditemukan.")
            track_data = songs_list[0]

        if alb_info_pre:
            alb_info = alb_info_pre
        else:
            album_raw_id = track_data.get('raw_album_id') or int(track_data['album_id'])
            try:
                album_data_more = await asyncio.to_thread(client.get_album_more, album_raw_id)
                if not album_data_more or 'info' not in album_data_more:
                    raise KKBoxError("Invalid get_album_more response")
                alb_info = album_data_more['info']
                # --- MENANGKAP LABEL/COMPANY ---
                if 'company' in album_data_more.get('info', {}):
                    alb_info['label'] = album_data_more['info']['company']
                else:
                    alb_info['label'] = ""
                # -------------------------------
                alb_info['num_tracks'] = len(album_data_more.get('song_list', {}).get('song', []))
            except Exception as e:
                alb_obj = track_data.get('album', {})
                alb_info = {
                    'album_name': alb_obj.get('name', 'Unknown Album'),
                    'artist_name': alb_obj.get('artist', {}).get('name', 'Unknown Artist'),
                    'album_date': alb_obj.get('release_date', ''),
                    'num_tracks': 1, 
                    'album_photo_info': {'url_template': alb_obj.get('images', [{}])[0].get('url', '')},
                    'label': '' # Default kosong
                }

    except Exception as e:
        LOGGER.error(f"KKBox: Gagal mendapatkan metadata track {track_id}: {e}")
        raise e

    metadata['itemid'] = track_id
    metadata['title'] = track_data.get('song_name') or track_data.get('text') or track_data.get('name')
    
    artists = []
    if 'artist_role' in track_data:
        if 'mainartist_list' in track_data['artist_role']:
            artists.extend(track_data['artist_role']['mainartist_list']['mainartist'])
        if 'featuredartist_list' in track_data['artist_role']:
            artists.extend(track_data['artist_role']['featuredartist_list']['featuredartist'])
    
    metadata['albumartist'] = alb_info.get('artist_name', 'Unknown Artist')
    
    if not artists:
        if 'artist' in track_data and 'name' in track_data['artist']:
             artists = [track_data['artist']['name']]
        else:
             artists = [metadata['albumartist']]
    
    metadata['artist'] = ", ".join(artists)
    metadata['album'] = alb_info.get('album_name', 'Unknown Album')
    
    # --- MENANGKAP ISRC ---
    metadata['isrc'] = track_data.get('isrc') or ""
    # ----------------------

    # --- MENANGKAP COMPOSER ---
    composers = []
    if 'composer' in track_data:
        comp_data = track_data['composer']
        if isinstance(comp_data, list):
            for c in comp_data:
                if 'name' in c: composers.append(c['name'])
        elif isinstance(comp_data, dict) and 'name' in comp_data:
            composers.append(comp_data['name'])
            
    metadata['composer'] = ", ".join(composers) if composers else ""
    # --------------------------

    # --- MENANGKAP LABEL & PUBLISHER ---
    metadata['label'] = alb_info.get('label') or alb_info.get('company') or ""
    metadata['publisher'] = metadata['label'] # Seringkali label dianggap publisher
    # -----------------------------------

    fixed_alb_date = alb_info.get('album_date')
    track_date = track_data.get('release_date')
    
    final_date = ""
    if fixed_alb_date and len(fixed_alb_date) >= 10:
        final_date = fixed_alb_date
    elif track_date and len(track_date) >= 10:
        final_date = track_date
    elif fixed_alb_date:
        final_date = fixed_alb_date
    elif track_date:
        final_date = track_date
        
    metadata['date'] = final_date
    metadata['year'] = final_date[:4] if final_date else ""

    # --- PERBAIKAN: ZERO PADDING (01, 02...) ---
    track_num = str(track_data.get('song_idx', 1))
    metadata['tracknumber'] = track_num.zfill(2)
    # -------------------------------------------

    metadata['totaltracks'] = str(alb_info.get('num_tracks', 1))
    metadata['totalvolume'] = str(alb_info.get('num_volumes', 1))
    
    metadata['genre'] = track_data.get('genre_name')
    metadata['explicit'] = bool(track_data.get('song_is_explicit', False))
    metadata['provider'] = 'KKBox'
    metadata['type'] = 'track'
    
    cover_template = ""
    if 'album_photo_info' in track_data:
        cover_template = track_data['album_photo_info']['url_template']
    elif 'images' in track_data.get('album', {}):
        cover_template = track_data['album']['images'][0]['url']
    elif 'album_photo_info' in alb_info:
        cover_template = alb_info['album_photo_info']['url_template']

    if cover_template:
        metadata['cover'] = await _process_cover(metadata, cover_template)
        metadata['thumbnail'] = await create_cover_file(cover_template.replace('{width}', '80').replace('{height}', '80').replace('{format}', 'jpg'), metadata, True)

    user_id = user.get('user_id')
    preferred_quality = kkbox_manager.get_user_quality(user_id)
    user_quality_order = QUALITY_ORDER[QUALITY_ORDER.index(preferred_quality):]
    
    chosen_quality_key = None
    avail_q = track_data.get('audio_quality', {})
    
    for q_key in user_quality_order:
        if q_key in avail_q and q_key in client.available_qualities:
            chosen_quality_key = q_key
            break
            
    if not chosen_quality_key:
        for q_key in reversed(QUALITY_ORDER):
             if q_key in avail_q and q_key in client.available_qualities:
                chosen_quality_key = q_key
                break

    if not chosen_quality_key:
        raise KKBoxError(f"Tidak ada kualitas yang kompatibel untuk track {track_id}")

    metadata['quality'], metadata['extension'] = QUALITY_MAP_DISPLAY[chosen_quality_key]
    
    dl_id = track_data.get('id')
    if 'song_more_url' in track_data:
         dl_id = track_data['song_more_url'].split('/')[-1]
         
    metadata['download_id'] = dl_id
    metadata['download_quality_key'] = chosen_quality_key
    
    return metadata

async def process_album_metadata(album_id: str, r_id: str, user: dict):
    client = user['kkbox_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    alb_info = None
    tracks_list = []
    is_fallback_mode = False

    try:
        album_resp = await asyncio.to_thread(client.get_album, album_id)
        v_data = album_resp.get('album') if 'album' in album_resp else album_resp
        if not v_data: raise KKBoxError("Respons get_album kosong.")

        raw_id = v_data.get('album_id') or v_data.get('id')
        try:
            album_data_more = await asyncio.to_thread(client.get_album_more, raw_id)
            if album_data_more and 'info' in album_data_more and 'song_list' in album_data_more:
                alb_info = album_data_more['info']
                # --- MENANGKAP LABEL DI LEVEL ALBUM ---
                if 'company' in album_data_more.get('info', {}):
                    alb_info['label'] = album_data_more['info']['company']
                # --------------------------------------
                tracks_list = album_data_more['song_list']['song']
                alb_info['num_tracks'] = len(tracks_list)
            else:
                pass 
        except Exception:
             pass 

        if not alb_info:
            is_fallback_mode = True
            raw_tracks = v_data.get('tracks', {})
            if isinstance(raw_tracks, dict) and 'data' in raw_tracks:
                data_tracks = raw_tracks['data']
            elif isinstance(raw_tracks, list):
                data_tracks = raw_tracks
            else:
                data_tracks = []

            alb_info = {
                'album_name': v_data.get('name'),
                'artist_name': v_data.get('artist', {}).get('name'),
                'album_date': v_data.get('release_date', ''),
                'album_is_explicit': v_data.get('explicit', False),
                'album_photo_info': {
                    'url_template': v_data.get('images', [{}])[0].get('url', '')
                },
                'label': '' # Default
            }
            
            for rt in data_tracks:
                if 'id' in rt:
                    rt['song_more_url'] = f"https://kkbox.com/song/{rt['id']}"
                    if 'artist' not in rt: 
                        rt['artist'] = {'name': alb_info['artist_name']}
                    tracks_list.append(rt)
            alb_info['num_tracks'] = len(tracks_list)

    except Exception as e:
        LOGGER.error(f"KKBox: Gagal mendapatkan metadata album {album_id}: {e}")
        raise e

    api_date = alb_info.get('album_date', '')
    if not api_date: api_date = ""
    
    final_date = api_date
    
    if len(final_date) < 10:
        LOGGER.info(f"KKBox: Tanggal API '{final_date}'. Memulai Scraping (Smart Prefix)...")
        scraped_date = await _scrape_kkbox_date(album_id, known_prefix=api_date)
        
        if scraped_date:
            final_date = scraped_date
            LOGGER.info(f"KKBox: Scrape Berhasil! Update ke: {scraped_date}")
        else:
            LOGGER.warning("KKBox: Scrape gagal. Mempertahankan tanggal API.")
    
    alb_info['album_date'] = final_date
    
    metadata['itemid'] = album_id
    metadata['title'] = alb_info.get('album_name')
    metadata['album'] = alb_info.get('album_name')
    metadata['artist'] = alb_info.get('artist_name')
    metadata['albumartist'] = alb_info.get('artist_name')
    
    metadata['date'] = final_date
    metadata['year'] = final_date[:4] if final_date else ""
    
    metadata['totaltracks'] = str(alb_info.get('num_tracks', 1))
    metadata['totalvolume'] = str(alb_info.get('num_volumes', 1))
    metadata['explicit'] = bool(alb_info.get('album_is_explicit', False))
    metadata['provider'] = 'KKBox'
    metadata['type'] = 'album'
    
    # --- MENANGKAP LABEL ALBUM ---
    metadata['label'] = alb_info.get('label') or alb_info.get('company') or ""
    metadata['publisher'] = metadata['label']
    # -----------------------------

    cover_template = alb_info['album_photo_info']['url_template']
    metadata['cover'] = await _process_cover(metadata, cover_template)
    metadata['thumbnail'] = await create_cover_file(cover_template.replace('{width}', '80').replace('{height}', '80').replace('{format}', 'jpg'), metadata, True)

    metadata['tracks'] = []
    
    for song_data in tracks_list:
        try:
            track_id = song_data['song_more_url'].split('/')[-1]
            use_pre_data = None if is_fallback_mode else song_data

            track_meta = await process_track_metadata(
                track_id, r_id, user, 
                pre_data=use_pre_data, 
                alb_info_pre=alb_info 
            )
            track_meta['cover'] = metadata['cover'] 
            track_meta['thumbnail'] = metadata['thumbnail']
            metadata['tracks'].append(track_meta)
        except Exception as e:
            LOGGER.warning(f"KKBox: Gagal memproses track {song_data.get('song_more_url', 'Unknown')}: {e}")
            continue

    if not metadata['tracks']:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk album {metadata['title']}")
    
    metadata['quality'] = metadata['tracks'][0]['quality']

    if len(metadata['date']) < 10:
        for t in metadata['tracks']:
            td = t.get('date', '')
            if td and len(td) >= 10:
                metadata['date'] = td
                metadata['year'] = td[:4]
                LOGGER.info(f"KKBox: Tanggal Album diperbarui dari metadata Track: {td}")
                break

    return metadata

async def process_artist_metadata(artist_id: str, r_id: str, user: dict):
    client = user['kkbox_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"

    try:
        # Fetch artist profile
        artist_data = await asyncio.to_thread(client.get_artist, artist_id)
        if not artist_data:
            raise KKBoxError("Artis tidak ditemukan.")

        # Fetch artist albums with pagination
        limit = 50  # Tetap gunakan 50 untuk menghindari 400 Bad Request
        offset = 0
        albums_list = []
        
        while True:
            try:
                # Gunakan artist_id langsung BUKAN raw_id numerik
                albums = await asyncio.to_thread(client.get_artist_albums, artist_id, limit, offset)
                if not albums: # albums akan kosong/[] jika habis
                    break
                    
                albums_list.extend(albums)
                
                # Check pagination bounds
                if len(albums) < limit:
                    break
                offset += limit
                
            except Exception as e:
                LOGGER.warning(f"Berhenti mengambil halaman album artis (offset {offset}): {e}")
                break

    except Exception as e:
        LOGGER.error(f"KKBox: Gagal mendapatkan metadata artist {artist_id}: {e}")
        raise e

    metadata['itemid'] = artist_id
    metadata['title'] = artist_data.get('name', 'Unknown Artist')
    metadata['artist'] = metadata['title']
    metadata['type'] = 'artist'
    metadata['provider'] = 'KKBox'

    # Process Artist Image
    images = artist_data.get('images', [])
    if images:
        cover_template = images[0].get('url')
        if cover_template:
            metadata['cover'] = await _process_cover(metadata, cover_template)
            metadata['thumbnail'] = await create_cover_file(
                cover_template.replace('{width}', '80').replace('{height}', '80').replace('{format}', 'jpg'), 
                metadata, 
                True
            )

    metadata['releases'] = albums_list
    if not albums_list:
        raise KKBoxError("Artis ini tidak memiliki rilis/album yang dapat diunduh.")

    return metadata

async def process_playlist_metadata(playlist_id: str, r_id: str, user: dict):
    client = user['kkbox_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"

    try:
        playlists_list = await asyncio.to_thread(client.get_playlists, [playlist_id])
        if not playlists_list:
            raise KKBoxError(f"Playlist {playlist_id} tidak ditemukan.")
        pl_data = playlists_list[0]
    except Exception as e:
        LOGGER.error(f"KKBox: Gagal mendapatkan metadata playlist {playlist_id}: {e}")
        raise e

    metadata['itemid'] = playlist_id
    metadata['title'] = pl_data.get('title', 'Unknown Playlist')
    owner = pl_data.get('owner', {})
    metadata['artist'] = owner.get('name', 'Unknown User')
    metadata['albumartist'] = metadata['artist']
    metadata['type'] = 'playlist'
    metadata['provider'] = 'KKBox'
    
    raw_date = pl_data.get('updated_at')
    metadata['date'] = ""
    if raw_date:
        if isinstance(raw_date, str):
            metadata['date'] = raw_date[:10]
        elif isinstance(raw_date, (int, float)):
            try:
                ts = float(raw_date)
                if ts > 10000000000: ts = ts / 1000
                metadata['date'] = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
            except Exception:
                pass
    
    metadata['year'] = metadata['date'][:4] if metadata['date'] else ""

    images = pl_data.get('images', [])
    if images:
        cover_template = images[0]['url']
        metadata['cover'] = await _process_cover(metadata, cover_template)
        metadata['thumbnail'] = await create_cover_file(cover_template.replace('{width}', '80').replace('{height}', '80').replace('{format}', 'jpg'), metadata, True)

    metadata['tracks'] = []
    
    raw_tracks = pl_data.get('tracks', {}).get('data', [])
    
    if not raw_tracks:
        try:
            LOGGER.info(f"KKBox: Playlist tracks kosong di respons awal. Mencoba API Tracks untuk {playlist_id}...")
            fetched_tracks = await asyncio.to_thread(client.get_playlist_tracks, playlist_id)
            if fetched_tracks and isinstance(fetched_tracks, list):
                raw_tracks = fetched_tracks
                LOGGER.info(f"KKBox: Berhasil mengambil {len(raw_tracks)} tracks via API.")
            else:
                LOGGER.warning("KKBox: API Playlist tracks mengembalikan data kosong.")
        except Exception as e:
            LOGGER.warning(f"KKBox: Gagal fetch playlist tracks via API: {e}")

    if not raw_tracks:
        try:
            LOGGER.info(f"KKBox: API Gagal. Memulai Web Scraping untuk ID {playlist_id}...")
            scraped_ids = await _scrape_playlist_ids(playlist_id)
            if scraped_ids:
                raw_tracks = [{'id': sid} for sid in scraped_ids]
                LOGGER.info(f"KKBox: Berhasil scraping {len(raw_tracks)} tracks.")
            else:
                LOGGER.error("KKBox: Scraping juga gagal menemukan lagu.")
        except Exception as e:
            LOGGER.error(f"KKBox: Error saat scraping: {e}")

    for song_data in raw_tracks:
        try:
            track_id = song_data.get('id')
            if not track_id: continue

            track_meta = await process_track_metadata(
                track_id, r_id, user,
                pre_data=song_data if 'song_name' in song_data else None 
            )
            metadata['tracks'].append(track_meta)
        except Exception as e:
            LOGGER.warning(f"KKBox: Gagal memproses track playlist {track_id}: {e}")
            continue

    if not metadata['tracks']:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk playlist {metadata['title']}")

    metadata['totaltracks'] = len(metadata['tracks'])
    if metadata['tracks']:
        metadata['quality'] = metadata['tracks'][0]['quality']

    return metadata
