# [GANTI FILE: bot/helpers/deezer/metadata.py]

import copy
import re
import asyncio
from datetime import datetime
from bot.settings import bot_set
import aiohttp
import urllib.parse
import logging
import os
from difflib import SequenceMatcher

from config import Config 

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .dzapi import DeezerAPI 
from bot.logger import LOGGER

from .manager import deezer_manager, DeezerError

FALLBACK_IMAGE_PATH = os.path.join(Config.WORK_DIR, "project-siesta.png")

# --- 1. CLEANING UTILS ---

def clean_string_simple(text):
    if not text: return ""
    text = str(text).lower()
    text = re.sub(r'[^a-z0-9]', '', text)
    return text

def extract_label_from_copyright(text):
    if not text: return None
    clean = re.sub(r'(?:℗|©|^)\s*(?:\d{4})?\s*', '', text)
    separators = [
        ", a division of", ", a unit of", " under exclusive license", 
        " licensed to", " distributed by", ", courtesy of", " / ", 
        " exclusively distributed by", " joint venture with"
    ]
    temp_clean = clean.lower()
    for sep in separators:
        if sep in temp_clean:
            clean = clean[:temp_clean.find(sep)]
            break
    clean = re.sub(r'(?i)^(under exclusive license to|licensed to|distributed by)\s*', '', clean)
    return clean.strip()

# --- 2. DEEZER PUBLIC API HELPERS ---

async def fetch_deezer_public_album(album_id, session):
    """Ambil data Album dari Public API (untuk Genre & UPC)."""
    if not album_id or str(album_id) == '0': return {}
    try:
        url = f"https://api.deezer.com/album/{album_id}"
        async with session.get(url) as resp:
            if resp.status == 200: return await resp.json()
    except: pass
    return {}

async def fetch_deezer_public_track(track_id, session):
    """Ambil data Track dari Public API (untuk Composer)."""
    if not track_id: return {}
    try:
        url = f"https://api.deezer.com/track/{track_id}"
        async with session.get(url) as resp:
            if resp.status == 200: return await resp.json()
    except: pass
    return {}

# --- 3. ITUNES LOGIC ---

async def fetch_itunes_lookup(id_val, id_type, country, session):
    try:
        base = "https://itunes.apple.com/lookup"
        if id_type == 'upc':
            url = f"{base}?upc={id_val}&entity=album&limit=1&country={country}"
        else:
            url = f"{base}?id={id_val}&entity=album&country={country}"
        async with session.get(url) as resp:
            data = await resp.json()
            if data.get('resultCount', 0) > 0:
                return data['results'][0]
    except: pass
    return None

async def search_itunes_brute_force(artist, title, country, session):
    try:
        term = urllib.parse.quote(f"{artist} {title}")
        url = f"https://itunes.apple.com/search?term={term}&entity=song&media=music&limit=10&country={country}"
        async with session.get(url) as resp:
            data = await resp.json()
            results = data.get('results', [])
            clean_q_artist = clean_string_simple(artist)
            clean_q_title = clean_string_simple(title)
            for item in results:
                it_artist = clean_string_simple(item.get('artistName', ''))
                it_track = clean_string_simple(item.get('trackName', ''))
                if (clean_q_artist in it_artist or it_artist in clean_q_artist) and \
                   (clean_q_title in it_track or it_track in clean_q_title):
                    return item.get('collectionId')
    except: pass
    return None

async def get_extended_itunes_info(metadata: dict, session: aiohttp.ClientSession) -> dict:
    itunes_data = {
        'cover_url': None, 'date': None, 'copyright': None, 
        'genre': None, 'label': None, 'found': False
    }
    COUNTRIES = ['ID', 'US', 'GB', 'JP', 'AU', 'DE']

    if metadata.get('upc') and metadata['upc'] not in ["0", ""]:
        for country in COUNTRIES:
            res = await fetch_itunes_lookup(metadata['upc'], 'upc', country, session)
            if res: return parse_itunes_item(res)

    dz_artist = metadata.get('albumartist') or metadata.get('artist', '')
    dz_title = metadata.get('title', '')
    if not (dz_artist and dz_title): return itunes_data

    target_collection_id = None
    found_country = 'US'

    for country in COUNTRIES:
        col_id = await search_itunes_brute_force(dz_artist, dz_title, country, session)
        if col_id:
            target_collection_id = col_id
            found_country = country
            break 
    
    if target_collection_id:
        album_details = await fetch_itunes_lookup(target_collection_id, 'id', found_country, session)
        if album_details:
            return parse_itunes_item(album_details)

    return itunes_data

