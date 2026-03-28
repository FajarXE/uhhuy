# [GANTI FILE: bot/helpers/tidal/metadata.py]

import copy
import re
import aiohttp
import asyncio
import urllib.parse
from datetime import datetime
from bot.settings import bot_set

# --- Impor LOGGER ---
from bot.logger import LOGGER

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file

# --- FUNGSI BANTUAN API PIHAK KETIGA ---

async def get_deezer_genre_by_upc(upc):
    """
    Mendapatkan Genre dari Deezer menggunakan kode UPC (Barcode).
    Metode ini paling akurat karena menggunakan ID numerik, bukan pencarian teks.
    """
    if not upc:
        return None
    
    # API Publik Deezer untuk lookup via UPC
    url = f"https://api.deezer.com/album/upc:{upc}"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    
                    # Cek apakah ada error (UPC tidak ditemukan di Deezer)
                    if 'error' in data:
                        return None
                        
                    # Ambil Genre
                    if 'genres' in data and data['genres']['data']:
                        # Mengambil genre pertama (biasanya main genre)
                        return data['genres']['data'][0]['name']
        except Exception as e:
            LOGGER.warning(f"Deezer UPC lookup failed: {e}")
    return None

async def get_itunes_info(artist, title, album, use_album_search=False):
    """
    Mencari metadata tambahan dari iTunes Store dengan strategi pencarian bertingkat.
    """
    # 1. Bersihkan Judul (Hapus feat, prod, explicit, kurung)
    clean_title = re.sub(r'(?i)\s*[\(\[]\s*(feat|ft|with|prod|explicit|clean|dirty).*?[\)\]]', '', title)
    clean_title = re.sub(r'\s*\(.*?\)', '', clean_title).strip()
    
    # 2. Tentukan Artis Utama (Primary Artist) untuk menghindari isu "Artist A, Artist B"
    primary_artist = artist.split(',')[0].split('&')[0].strip()

    # 3. Siapkan Variasi Pencarian
    search_terms = []
    
    # Prioritas 1: Primary Artist + Clean Title
    search_terms.append(f"{primary_artist} {clean_title}")
    
    # Prioritas 2: Primary Artist + Original Title (Jika judul asli unik)
    if title != clean_title:
        search_terms.append(f"{primary_artist} {title}")
    
    # Header wajib agar tidak diblokir Apple
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    
    entity = "album" if use_album_search else "song"
    
    async with aiohttp.ClientSession() as session:
        for term in search_terms:
            encoded_term = urllib.parse.quote(term)
            url = f"https://itunes.apple.com/search?term={encoded_term}&entity={entity}&limit=1"
            
            try:
                async with session.get(url, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None) 
                        if data['resultCount'] > 0:
                            return data['results'][0]
            except Exception as e:
                LOGGER.warning(f"iTunes lookup error ({term}): {e}")
                
    return None

async def get_musicbrainz_info(isrc):
    """Mencari metadata tambahan dari MusicBrainz."""
    if not isrc:
        return None
    
    url = f"https://musicbrainz.org/ws/2/recording?query=isrc:{isrc}&fmt=json&inc=tags+releases"
    headers = {"User-Agent": "TidalBot/1.0 ( your_email@example.com )"}
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if data.get('recordings'):
                        recording = data['recordings'][0]
                        info = {}
                        
                        if recording.get('releases'):
                            dates = []
                            for rel in recording['releases']:
                                if rel.get('date'): dates.append(rel['date'])
                            if dates:
                                dates.sort()
                                info['date'] = dates[0]
                        
                        tags = recording.get('tags', [])
                        if tags:
                            sorted_tags = sorted(tags, key=lambda x: x.get('count', 0), reverse=True)
                            genre_list = [t['name'].title() for t in sorted_tags[:2]]
                            info['genre'] = ', '.join(genre_list)
                            
                        return info
        except Exception as e:
            LOGGER.warning(f"MusicBrainz lookup failed: {e}")
    return None

