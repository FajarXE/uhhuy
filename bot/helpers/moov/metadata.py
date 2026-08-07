# [GANTI FILE: bot/helpers/moov/metadata.py]

import copy
import re
import datetime
import aiohttp
from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from bot.logger import LOGGER

# --- CONFIG ---
IGNORED_KEYS_META = {
    'modules', 'images', 'related', 'products', 'tracks', 
    'artists', 'composers', 'lyric', 'mv', 'concerts'
}

IGNORED_KEYS_PRODUCTS = {
    'related', 'recommend', 'recommendation', 'concerts', 'articles', 'mv', 'images', 'uimodule'
}

def is_explicit_strict(data):
    val_exp = str(data.get('explicit', '')).lower()
    if val_exp in ['true', '1', 'yes', 'explicit']: return True
    val_pw = str(data.get('parentalWarning', '')).lower()
    if val_pw in ['true', '1', 'yes', 'explicit']: return True
    return False

def get_moov_cover(url):
    if not url: return None
    clean_url = url.split("?")[0]
    clean_url = re.sub(r'\/resize\/\d+x\d+', '', clean_url)
    clean_url = re.sub(r'_(\d{2,4}x\d{2,4})', '', clean_url)
    clean_url = clean_url.replace('//', '/').replace('https:/', 'https://').replace('http:/', 'http://')
    return clean_url

def parse_date(date_val):
    if not date_val: return None
    s = str(date_val).strip()
    if s.lower() == 'none' or s == "": return None
    if 'T' in s: return s.split('T')[0]
    if len(s) == 8 and s.isdigit(): return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s): return s
    return None

def get_val_safe(data, keys):
    if not data or not isinstance(data, dict): return None
    for k in keys:
        if data.get(k): return data.get(k)
    return None

def find_key_optimized(data, target_keys, depth=0, max_depth=3):
    if depth > max_depth: return None
    if not isinstance(target_keys, list): target_keys = [target_keys]
    target_keys = [k.lower() for k in target_keys]
    
    if isinstance(data, dict):
        for k, v in data.items():
            if k.lower() in target_keys and v:
                return v
        
        for k, v in data.items():
            if k.lower() in IGNORED_KEYS_META: continue 
            if isinstance(v, (dict, list)):
                found = find_key_optimized(v, target_keys, depth + 1, max_depth)
                if found: return found

    elif isinstance(data, list):
        limit = 50 if depth == 0 else 10
        for i, item in enumerate(data):
            if i >= limit: break
            found = find_key_optimized(item, target_keys, depth + 1, max_depth)
            if found: return found
            
    return None

def find_products_recursive(data, results=None):
    if results is None: results = []
    
    if isinstance(data, dict):
        pid = data.get('productId') or data.get('contentId') or data.get('mtgContentId')
        title = data.get('productTitle') or data.get('title') or data.get('trackTitle')
        
        if pid and title:
            if not any(str(x.get('productId', '')) == str(pid) for x in results):
                data['productId'] = pid
                data['productTitle'] = title
                results.append(data)
            return

        for key, value in data.items():
            if key.lower() in IGNORED_KEYS_PRODUCTS: continue 
            if isinstance(value, (dict, list)): find_products_recursive(value, results)
            
    elif isinstance(data, list):
        for item in data: find_products_recursive(item, results)
        
    return results