def parse_itunes_item(item):
    data = {'found': True, 'cover_url': None, 'date': None, 'copyright': None, 'genre': None, 'label': None}
    if item.get('artworkUrl100'):
        data['cover_url'] = item['artworkUrl100'].replace('100x100bb.jpg', '10000x10000bb.jpg')
    if item.get('releaseDate'):
        data['date'] = item['releaseDate'].split('T')[0]
    if item.get('copyright'):
        data['copyright'] = item['copyright']
        data['label'] = extract_label_from_copyright(item['copyright'])
    if item.get('primaryGenreName'):
        data['genre'] = item['primaryGenreName']
    return data

# --- 4. MUSICBRAINZ FALLBACK ---
async def get_musicbrainz_info(metadata: dict, session: aiohttp.ClientSession) -> dict:
    mb_data = {'label': None, 'date': None, 'copyright': None, 'genre': None}
    headers = {'User-Agent': 'SiestaBot/2.0', 'Accept': 'application/json'}
    artist = metadata.get('albumartist') or metadata.get('artist', '')
    album = metadata.get('album', '')
    if not (artist and album): return mb_data
    
    query = f'artist:"{artist}" AND release:"{album}"'
    try:
        url = f"https://musicbrainz.org/ws/2/release?query={urllib.parse.quote(query)}&fmt=json&limit=1&inc=tags"
        async with session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get('releases'):
                    rel = data['releases'][0]
                    if rel.get('date'): mb_data['date'] = rel['date']
                    if rel.get('label-info'):
                        l = rel['label-info'][0].get('label', {})
                        if l.get('name'): mb_data['label'] = l['name']
                    if rel.get('tags'):
                        sorted_tags = sorted(rel['tags'], key=lambda x: x.get('count', 0), reverse=True)
                        if sorted_tags:
                            mb_data['genre'] = sorted_tags[0].get('name', '').title()
    except: pass
    return mb_data