# --- FUNGSI PARSING GENRE ---
def parse_genre_field(data):
    """
    Mengekstrak nama genre dari berbagai format (string, dict, atau list).
    """
    if not data:
        return None

    if isinstance(data, dict):
        return data.get('name')
    
    if isinstance(data, list):
        names = []
        for item in data:
            if isinstance(item, dict):
                if item.get('name'): names.append(item['name'])
            else:
                names.append(str(item))
        return ', '.join(names) if names else None

    return str(data)

# --- FUNGSI UTAMA ---
async def get_track_metadata(track_id, t_meta, r_id, cover=None, thumbnail=False, client=None, user_id=0):
    """
    Mengambil metadata track. 
    """
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['itemid'] = track_id
    
    # --- 1. DATA DASAR TIDAL ---
    metadata['title'] = t_meta['title']
    if t_meta.get('version'):
        metadata['title'] += f' ({t_meta["version"]})'
    metadata['title'] = metadata['title'].replace('/', ' ')
    
    metadata['albumartist'] = t_meta.get('artist', {}).get('name', 'Various Artists')
    metadata['artist'] = get_artists_name(t_meta)
    metadata['album'] = t_meta.get('album', {}).get('title', 'Unknown Album')
    metadata['isrc'] = t_meta.get('isrc')
    metadata['duration'] = t_meta.get('duration', 0)
    metadata['explicit'] = t_meta.get('explicit', False)
    
    raw_track_number = t_meta.get('trackNumber', 1)
    metadata['tracknumber'] = str(raw_track_number).zfill(2)
    
    metadata['volume'] = t_meta.get('volumeNumber', 1)
    metadata['copyright'] = t_meta.get('copyright') or ''
    
    # --- PUBLISHER ---
    if metadata['copyright']:
        clean_pub = re.sub(r'^(\(?[cpCP]\)?|©|℗)?\s*\d{4}\s*', '', metadata['copyright'])
        metadata['publisher'] = clean_pub.strip(" -.,")
    else:
        metadata['publisher'] = ''
    
    if t_meta.get('album'):
        metadata['upc'] = t_meta['album'].get('upc', '')
        metadata['totalvolume'] = t_meta['album'].get('numberOfVolumes', 1)
        metadata['totaltracks'] = t_meta['album'].get('numberOfTracks', 1)
    else:
        metadata['upc'] = ''
        metadata['totalvolume'] = 1
        metadata['totaltracks'] = 1

    # --- 2. SIAPKAN GENRE DARI TRACK (TIDAL INTERNAL) ---
    tidal_track_genre = parse_genre_field(t_meta.get('genre'))
    if not tidal_track_genre:
         tidal_track_genre = parse_genre_field(t_meta.get('genres'))

    # --- 3. ENRICHMENT VIA TIDAL CLIENT ---
    tidal_album_date = None
    tidal_album_genre = None
    tidal_artist_genre = None

    if client:
        try:
            # A. Info Album
            album_id = t_meta.get('album', {}).get('id')
            if album_id:
                full_album = await client.get_album(album_id)
                if full_album.get('releaseDate'): tidal_album_date = full_album['releaseDate']
                
                tidal_album_genre = parse_genre_field(full_album.get('genre'))
                if not tidal_album_genre: tidal_album_genre = parse_genre_field(full_album.get('genres'))
                
                if full_album.get('upc'): metadata['upc'] = full_album['upc']
                if full_album.get('numberOfTracks'): metadata['totaltracks'] = full_album['numberOfTracks']
                if full_album.get('numberOfVolumes'): metadata['totalvolume'] = full_album['numberOfVolumes']

            # B. Info Artist
            if not tidal_album_genre and not tidal_track_genre:
                artist_id = t_meta.get('artist', {}).get('id')
                if artist_id:
                    try:
                        artist_data = await client.get_artist(artist_id)
                        tidal_artist_genre = parse_genre_field(artist_data.get('genre'))
                        if not tidal_artist_genre:
                             tidal_artist_genre = parse_genre_field(artist_data.get('genres'))
                    except Exception: pass

            # C. Composer
            credits_data = await client.get_track_contributors(track_id)
            composers = []
            if 'items' in credits_data:
                for item in credits_data['items']:
                    role = item.get('role', '').lower()
                    name = item.get('name', '')
                    if 'composer' in role: composers.append(name)
            
            if composers: metadata['composer'] = ', '.join(composers)

        except Exception as e:
            LOGGER.warning(f"Tidal Client Enrichment Failed: {e}")

    # --- 4. EXTERNAL LOOKUP (Deezer UPC > iTunes > MusicBrainz) ---
    deezer_genre = None
    itunes_data = None
    mb_data = None

    # HANYA cari eksternal jika Tidal internal kosong
    if not tidal_album_genre and not tidal_track_genre and not tidal_artist_genre:
        
        # A. Coba DEEZER UPC Lookup (Metode Baru - Sangat Akurat)
        # Kita gunakan UPC dari Album Tidal
        if metadata.get('upc'):
            try:
                deezer_genre = await get_deezer_genre_by_upc(metadata['upc'])
            except Exception: pass
        
        # B. Coba iTunes (Text Search) - Hanya jika Deezer gagal
        if not deezer_genre:
            try:
                itunes_data = await get_itunes_info(metadata['artist'], metadata['title'], metadata['album'])
                if not itunes_data:
                    itunes_data = await get_itunes_info(metadata['artist'], metadata['title'], metadata['album'], use_album_search=True)
            except Exception: pass

        # C. Coba MusicBrainz
        if not deezer_genre and not itunes_data:
            try:
                mb_data = await get_musicbrainz_info(metadata['isrc'])
            except Exception: pass

    # --- 5. MERGING GENRE (PRIORITAS FINAL) ---
    final_genre = None
    
    # 1. Tidal Album (Data Asli)
    if tidal_album_genre: final_genre = tidal_album_genre
    # 2. Tidal Track
    elif tidal_track_genre: final_genre = tidal_track_genre
    # 3. Deezer UPC (Sangat Akurat untuk Rap/Hip-Hop Global)
    elif deezer_genre: final_genre = deezer_genre
    # 4. Tidal Artist
    elif tidal_artist_genre: final_genre = tidal_artist_genre
    # 5. iTunes
    elif itunes_data and itunes_data.get('primaryGenreName'): final_genre = itunes_data['primaryGenreName']
    # 6. MusicBrainz
    elif mb_data and mb_data.get('genre'): final_genre = mb_data['genre']
    
    if final_genre: 
        metadata['genre'] = final_genre

    # --- 6. MERGING DATES ---
    final_date = None
    if tidal_album_date: final_date = tidal_album_date
    if not final_date and t_meta.get('album') and t_meta['album'].get('releaseDate'): final_date = t_meta['album']['releaseDate']
    if not final_date and t_meta.get('streamStartDate'): final_date = t_meta['streamStartDate'][:10]

    if not final_date:
        if itunes_data and itunes_data.get('releaseDate'): final_date = itunes_data['releaseDate'][:10]
        elif mb_data and mb_data.get('date'): final_date = mb_data['date']

    if final_date:
        metadata['release_date'] = final_date
        metadata['date'] = final_date[:4]
    else:
        metadata['release_date'] = ''
        metadata['date'] = ''

    # Cover Art
    metadata['cover'] = cover if cover else await get_cover(t_meta.get('album', {}).get('cover'), metadata, False, user_id)
    metadata['thumbnail'] = thumbnail if thumbnail else await get_cover(t_meta.get('album', {}).get('cover'), metadata, True, user_id)

    if not metadata.get('composer') and t_meta.get('composers'):
        metadata['composer'] = ', '.join([c.get('name', '') for c in t_meta['composers']])

    return metadata