async def process_track_metadata(track_data: dict, r_id, user: dict, cover=None, album_meta=None):
    from .manager import moov_manager

    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    metadata['itemid'] = track_data.get('productId')
    metadata['title'] = track_data.get('productTitle')

    # --- 1. DATE ---
    final_date = None
    date_keys = ['publishDate', 'releaseDate', 'originalReleaseDate', 'createdOn']
    final_date = get_val_safe(track_data, date_keys)
    
    if not final_date and track_data.get('album'):
        final_date = get_val_safe(track_data['album'], date_keys)
    
    if final_date:
        final_date = parse_date(final_date)
        metadata['date'] = final_date
        metadata['year'] = final_date[:4] if final_date else ""
    elif album_meta and album_meta.get('year'):
        metadata['date'] = album_meta.get('date')
        metadata['year'] = album_meta.get('year')
    else:
        metadata['year'] = str(datetime.datetime.now().year)

    # --- 2. ISRC ---
    isrc = track_data.get('isrc')
    if not isrc: isrc = find_key_optimized(track_data, ['isrc'])
    metadata['isrc'] = str(isrc) if isrc else ""

    # --- 3. ALBUM ID ---
    if track_data.get('albumId'):
        metadata['moov_album_id'] = track_data.get('albumId')
    elif isinstance(track_data.get('album'), dict):
        metadata['moov_album_id'] = track_data.get('album').get('id')
    
    if not metadata.get('moov_album_id') and album_meta:
        metadata['moov_album_id'] = album_meta.get('itemid')
    
    # --- 4. ARTIST ---
    artists_raw = track_data.get('artists', [])
    if not artists_raw and 'artist' in track_data:
        val = track_data['artist']
        artists_raw = [{'name': val, 'role': 'Main'}] if isinstance(val, str) else [val]

    main_artists, producers = [], []
    if isinstance(artists_raw, list):
        for a in artists_raw:
            if isinstance(a, dict):
                name = a.get('name')
                role = a.get('role', 'Main')
                if role in ['Main', 'Featured']: main_artists.append(name)
                if role in ['Producer', 'Arranger', 'Composer']: producers.append(name)
            elif isinstance(a, str): main_artists.append(a)
    
    metadata['artist'] = ", ".join(main_artists)
    metadata['producer'] = ", ".join(producers) 
    
    # --- 5. LABEL ---
    keys_label = ['recordLabel', 'albumLabel', 'label', 'company']
    label_val = get_val_safe(track_data, keys_label)
    if not label_val and track_data.get('album'):
        label_val = get_val_safe(track_data['album'], keys_label)
    if not label_val and album_meta:
        label_val = album_meta.get('label') 
    metadata['label'] = str(label_val) if label_val else ""

    # --- 6. COPYRIGHT ---
    raw_cpr = get_val_safe(track_data, ['cnote', 'copyright'])
    if not raw_cpr:
        raw_cpr = get_val_safe(track_data, ['company', 'recordCompany', 'publishingCompany'])
    if not raw_cpr and track_data.get('album'):
        raw_cpr = get_val_safe(track_data['album'], ['company', 'recordCompany'])
    if not raw_cpr: raw_cpr = metadata['label']
    
    final_cpr = str(raw_cpr) if raw_cpr else ""
    if final_cpr:
        has_symbol = re.search(r'[\u00A9\u24B8]|\(c\)', final_cpr, re.IGNORECASE)
        has_year = re.search(r'\b20\d{2}\b', final_cpr)
        year_str = metadata.get('year', '')
        
        if not has_symbol:
            if year_str and not has_year: final_cpr = f"© {year_str} {final_cpr}"
            else: final_cpr = f"© {final_cpr}"
        final_cpr = re.sub(r'\s+', ' ', final_cpr).strip()

    metadata['copyright'] = final_cpr

    # --- 7. GENRE (NEW) ---
    # Coba ambil genre dari track itu sendiri
    genres = track_data.get('genres', [])
    if genres:
        metadata['genre'] = ", ".join([g.get('name') for g in genres])
    else:
        # Fallback ke key lain di track
        metadata['genre'] = get_val_safe(track_data, ['genre', 'category', 'style']) or ""

    # Fallback ke Album Genre jika track kosong
    if not metadata['genre'] and album_meta:
        metadata['genre'] = album_meta.get('genre', '')

    # --- 8. TRACK NUMBERS ---
    metadata['disk'] = str(track_data.get('discNo', 1))
    try:
        tn = int(track_data.get('trackNo', 1))
        metadata['tracknumber'] = f"{tn:02d}"
    except:
        metadata['tracknumber'] = str(track_data.get('trackNo', 1))

    # --- 9. OTHER META ---
    metadata['album'] = track_data.get('albumTitle') or (album_meta.get('title') if album_meta else "")
    metadata['albumartist'] = metadata['artist'] 
    if album_meta and album_meta.get('artist'):
         metadata['albumartist'] = album_meta.get('artist')

    comp_list = []
    if 'composers' in track_data:
        for c in track_data.get('composers', []):
            if isinstance(c, dict): comp_list.append(c.get('name'))
    if not comp_list and track_data.get('author'): comp_list.append(track_data.get('author'))
    metadata['composer'] = ", ".join(comp_list)

    is_track_explicit = is_explicit_strict(track_data)
    metadata['explicit'] = "True" if is_track_explicit else "False"

    # Context Injection
    if album_meta:
        metadata['upc'] = album_meta.get('upc', '')
        metadata['ean'] = album_meta.get('ean', '')
        metadata['barcode'] = album_meta.get('barcode', '')
        if album_meta.get('totaltracks'): metadata['totaltracks'] = album_meta.get('totaltracks')
        if album_meta.get('totalvolumes'): metadata['totalvolumes'] = album_meta.get('totalvolumes')
    else:
        metadata['totaltracks'] = '1'
        metadata['totalvolumes'] = '1'

    metadata['provider'] = 'Moov'
    metadata['type'] = 'track'
    
    if cover:
        metadata['cover'] = cover
        metadata['cover_url'] = None 
    elif not metadata.get('cover_url'):
        keys_img = ['largeImage', 'thumbnail', 'path']
        found_url = get_val_safe(track_data, keys_img)
        if not found_url and track_data.get('images') and isinstance(track_data['images'], list):
             found_url = get_val_safe(track_data['images'][0], keys_img)
        if found_url: metadata['cover_url'] = get_moov_cover(found_url)

    avail_qualities = track_data.get('qualities', [])
    user_pref = moov_manager.get_user_quality(user['user_id']) 
    target_quality = 'LL' 
    if user_pref == "FLAC": 
        if 'HR' in avail_qualities:
            target_quality = 'HR'
            metadata['quality'] = 'FLAC 24bit'
        elif 'LL' in avail_qualities:
            target_quality = 'LL'
            metadata['quality'] = 'FLAC 16bit'
    else: 
        if 'LL' in avail_qualities:
            target_quality = 'LL'
            metadata['quality'] = 'FLAC 16bit'
            
    metadata['extension'] = 'flac'
    metadata['moov_quality_code'] = target_quality
    
    return metadata