async def get_musicbrainz_cover_url(metadata: dict, session: aiohttp.ClientSession) -> str | None:
    try:
        if metadata.get('upc') and metadata['upc'] not in ["0", ""]:
            mb_url = f"https://musicbrainz.org/ws/2/release?query=barcode:{metadata['upc']}&fmt=json"
            async with session.get(mb_url, headers={'User-Agent': 'SiestaBot/2.0'}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('releases') and len(data['releases']) > 0:
                        release_id = data['releases'][0]['id']
                        caa_api = f"https://coverartarchive.org/release/{release_id}"
                        async with session.get(caa_api) as caa_resp:
                            if caa_resp.status == 200:
                                caa_data = await caa_resp.json()
                                if caa_data.get('images') and len(caa_data['images']) > 0:
                                    for img in caa_data['images']:
                                        if img.get('front'): return img['image']
                                    return caa_data['images'][0]['image']
    except Exception as e:
        pass
    return None


# --- MAIN LOGIC ---
async def process_track_metadata(track_id, r_id, cover=None, 
    thumbnail=None, total_tracks=None, album_genre=None, total_disks=None, user: dict = None): 
    
    if not user: raise DeezerError("User arg required")
    deezerapi = user['deezer_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"

    # --- DEEZER DATA (INTERNAL) ---
    try:
        raw_meta_data = await deezerapi.get_track_data(track_id)
        t_meta_api = raw_meta_data.get('FALLBACK', raw_meta_data)
    except: t_meta_api = {} 

    try:
        raw_meta_page = await deezerapi.get_track(track_id)
        t_meta_page = raw_meta_page.get('DATA', {}) 
        t_meta_page = t_meta_page.get('FALLBACK', t_meta_page) 
    except: raise DeezerError(f"Deezer : Track not available")
    
    get_val = lambda k, d=None: t_meta_page.get(k) or t_meta_api.get(k) or d

    metadata['itemid'] = track_id
    metadata['provider'] = 'Deezer'
    metadata['type'] = 'track'
    metadata['title'] = get_val('SNG_TITLE', '')
    if get_val('VERSION'): metadata['title'] += f' ({get_val("VERSION")})'
    
    metadata['album'] = get_val('ALB_TITLE', '')
    metadata['albumartist'] = get_val('ART_NAME', '')
    metadata['artist'] = get_artists_name(t_meta_page) or get_artists_name(t_meta_api)
    
    metadata['tracknumber'] = str(get_val('TRACK_NUMBER', '1')).zfill(2)
    metadata['volume'] = str(get_val('DISK_NUMBER', '1'))
    if total_tracks: metadata['totaltracks'] = str(total_tracks)
    if total_disks: metadata['totalvolume'] = str(total_disks)
    
    metadata['isrc'] = get_val('ISRC', '')

    # --- 1. PRODUCER & COMPOSER (INTERNAL CHECK) ---
    contributors = t_meta_page.get('CONTRIBUTORS') or t_meta_api.get('CONTRIBUTORS') or []
    composers, producers = [], []
    
    # Internal parsing
    for c in contributors:
        rid = str(c.get('ROLE_ID'))
        name = c.get('ART_NAME')
        if not name: continue
        # 16=Composer, 1=Author, 4=Composer, 5=Arranger
        if rid in ['16', '1', '4', '5']: composers.append(name)
        # 2=Producer
        elif rid == '2': producers.append(name)

    # --- 2. EXTERNAL FETCH (PUBLIC API & ITUNES) ---
    itunes_info = {'found': False}
    mb_info = {}
    pub_album_data = {} 
    
    async with aiohttp.ClientSession() as session:
        # A. PUBLIC TRACK (Composer Fallback)
        # Jika internal kosong, tembak Public API Track
        if not composers:
            pub_track = await fetch_deezer_public_track(track_id, session)
            if pub_track.get('contributors'):
                for c in pub_track['contributors']:
                    role = c.get('role', '').lower()
                    name = c.get('name')
                    if not name: continue
                    if role == 'composer': composers.append(name)
                    elif role == 'producer': producers.append(name)

        # B. UPC Extraction (Priority: Internal -> Nested -> Public Album)
        found_upc = get_val('UPC')
        if not found_upc and t_meta_page.get('ALBUM'):
            found_upc = t_meta_page['ALBUM'].get('UPC')
        
        # C. GENRE Preparation
        # Ambil ID Album untuk fetch Public Album jika UPC atau Genre kosong
        alb_id = get_val('ALB_ID')
        if not alb_id and t_meta_page.get('ALBUM'): alb_id = t_meta_page['ALBUM'].get('ALB_ID')

        # D. PUBLIC ALBUM FETCH (Genre & UPC Savior)
        if alb_id and (not found_upc or not album_genre):
            pub_album_data = await fetch_deezer_public_album(alb_id, session)
            if not found_upc:
                found_upc = pub_album_data.get('upc')

        # SET UPC/EAN/BARCODE
        metadata['upc'] = found_upc or ''
        if metadata['upc']:
            metadata['ean'] = metadata['upc']
            metadata['barcode'] = metadata['upc']

        # E. iTunes & MB Lookup
        try:
            itunes_info = await get_extended_itunes_info(metadata, session)
        except: pass
        
        if not itunes_info.get('label') or not itunes_info.get('genre'):
            try:
                mb_info = await get_musicbrainz_info(metadata, session)
            except: pass

    # SET COMPOSER & PRODUCER
    if composers: metadata['composer'] = ', '.join(list(dict.fromkeys(composers)))
    if producers: metadata['producer'] = ', '.join(list(dict.fromkeys(producers)))

    # --- MERGE METADATA ---

    # DATE
    dz_phys = get_val('PHYSICAL_RELEASE_DATE')
    dz_digi = get_val('DIGITAL_RELEASE_DATE')
    final_date = datetime.now().strftime('%Y-%m-%d')
    if dz_phys and dz_phys != '0000-00-00': final_date = dz_phys
    elif itunes_info.get('date'): final_date = itunes_info['date']
    elif mb_info.get('date'): final_date = mb_info['date']
    elif dz_digi and dz_digi != '0000-00-00': final_date = dz_digi

    metadata['date'] = final_date
    metadata['originaldate'] = final_date
    metadata['releasetime'] = final_date
    metadata['release_date'] = final_date
    metadata['recorded_date'] = final_date
    if final_date and len(final_date) >= 4:
        metadata['year'] = final_date[:4]

    # COPYRIGHT
    if itunes_info.get('copyright'):
        metadata['copyright'] = itunes_info['copyright']
    elif mb_info.get('copyright'):
        metadata['copyright'] = mb_info['copyright']
    else:
        metadata['copyright'] = get_val('COPYRIGHT', '')
    metadata['cpr'] = metadata.get('copyright', '')

    # LABEL
    if itunes_info.get('label'):
        metadata['label'] = itunes_info['label']
    elif mb_info.get('label'):
        metadata['label'] = mb_info['label']
    elif get_val('ALB_LABEL') or get_val('LABEL_NAME'):
        metadata['label'] = get_val('ALB_LABEL') or get_val('LABEL_NAME')
    elif metadata.get('copyright'):
        metadata['label'] = extract_label_from_copyright(metadata['copyright'])
    else:
        metadata['label'] = ''
    metadata['publisher'] = metadata['label']
    metadata['pub'] = metadata['label']

    if not metadata.get('copyright') and metadata.get('label'):
        try:
            yr = final_date.split('-')[0]
            metadata['copyright'] = f"© {yr} {metadata['label']}"
            metadata['cpr'] = metadata['copyright']
        except: pass

    # GENRE (ROBUST LOGIC)
    found_genre = ''
    # 1. Argument (Album Level Priority)
    if album_genre: found_genre = album_genre
    # 2. Public API Album (Very Reliable)
    elif pub_album_data and pub_album_data.get('genres') and pub_album_data['genres'].get('data'):
        found_genre = pub_album_data['genres']['data'][0].get('name')
    # 3. Internal Track Data (API)
    elif get_val('GENRE_NAME'): found_genre = get_val('GENRE_NAME')
    # 4. Internal Nested Data (Check Both Keys)
    elif t_meta_page.get('ALBUM'):
        # Check 'genres' (lowercase)
        if t_meta_page['ALBUM'].get('genres') and t_meta_page['ALBUM']['genres'].get('data'):
             found_genre = t_meta_page['ALBUM']['genres']['data'][0].get('name')
        # Check 'GENRES' (uppercase)
        elif t_meta_page['ALBUM'].get('GENRES') and t_meta_page['ALBUM']['GENRES'].get('data'):
             found_genre = t_meta_page['ALBUM']['GENRES']['data'][0].get('name')
    # 5. External (iTunes/MB)
    elif itunes_info.get('genre'): found_genre = itunes_info['genre']
    elif mb_info.get('genre'): found_genre = mb_info['genre']

    metadata['genre'] = found_genre or ''

    # EXPLICIT
    try:
        exp_data = t_meta_page.get('EXPLICIT_TRACK_CONTENT') or t_meta_api.get('EXPLICIT_TRACK_CONTENT') or {}
        status = exp_data.get('EXPLICIT_LYRICS_STATUS', 0)
        metadata['explicit'] = (status == 1)
        metadata['itunesadvisory'] = '1' if status == 1 else '0' 
    except:
        metadata['explicit'] = False
        metadata['itunesadvisory'] = '0'

    # COVER ART
    # --- LOGIKA SUMBER COVER ---
    uid = int(user.get('user_id', 0)) if user else 0
    cover_source = bot_set.user_data.get(uid, {}).get("deezer_cover_source", "itunes") # Default itunes agar perilaku lama tetap jalan
    
    cover_id = get_val('ALB_PICTURE')
    final_cover_url = None

    if cover_source == "itunes":
        final_cover_url = itunes_info.get('cover_url')
    elif cover_source == "musicbrainz":
        async with aiohttp.ClientSession() as session:
            final_cover_url = await get_musicbrainz_cover_url(metadata, session)

    # Fallback ke Original jika API pihak ketiga gagal / disetel ke original
    if not final_cover_url and cover_id:
        final_cover_url = f'https://cdn-images.dzcdn.net/images/cover/{cover_id}/1200x0-none-100-0-0.png'
    if not final_cover_url and os.path.exists(FALLBACK_IMAGE_PATH):
        final_cover_url = FALLBACK_IMAGE_PATH
    # ---------------------------

    metadata['cover'] = await create_cover_file(final_cover_url, metadata)
    metadata['thumbnail'] = await get_cover(cover_id, metadata, True)

    metadata['token'] = t_meta_page.get('TRACK_TOKEN')
    metadata['token_expiry'] = t_meta_page.get('TRACK_TOKEN_EXPIRE')
    metadata['quality'] = await get_quality(t_meta_page, deezerapi, user['user_id'])
    
    return metadata
            

async def process_album_metadata(album_id:int, a_meta:dict, t_meta:list, r_id, user: dict = None):
    if not user: raise DeezerError("User arg required")
    deezerapi = user['deezer_api']

    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    metadata['itemid'] = album_id
    metadata['provider'] = 'Deezer'
    metadata['type'] = 'album'
    
    metadata['albumartist'] = a_meta.get('ART_NAME', '')
    metadata['artist'] = get_artists_name(a_meta) 
    metadata['title'] = a_meta.get('ALB_TITLE', 'Unknown Album')
    metadata['album'] = metadata['title']
    if a_meta.get('VERSION'): metadata['title'] += f' ({a_meta["VERSION"]})'

    # UPC (INTERNAL)
    metadata['upc'] = a_meta.get('UPC', '')

    metadata['totaltracks'] = a_meta.get('NUMBER_TRACK', '0')
    metadata['duration'] = a_meta.get('DURATION', 0)
    
    # --- PERBAIKAN: DETEKSI MULTI-DISC DEEZER SECARA MANUAL ---
    max_vol = 1
    if t_meta and 'data' in t_meta:
        for t in t_meta['data']:
            try:
                v = int(t.get('DISK_NUMBER', 1))
                if v > max_vol: 
                    max_vol = v
            except: 
                pass
    metadata['totalvolume'] = str(max_vol)
    # ----------------------------------------------------------

    # --- Fetch External Info ---
    itunes_info = {'found': False}
    mb_info = {}
    pub_album_data = {}
    
    async with aiohttp.ClientSession() as session:
        # UPC / GENRE FALLBACK (PUBLIC API)
        # Jika UPC internal kosong, atau kita ingin genre yang lebih akurat
        if not metadata['upc'] or not a_meta.get('genres'):
             pub_album_data = await fetch_deezer_public_album(album_id, session)
             
             if not metadata['upc'] and pub_album_data.get('upc'):
                 metadata['upc'] = pub_album_data['upc']

        try:
            itunes_info = await get_extended_itunes_info(metadata, session)
        except: pass
        if not itunes_info.get('label') or not itunes_info.get('genre'):
             try:
                mb_info = await get_musicbrainz_info(metadata, session)
             except: pass

    # SET UPC/BARCODE
    if metadata['upc']:
        metadata['ean'] = metadata['upc']
        metadata['barcode'] = metadata['upc']

    # --- Merge ---
    
    # DATE
    dz_phys = a_meta.get('PHYSICAL_RELEASE_DATE')
    dz_digi = a_meta.get('DIGITAL_RELEASE_DATE')
    final_date = datetime.now().strftime('%Y-%m-%d')
    if dz_phys and dz_phys != '0000-00-00': final_date = dz_phys
    elif itunes_info.get('date'): final_date = itunes_info['date']
    elif mb_info.get('date'): final_date = mb_info['date']
    elif dz_digi and dz_digi != '0000-00-00': final_date = dz_digi
        
    metadata['date'] = final_date
    metadata['originaldate'] = final_date
    metadata['releasetime'] = final_date
    metadata['release_date'] = final_date
    metadata['recorded_date'] = final_date 
    if final_date and len(final_date) >= 4:
        metadata['year'] = final_date[:4]

    # COPYRIGHT
    dz_copyright = a_meta.get('COPYRIGHT', '')
    if itunes_info.get('copyright'):
        metadata['copyright'] = itunes_info['copyright']
    elif dz_copyright:
        metadata['copyright'] = dz_copyright
    elif mb_info.get('copyright'):
        metadata['copyright'] = mb_info['copyright']
    metadata['cpr'] = metadata.get('copyright', '')

    # LABEL
    if itunes_info.get('label'):
        metadata['label'] = itunes_info['label']
    elif mb_info.get('label'):
        metadata['label'] = mb_info['label']
    elif a_meta.get('LABEL_NAME'):
        metadata['label'] = a_meta.get('LABEL_NAME')
    elif metadata.get('copyright'):
        metadata['label'] = extract_label_from_copyright(metadata['copyright'])
    else:
        metadata['label'] = ''
    metadata['publisher'] = metadata['label']
    metadata['pub'] = metadata['label']

    # EXPLICIT
    explicit_status = a_meta.get('explicit_lyrics')
    if explicit_status is None:
        explicit_content = int(a_meta.get('explicit_content_lyrics', 0))
        metadata['explicit'] = True if explicit_content in [1, 4, 6] else False
    else:
        metadata['explicit'] = bool(explicit_status)
    metadata['itunesadvisory'] = '1' if metadata['explicit'] else '0'

    # GENRE
    found_genre = ''
    # 1. Internal API Check (Lowercase & Uppercase)
    if a_meta.get('genres') and a_meta.get('genres').get('data'):
        data = a_meta['genres']['data']
        if len(data) > 0: found_genre = data[0].get('NAME') or data[0].get('name')
    elif a_meta.get('GENRES') and a_meta.get('GENRES').get('data'):
        data = a_meta['GENRES']['data']
        if len(data) > 0: found_genre = data[0].get('NAME') or data[0].get('name')
    
    # 2. Public API Fallback
    if not found_genre and pub_album_data.get('genres') and pub_album_data['genres'].get('data'):
        found_genre = pub_album_data['genres']['data'][0].get('name')

    # 3. iTunes & MB
    if not found_genre:
        if itunes_info.get('genre'): found_genre = itunes_info['genre']
        elif mb_info.get('genre'): found_genre = mb_info['genre']

    metadata['genre'] = found_genre or ''

    # --- LOGIKA SUMBER COVER (ALBUM) ---
    uid = int(user.get('user_id', 0)) if user else 0
    cover_source = bot_set.user_data.get(uid, {}).get("deezer_cover_source", "itunes")
    
    cover_id = a_meta.get('ALB_PICTURE', '')
    final_cover_url = None
    
    if cover_source == "itunes":
        final_cover_url = itunes_info.get('cover_url')
    elif cover_source == "musicbrainz":
        async with aiohttp.ClientSession() as session:
            final_cover_url = await get_musicbrainz_cover_url(metadata, session)

    # Fallback
    if not final_cover_url and cover_id:
        final_cover_url = f'https://cdn-images.dzcdn.net/images/cover/{cover_id}/1200x0-none-100-0-0.png'
    if not final_cover_url and os.path.exists(FALLBACK_IMAGE_PATH):
        final_cover_url = FALLBACK_IMAGE_PATH
    # -----------------------------------

    metadata['cover'] = await create_cover_file(final_cover_url, metadata)
    metadata['thumbnail'] = await get_cover(cover_id, metadata, True)
        
    metadata['tracks'] = []
    for track in t_meta['data']:
        try:
            track_meta = await process_track_metadata(
                track['SNG_ID'], r_id, metadata['cover'], metadata['thumbnail'],
                metadata['totaltracks'], metadata['genre'], metadata['totalvolume'], user=user
            )
            
            # FORCE SYNC TRACK DATA
            track_meta['date'] = metadata['date']
            track_meta['originaldate'] = metadata['date']
            track_meta['releasetime'] = metadata['date']
            track_meta['release_date'] = metadata['date']
            track_meta['recorded_date'] = metadata['date']
            track_meta['year'] = metadata['year']
            
            # Sync Copyright/Label if missing
            if metadata.get('copyright'):
                track_meta['copyright'] = metadata['copyright']
                track_meta['cpr'] = metadata['cpr']
            if metadata.get('label'):
                track_meta['label'] = metadata['label']
                track_meta['publisher'] = metadata['publisher']
                track_meta['pub'] = metadata['pub']
            
            # Sync Genre
            if not track_meta.get('genre') and metadata.get('genre'):
                track_meta['genre'] = metadata['genre']
            
            # Sync UPC (Important!)
            if not track_meta.get('upc') and metadata.get('upc'):
                track_meta['upc'] = metadata['upc']
                track_meta['ean'] = metadata['upc']
                track_meta['barcode'] = metadata['upc']

            metadata['tracks'].append(track_meta)
        except: continue

    if not metadata['tracks']: raise DeezerError(f"No tracks found for album {metadata['title']}")
    metadata['quality'] = metadata['tracks'][0]['quality']
    return metadata

async def process_artist_metadata(artist_data: dict, r_id: str):
    """Memproses metadata profil artis Deezer."""
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    metadata['itemid'] = artist_data.get('ART_ID')
    metadata['provider'] = 'Deezer'
    metadata['type'] = 'artist'
    
    # Deezer menyimpan nama artis di parameter ART_NAME
    metadata['artist'] = artist_data.get('ART_NAME', 'Unknown Artist')
    metadata['title'] = metadata['artist']
    
    # Ekstraksi dan resolusi gambar profil artis
    cover_id = artist_data.get('ART_PICTURE')
    final_cover_url = None
    if cover_id:
        final_cover_url = f'https://cdn-images.dzcdn.net/images/artist/{cover_id}/1200x0-none-100-0-0.png'
        
    metadata['cover'] = await create_cover_file(final_cover_url, metadata)
    
    return metadata

# --- Helper Functions (Standard) ---
async def process_playlist_meta(raw_meta, r_id, user: dict = None):
    if not user: raise DeezerError("User arg required")
    deezerapi = user['deezer_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['title'] = raw_meta['DATA']['TITLE']
    metadata['duration'] = raw_meta['DATA']['DURATION']
    metadata['totaltracks'] = raw_meta['DATA']['NB_SONG'] 
    metadata['itemid'] = raw_meta['DATA']['PLAYLIST_ID']
    metadata['type'] = 'playlist'
    metadata['provider'] = 'Deezer'
    metadata['cover'] = await get_cover(raw_meta['DATA']['PLAYLIST_PICTURE'], metadata)
    metadata['thumbnail'] = await get_cover(raw_meta['DATA']['PLAYLIST_PICTURE'], metadata, True)
    if raw_meta['DATA'].get('CREATOR') and raw_meta['DATA']['CREATOR'].get('NAME'):
        metadata['artist'] = raw_meta['DATA']['CREATOR']['NAME']
    for track in raw_meta['SONGS']['data']:
        try:
            track_meta = await process_track_metadata(
                track['SNG_ID'], r_id, total_tracks=metadata['totaltracks'], user=user 
            )
            metadata['tracks'].append(track_meta)
        except: continue
    if metadata['tracks']: metadata['quality'] = metadata['tracks'][0]['quality']
    else: metadata['quality'] = "N/A"
    return metadata

def get_artists_name(meta:dict):
    artists = []
    if meta.get('ARTISTS'):
        for a in meta['ARTISTS']: artists.append(a['ART_NAME'])
    elif meta.get('ART_NAME'): artists.append(meta.get('ART_NAME'))
    return ', '.join([str(artist) for artist in artists if artist])

async def get_cover(cover_id, meta:dict, thumbnail=False):
    url = None
    if cover_id:
        url = (f'https://cdn-images.dzcdn.net/images/cover/{cover_id}/1200x0-none-100-0-0.png' 
               if not thumbnail else 
               f'https://cdn-images.dzcdn.net/images/cover/{cover_id}/80x0-none-100-0-0.png')
    return await create_cover_file(url, meta, thumbnail)

async def get_quality(meta:dict, deezerapi: DeezerAPI, user_id: int):
    countries = meta.get('AVAILABLE_COUNTRIES', {}).get('STREAM_ADS')
    if not countries or deezerapi.country not in countries:
        raise DeezerError("Deezer : Track not available in your country")
    preferred_quality = deezer_manager.get_user_quality(user_id)
    formats = ['FLAC', 'MP3_320', 'MP3_128'] if preferred_quality == "FLAC" else \
              ['MP3_320', 'MP3_128'] if preferred_quality == "MP3_320" else ['MP3_128']
    for f in formats:
        if f in deezerapi.available_formats and meta.get(f'FILESIZE_{f}', '0') != '0': return f
    if 'MP3_128' in deezerapi.available_formats and meta.get('FILESIZE_MP3_128', '0') != '0': return 'MP3_128'
    raise DeezerError(f"Deezer: Format {preferred_quality} not available.")