async def get_album_metadata(album_id, a_meta, t_meta, r_id, user_id=0):
    """
    Mengambil metadata album.
    """
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['itemid'] = album_id
    metadata['albumartist'] = a_meta['artist']['name']
    metadata['upc'] = a_meta.get('upc')
    metadata['title'] = a_meta['title']
    if a_meta.get('version'):
        metadata['title'] += f' ({a_meta["version"]})'
    metadata['album'] = a_meta['title']
    metadata['artist'] = get_artists_name(a_meta)
    
    if a_meta.get('releaseDate'):
        metadata['release_date'] = a_meta['releaseDate'] 
        metadata['date'] = a_meta['releaseDate'].split('-')[0] 
    else:
         metadata['release_date'] = ''
         metadata['date'] = ''
    
    metadata['totaltracks'] = a_meta['numberOfTracks']
    metadata['duration'] = a_meta['duration']
    
    raw_copyright = a_meta.get('copyright') or ''
    metadata['copyright'] = raw_copyright
    
    if raw_copyright:
        clean_pub = re.sub(r'^(\(?[cpCP]\)?|©|℗)?\s*\d{4}\s*', '', raw_copyright)
        metadata['publisher'] = clean_pub.strip(" -.,")
    else:
        metadata['publisher'] = ''

    metadata['explicit'] = a_meta.get('explicit')
    metadata['totalvolume'] = a_meta.get('numberOfVolumes')
    metadata['provider'] = 'Tidal'
    metadata['type'] = 'album'
    
    # --- PARSING GENRE + DEEZER UPC FALLBACK ---
    album_genre = parse_genre_field(a_meta.get('genre'))
    if not album_genre:
        album_genre = parse_genre_field(a_meta.get('genres'))
    
    # Fallback ke Deezer UPC jika Tidal kosong
    if not album_genre and metadata.get('upc'):
        try:
            album_genre = await get_deezer_genre_by_upc(metadata['upc'])
        except Exception: pass
    
    # Fallback ke iTunes jika Deezer juga kosong
    if not album_genre:
        try:
            itunes_data = await get_itunes_info(metadata['artist'], metadata['title'], metadata['album'], use_album_search=True)
            if itunes_data and itunes_data.get('primaryGenreName'):
                album_genre = itunes_data['primaryGenreName']
        except Exception: pass
            
    if album_genre:
        metadata['genre'] = album_genre
    # -------------------------------------------

    metadata['cover'] = await get_cover(a_meta.get('cover'), metadata, False, user_id)
    metadata['thumbnail'] = await get_cover(a_meta.get('cover'), metadata, True, user_id)

    metadata['tracks'] = []
    for track in t_meta['items']:
        raw_tn = track.get('trackNumber', 1)
        str_tn = str(raw_tn).zfill(2)

        stub_meta = {
            'itemid': track['id'],
            'albumartist': metadata['albumartist'],
            'album': metadata['album'],
            'cover': metadata['cover'], 
            'thumbnail': metadata['thumbnail'], 
            'provider': 'Tidal',
            'title': track['title'].replace('/', ' ') if track.get('title') else 'Unknown Title',
            'artist': get_artists_name(track),
            'tracknumber': str_tn, 
            'upc': metadata['upc']
        }
        metadata['tracks'].append(stub_meta)
    
    return metadata