async def process_album_metadata(album_data: dict, r_id, user: dict):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    titles = album_data.get('engTitle', [])
    if not titles: titles = album_data.get('title', [])
    metadata['title'] = titles[0] if titles else "Unknown Album"
    metadata['album'] = metadata['title']
    
    artists = album_data.get('artists', [])
    metadata['artist'] = ", ".join([a.get('name') for a in artists])
    metadata['albumartist'] = metadata['artist']
    metadata['provider'] = 'Moov'
    metadata['type'] = 'album'
    metadata['itemid'] = album_data.get('profileId') 

    metadata['upc'] = get_val_safe(album_data, ['upc', 'ean', 'barcode'])
    if not metadata['upc']: metadata['upc'] = find_key_optimized(album_data, ['upc', 'ean', 'barcode']) or ""
    metadata['ean'] = metadata['upc']
    metadata['barcode'] = metadata['upc']

    is_album_explicit = is_explicit_strict(album_data)
    
    final_date = None
    date_keys = ['publishDate', 'releaseDate', 'originalReleaseDate']
    final_date = get_val_safe(album_data, date_keys)
    if final_date:
        final_date = parse_date(final_date)
        metadata['date'] = final_date
        metadata['year'] = final_date[:4] if final_date else ""
    else:
        if len(titles) > 2:
            try: 
                metadata['year'] = titles[2].split('-')[0]
                metadata['date'] = titles[2]
            except: pass

    genres = album_data.get('genres', [])
    if genres: metadata['genre'] = ", ".join([g.get('name') for g in genres])
    else: metadata['genre'] = album_data.get('category', "")
    
    metadata['label'] = get_val_safe(album_data, ['recordLabel', 'albumLabel']) or ""

    moov_cover_url = None
    images = album_data.get('images', [])
    if images:
        raw_path = images[0].get('path')
        moov_cover_url = get_moov_cover(raw_path)

    metadata['cover_url'] = moov_cover_url
    if metadata.get('cover_url'):
        metadata['cover'] = await create_cover_file(metadata['cover_url'], metadata)
    
    metadata['tracks'] = []
    
    raw_products = find_products_recursive(album_data)
    metadata['totaltracks'] = str(len(raw_products))
    
    max_disc = 1
    for p in raw_products:
        try:
            d = int(p.get('discNo', 1))
            if d > max_disc: max_disc = d
        except: pass
    metadata['totalvolumes'] = str(max_disc)

    for idx, track_raw in enumerate(raw_products, 1):
        track_raw['trackNo'] = idx 
        if not is_album_explicit:
            if is_explicit_strict(track_raw): is_album_explicit = True
        
        t_meta = await process_track_metadata(track_raw, r_id, user, cover=metadata['cover'], album_meta=metadata)
        metadata['tracks'].append(t_meta)
    
    metadata['explicit'] = "True" if is_album_explicit else "False"
    if metadata['tracks']: metadata['quality'] = metadata['tracks'][0]['quality']
        
    return metadata

async def process_playlist_metadata(pl_data: dict, r_id, user: dict):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    titles = pl_data.get('engTitle', [])
    if not titles: titles = pl_data.get('title', []) 
    metadata['title'] = titles[0] if titles else "Unknown Playlist"
    metadata['album'] = metadata['title']
    metadata['provider'] = 'Moov'
    metadata['type'] = 'playlist'
    metadata['itemid'] = pl_data.get('profileId')
    metadata['artist'] = "Moov Playlist"
    metadata['albumartist'] = "Various Artists"

    images = pl_data.get('images', [])
    if images:
        raw_path = images[0].get('path')
        metadata['cover_url'] = get_moov_cover(raw_path)
        metadata['cover'] = await create_cover_file(metadata['cover_url'], metadata)

    metadata['tracks'] = []
    raw_tracks = find_products_recursive(pl_data)
    LOGGER.info(f"Moov Playlist/Chart: Ditemukan {len(raw_tracks)} lagu.")

    metadata['totalvolumes'] = "1"
    metadata['totaltracks'] = str(len(raw_tracks))

    for idx, track_raw in enumerate(raw_tracks, 1):
        track_raw['trackNo'] = idx
        track_raw['discNo'] = 1
        
        t_meta = await process_track_metadata(track_raw, r_id, user, cover=None, album_meta=None)
        metadata['tracks'].append(t_meta)

    if metadata['tracks']: metadata['quality'] = metadata['tracks'][0]['quality']
    return metadata