async def get_playlist_metadata(playlist_id, p_meta, t_meta, r_id, user_id=0):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['itemid'] = playlist_id
    metadata['albumartist'] = p_meta.get('creator', {}).get('name', 'Various Artists')
    metadata['artist'] = 'Various Artists'
    metadata['title'] = p_meta['title']
    metadata['album'] = p_meta['title'] 
    metadata['upc'] = p_meta.get('uuid') 

    try:
        parsed_date = datetime.strptime(p_meta['created'], '%Y-%m-%dT%H:%M:%S.%f%z')
        metadata['release_date'] = str(parsed_date.date())
        metadata['date'] = str(parsed_date.year)
    except (ValueError, KeyError):
         metadata['release_date'] = ''
         metadata['date'] = ''

    metadata['totaltracks'] = p_meta['numberOfTracks']
    metadata['duration'] = p_meta['duration']
    metadata['explicit'] = p_meta.get('explicit', False)
    metadata['provider'] = 'Tidal'
    metadata['type'] = 'playlist' 

    metadata['cover'] = await get_cover(p_meta.get('image'), metadata, False, user_id)
    metadata['thumbnail'] = await get_cover(p_meta.get('image'), metadata, True, user_id)

    metadata['tracks'] = []
    for item in t_meta['items']:
        if item.get('type') == 'track' and item.get('item'):
            track = item['item']
            raw_tn = track.get('trackNumber', 1)
            str_tn = str(raw_tn).zfill(2)

            stub_meta = {
                'itemid': track['id'],
                'albumartist': track.get('artist', {}).get('name', 'Various Artists'),
                'album': track.get('album', {}).get('title', 'Unknown Album'),
                'cover': None, 
                'thumbnail': None,
                'provider': 'Tidal',
                'title': track['title'].replace('/', ' ') if track.get('title') else 'Unknown Title',
                'artist': get_artists_name(track),
                'tracknumber': str_tn 
            }
            metadata['tracks'].append(stub_meta)
    
    metadata['totaltracks'] = len(metadata['tracks'])
    return metadata


async def get_artist_metadata(a_meta:dict, r_id, user_id=0):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['artist'] = a_meta['name']
    metadata['title'] = a_meta['name']
    metadata['provider'] = 'Tidal'
    metadata['type'] = 'artist'
    metadata['cover'] = await get_cover(a_meta.get('picture'), metadata, False, user_id)
    metadata['thumbnail'] = await get_cover(a_meta.get('picture'), metadata, True, user_id)
    return metadata


async def get_itunes_cover_url(metadata: dict, session: aiohttp.ClientSession) -> str | None:
    try:
        upc = metadata.get('upc')
        # Pastikan UPC ada dan valid
        if upc and upc != "0":
            url = f"https://itunes.apple.com/lookup?upc={upc}"
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Jika barcode cocok, ambil covernya
                    if data['resultCount'] > 0:
                        artwork_url = data['results'][0]['artworkUrl100']
                        return artwork_url.replace('100x100bb', '10000x10000bb')
    except Exception as e:
        pass
    return None

async def get_musicbrainz_cover_url(metadata: dict, session: aiohttp.ClientSession) -> str | None:
    try:
        if metadata.get('upc') and metadata['upc'] != "0":
            mb_url = f"https://musicbrainz.org/ws/2/release?query=barcode:{metadata['upc']}&fmt=json"
            async with session.get(mb_url, headers={'User-Agent': 'TidalBot/1.0'}) as resp:
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
        LOGGER.warning(f"MusicBrainz cover lookup failed: {e}")
    return None


async def get_cover(cover_id, meta: dict, thumbnail=False, user_id=0):
    original_url = None
    if cover_id:
        original_url = (
            f'https://resources.tidal.com/images/{cover_id.replace("-", "/")}/80x80.jpg'
            if thumbnail
            else f'https://resources.tidal.com/images/{cover_id.replace("-", "/")}/1280x1280.jpg'
        )
    
    # Jangan proses thumbnail ke iTunes/MB agar proses download tetap cepat
    if thumbnail:
        return await create_cover_file(original_url, meta, thumbnail)

    # PASTIKAN user_id adalah integer agar pembacaan setting akurat
    try:
        uid = int(user_id)
    except:
        uid = 0
        
    cover_source = bot_set.user_data.get(uid, {}).get("tidal_cover_source", "original")
    final_url = None

    # --- PERBAIKAN DI SINI ---
    # Buka session sekaligus untuk iTunes maupun MusicBrainz
    if cover_source in ["itunes", "musicbrainz"]:
        async with aiohttp.ClientSession() as session:
            if cover_source == "itunes":
                final_url = await get_itunes_cover_url(meta, session)
            elif cover_source == "musicbrainz":
                final_url = await get_musicbrainz_cover_url(meta, session)
    # ------------------------

    # Jika API gagal menemukan album (hasilnya None), Fallback ke Original Tidal
    if not final_url:
        final_url = original_url

    return await create_cover_file(final_url, meta, thumbnail)


def get_artists_name(meta:dict):
    artists = []
    if meta.get('artists'): 
        for a in meta['artists']:
            artists.append(a['name'])
    elif meta.get('artist'): 
        artists.append(meta['artist']['name'])
        
    if not artists:
        return "Various Artists" 
        
    return ', '.join([str(artist) for artist in artists])
