# [GANTI FILE: bot/helpers/tidal/metadata.py]

import copy
import re
import aiohttp
import asyncio
import urllib.parse
from datetime import datetime
from bot.settings import bot_set
import aiolimiter

from bot.logger import LOGGER

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file

# Limit 1 request setiap 1.5 detik untuk MusicBrainz
MBZ_LIMITER = aiolimiter.AsyncLimiter(1, 1.5)

# --- SHARED SESSION & CACHES UNTUK METADATA TIDAL ---
_TIDAL_META_SESSION: aiohttp.ClientSession | None = None
_ALBUM_DATA_CACHE = {}
_UPC_GENRE_CACHE = {}
_COVER_URL_CACHE = {}

def get_tidal_meta_session() -> aiohttp.ClientSession:
    global _TIDAL_META_SESSION
    if _TIDAL_META_SESSION is None or _TIDAL_META_SESSION.closed:
        connector = aiohttp.TCPConnector(limit=30, keepalive_timeout=30, enable_cleanup_closed=True)
        timeout = aiohttp.ClientTimeout(total=12)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        }
        _TIDAL_META_SESSION = aiohttp.ClientSession(connector=connector, timeout=timeout, headers=headers)
    return _TIDAL_META_SESSION

async def close_tidal_meta_session():
    global _TIDAL_META_SESSION
    if _TIDAL_META_SESSION and not _TIDAL_META_SESSION.closed:
        await _TIDAL_META_SESSION.close()
        _TIDAL_META_SESSION = None
# ----------------------------------------------------


async def get_deezer_genre_by_upc(upc):
    """Mendapatkan Genre dari Deezer menggunakan kode UPC (Barcode) dengan cache."""
    if not upc:
        return None
    
    upc_str = str(upc).strip()
    if upc_str in _UPC_GENRE_CACHE:
        return _UPC_GENRE_CACHE[upc_str]

    url = f"https://api.deezer.com/album/upc:{upc_str}"
    session = get_tidal_meta_session()
    try:
        async with session.get(url, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                if isinstance(data, dict) and 'error' not in data:
                    if 'genres' in data and data['genres'].get('data'):
                        genre_name = data['genres']['data'][0].get('name')
                        if genre_name:
                            if len(_UPC_GENRE_CACHE) > 2000:
                                _UPC_GENRE_CACHE.clear()
                            _UPC_GENRE_CACHE[upc_str] = genre_name
                            return genre_name
    except Exception as e:
        LOGGER.warning(f"Deezer UPC lookup failed: {e}")
    return None


async def get_itunes_info(artist, title, album, use_album_search=False):
    """Mencari metadata tambahan dari iTunes Store dengan strategi pencarian bertingkat."""
    clean_title = re.sub(r'(?i)\s*[\(\[]\s*(feat|ft|with|prod|explicit|clean|dirty).*?[\)\]]', '', title)
    clean_title = re.sub(r'\s*\(.*?\)', '', clean_title).strip()
    
    primary_artist = artist.split(',')[0].split('&')[0].strip()

    search_terms = [f"{primary_artist} {clean_title}"]
    if title != clean_title:
        search_terms.append(f"{primary_artist} {title}")
    
    entity = "album" if use_album_search else "song"
    session = get_tidal_meta_session()
    
    for term in search_terms:
        encoded_term = urllib.parse.quote(term)
        url = f"https://itunes.apple.com/search?term={encoded_term}&entity={entity}&limit=1"
        
        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None) 
                    if isinstance(data, dict) and data.get('resultCount', 0) > 0:
                        return data['results'][0]
        except Exception as e:
            LOGGER.warning(f"iTunes lookup error ({term}): {e}")
                
    return None


async def get_musicbrainz_info(isrc):
    """Mencari metadata tambahan dari MusicBrainz."""
    if not isrc:
        return None
    
    url = f"https://musicbrainz.org/ws/2/recording?query=isrc:{isrc}&fmt=json&inc=tags+releases"
    headers = {"User-Agent": "TidalBot/1.0 ( mybot@example.com )"}
    session = get_tidal_meta_session()
    
    try:
        async with MBZ_LIMITER:
            async with session.get(url, headers=headers, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if isinstance(data, dict) and data.get('recordings'):
                        recording = data['recordings'][0]
                        info = {}
                        
                        if recording.get('releases'):
                            dates = [rel['date'] for rel in recording['releases'] if rel.get('date')]
                            if dates:
                                dates.sort()
                                info['date'] = dates[0]
                        
                        tags = recording.get('tags', [])
                        if tags:
                            sorted_tags = sorted(tags, key=lambda x: x.get('count', 0), reverse=True)
                            genre_list = [t['name'].title() for t in sorted_tags[:2] if t.get('name')]
                            if genre_list:
                                info['genre'] = ', '.join(genre_list)
                            
                        return info
    except Exception as e:
        LOGGER.warning(f"MusicBrainz lookup failed: {e}")
    return None


def parse_genre_field(data):
    """Mengekstrak nama genre dari berbagai format (string, dict, atau list)."""
    if not data:
        return None

    if isinstance(data, dict):
        return data.get('name')
    
    if isinstance(data, list):
        names = []
        for item in data:
            if isinstance(item, dict):
                if item.get('name'):
                    names.append(item['name'])
            else:
                names.append(str(item))
        return ', '.join(names) if names else None

    return str(data)


async def get_track_metadata(track_id, t_meta, r_id, cover=None, thumbnail=False, client=None, user_id=0):
    """Mengambil metadata track dengan optimasi cache album."""
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['itemid'] = track_id
    
    # --- 1. DATA DASAR TIDAL ---
    metadata['title'] = t_meta.get('title', 'Unknown Title')
    if t_meta.get('version'):
        metadata['title'] += f' ({t_meta["version"]})'
    metadata['title'] = metadata['title'].replace('/', ' ')
    
    metadata['albumartist'] = (t_meta.get('artist') or {}).get('name', 'Various Artists')
    metadata['artist'] = get_artists_name(t_meta)
    album_obj = t_meta.get('album') or {}
    metadata['album'] = album_obj.get('title', 'Unknown Album')
    metadata['isrc'] = t_meta.get('isrc', '')
    metadata['duration'] = t_meta.get('duration', 0)
    metadata['explicit'] = t_meta.get('explicit', False)
    
    raw_track_number = t_meta.get('trackNumber', 1)
    metadata['tracknumber'] = str(raw_track_number).zfill(2)
    
    metadata['volume'] = t_meta.get('volumeNumber', 1)
    metadata['copyright'] = t_meta.get('copyright') or ''
    
    if metadata['copyright']:
        clean_pub = re.sub(r'^(\(?[cpCP]\)?|©|℗)?\s*\d{4}\s*', '', metadata['copyright'])
        metadata['publisher'] = clean_pub.strip(" -.,")
    else:
        metadata['publisher'] = ''
    
    if album_obj:
        metadata['upc'] = album_obj.get('upc', '')
        metadata['totalvolume'] = album_obj.get('numberOfVolumes', 1)
        metadata['totaltracks'] = album_obj.get('numberOfTracks', 1)
    else:
        metadata['upc'] = ''
        metadata['totalvolume'] = 1
        metadata['totaltracks'] = 1

    # --- 2. SIAPKAN GENRE DARI TRACK (TIDAL INTERNAL) ---
    tidal_track_genre = parse_genre_field(t_meta.get('genre')) or parse_genre_field(t_meta.get('genres'))

    # --- 3. ENRICHMENT VIA TIDAL CLIENT (DENGAN CACHE ALBUM) ---
    tidal_album_date = None
    tidal_album_genre = None
    tidal_artist_genre = None

    if client:
        try:
            album_id = album_obj.get('id')
            if album_id:
                full_album = _ALBUM_DATA_CACHE.get(album_id)
                if not full_album:
                    full_album = await client.get_album(album_id)
                    if full_album:
                        if len(_ALBUM_DATA_CACHE) > 500:
                            _ALBUM_DATA_CACHE.clear()
                        _ALBUM_DATA_CACHE[album_id] = full_album

                if full_album:
                    if full_album.get('releaseDate'):
                        tidal_album_date = full_album['releaseDate']
                    tidal_album_genre = parse_genre_field(full_album.get('genre')) or parse_genre_field(full_album.get('genres'))
                    if full_album.get('upc'):
                        metadata['upc'] = full_album['upc']
                    if full_album.get('numberOfTracks'):
                        metadata['totaltracks'] = full_album['numberOfTracks']
                    if full_album.get('numberOfVolumes'):
                        metadata['totalvolume'] = full_album['numberOfVolumes']

            if not tidal_album_genre and not tidal_track_genre:
                artist_id = (t_meta.get('artist') or {}).get('id')
                if artist_id:
                    try:
                        artist_data = await client.get_artist(artist_id)
                        tidal_artist_genre = parse_genre_field(artist_data.get('genre')) or parse_genre_field(artist_data.get('genres'))
                    except Exception:
                        pass

            credits_data = await client.get_track_contributors(track_id)
            composers = []
            if isinstance(credits_data, dict) and 'items' in credits_data:
                for item in credits_data['items']:
                    role = item.get('role', '').lower()
                    name = item.get('name', '')
                    if 'composer' in role and name:
                        composers.append(name)
            
            if composers:
                metadata['composer'] = ', '.join(composers)

        except Exception as e:
            LOGGER.warning(f"Tidal Client Enrichment Failed: {e}")

    # --- 4. EXTERNAL LOOKUP (Deezer UPC > iTunes > MusicBrainz) ---
    deezer_genre = None
    itunes_data = None
    mb_data = None

    if not tidal_album_genre and not tidal_track_genre and not tidal_artist_genre:
        if metadata.get('upc'):
            try:
                deezer_genre = await get_deezer_genre_by_upc(metadata['upc'])
            except Exception:
                pass
        
        if not deezer_genre:
            try:
                itunes_data = await get_itunes_info(metadata['artist'], metadata['title'], metadata['album'])
                if not itunes_data:
                    itunes_data = await get_itunes_info(metadata['artist'], metadata['title'], metadata['album'], use_album_search=True)
            except Exception:
                pass

        if not deezer_genre and not itunes_data:
            try:
                mb_data = await get_musicbrainz_info(metadata['isrc'])
            except Exception:
                pass

    # --- 5. MERGING GENRE ---
    final_genre = (
        tidal_album_genre
        or tidal_track_genre
        or deezer_genre
        or tidal_artist_genre
        or (itunes_data.get('primaryGenreName') if itunes_data else None)
        or (mb_data.get('genre') if mb_data else None)
    )
    if final_genre: 
        metadata['genre'] = final_genre

    # --- 6. MERGING DATES ---
    final_date = tidal_album_date or album_obj.get('releaseDate')
    if not final_date and t_meta.get('streamStartDate'):
        final_date = t_meta['streamStartDate'][:10]
    if not final_date:
        if itunes_data and itunes_data.get('releaseDate'):
            final_date = itunes_data['releaseDate'][:10]
        elif mb_data and mb_data.get('date'):
            final_date = mb_data['date']

    if final_date:
        metadata['release_date'] = final_date
        metadata['date'] = final_date[:4]
    else:
        metadata['release_date'] = ''
        metadata['date'] = ''

    # Cover Art
    album_cover_id = album_obj.get('cover')
    metadata['cover'] = cover if cover else await get_cover(album_cover_id, metadata, False, user_id)
    metadata['thumbnail'] = thumbnail if thumbnail else await get_cover(album_cover_id, metadata, True, user_id)

    if not metadata.get('composer') and t_meta.get('composers'):
        metadata['composer'] = ', '.join([c.get('name', '') for c in t_meta['composers'] if c.get('name')])

    metadata['provider'] = 'Tidal'
    metadata['type'] = 'track'

    return metadata


async def get_album_metadata(album_id, a_meta, t_meta, r_id, user_id=0):
    """Mengambil metadata album dan menyimpannya ke cache agar tidak di-request ulang oleh tiap track."""
    if album_id and isinstance(a_meta, dict):
        if len(_ALBUM_DATA_CACHE) > 500:
            _ALBUM_DATA_CACHE.clear()
        _ALBUM_DATA_CACHE[album_id] = a_meta

    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['itemid'] = album_id
    metadata['albumartist'] = (a_meta.get('artist') or {}).get('name', 'Unknown Artist')
    metadata['upc'] = a_meta.get('upc', '')
    metadata['title'] = a_meta.get('title', 'Unknown Album')
    if a_meta.get('version'):
        metadata['title'] += f' ({a_meta["version"]})'
    metadata['album'] = a_meta.get('title', 'Unknown Album')
    metadata['artist'] = get_artists_name(a_meta)
    
    if a_meta.get('releaseDate'):
        metadata['release_date'] = a_meta['releaseDate'] 
        metadata['date'] = a_meta['releaseDate'].split('-')[0] 
    else:
        metadata['release_date'] = ''
        metadata['date'] = ''
    
    metadata['totaltracks'] = a_meta.get('numberOfTracks', 1)
    metadata['duration'] = a_meta.get('duration', 0)
    
    raw_copyright = a_meta.get('copyright') or ''
    metadata['copyright'] = raw_copyright
    
    if raw_copyright:
        clean_pub = re.sub(r'^(\(?[cpCP]\)?|©|℗)?\s*\d{4}\s*', '', raw_copyright)
        metadata['publisher'] = clean_pub.strip(" -.,")
    else:
        metadata['publisher'] = ''

    metadata['explicit'] = a_meta.get('explicit', False)
    metadata['totalvolume'] = a_meta.get('numberOfVolumes', 1)
    metadata['provider'] = 'Tidal'
    metadata['type'] = 'album'
    
    album_genre = parse_genre_field(a_meta.get('genre')) or parse_genre_field(a_meta.get('genres'))
    if not album_genre and metadata.get('upc'):
        try:
            album_genre = await get_deezer_genre_by_upc(metadata['upc'])
        except Exception:
            pass
    
    if not album_genre:
        try:
            itunes_data = await get_itunes_info(metadata['artist'], metadata['title'], metadata['album'], use_album_search=True)
            if itunes_data and itunes_data.get('primaryGenreName'):
                album_genre = itunes_data['primaryGenreName']
        except Exception:
            pass
            
    if album_genre:
        metadata['genre'] = album_genre
        a_meta['genre'] = album_genre

    metadata['cover'] = await get_cover(a_meta.get('cover'), metadata, False, user_id)
    metadata['thumbnail'] = await get_cover(a_meta.get('cover'), metadata, True, user_id)

    metadata['tracks'] = []
    for track in (t_meta.get('items') or []):
        raw_tn = track.get('trackNumber', 1)
        str_tn = str(raw_tn).zfill(2)

        track_title = track.get('title', 'Unknown Title')
        if track.get('version'):
            track_title += f" ({track['version']})"
        track_title = track_title.replace('/', ' ')

        stub_meta = {
            'itemid': track['id'],
            'albumartist': metadata['albumartist'],
            'album': metadata['album'],
            'cover': metadata['cover'], 
            'thumbnail': metadata['thumbnail'], 
            'provider': 'Tidal',
            'title': track_title,
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
    metadata['albumartist'] = (p_meta.get('creator') or {}).get('name', 'Various Artists')
    metadata['artist'] = 'Various Artists'
    metadata['title'] = p_meta.get('title', 'Unknown Playlist')
    metadata['album'] = metadata['title']
    metadata['upc'] = p_meta.get('uuid', '')

    try:
        parsed_date = datetime.strptime(p_meta['created'], '%Y-%m-%dT%H:%M:%S.%f%z')
        metadata['release_date'] = str(parsed_date.date())
        metadata['date'] = str(parsed_date.year)
    except (ValueError, KeyError, TypeError):
        metadata['release_date'] = ''
        metadata['date'] = ''

    metadata['totaltracks'] = p_meta.get('numberOfTracks', 0)
    metadata['duration'] = p_meta.get('duration', 0)
    metadata['explicit'] = p_meta.get('explicit', False)
    metadata['provider'] = 'Tidal'
    metadata['type'] = 'playlist' 

    metadata['cover'] = await get_cover(p_meta.get('image'), metadata, False, user_id)
    metadata['thumbnail'] = await get_cover(p_meta.get('image'), metadata, True, user_id)

    metadata['tracks'] = []
    for item in (t_meta.get('items') or []):
        if item.get('type') == 'track' and item.get('item'):
            track = item['item']
            raw_tn = track.get('trackNumber', 1)
            str_tn = str(raw_tn).zfill(2)

            track_title = track.get('title', 'Unknown Title')
            if track.get('version'):
                track_title += f" ({track['version']})"
            track_title = track_title.replace('/', ' ')

            stub_meta = {
                'itemid': track['id'],
                'albumartist': (track.get('artist') or {}).get('name', 'Various Artists'),
                'album': (track.get('album') or {}).get('title', 'Unknown Album'),
                'cover': None, 
                'thumbnail': None,
                'provider': 'Tidal',
                'title': track_title,
                'artist': get_artists_name(track),
                'tracknumber': str_tn 
            }
            metadata['tracks'].append(stub_meta)
    
    metadata['totaltracks'] = len(metadata['tracks'])
    return metadata


async def get_artist_metadata(a_meta: dict, r_id, user_id=0):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['artist'] = a_meta.get('name', 'Unknown Artist')
    metadata['title'] = metadata['artist']
    metadata['provider'] = 'Tidal'
    metadata['type'] = 'artist'
    metadata['cover'] = await get_cover(a_meta.get('picture'), metadata, False, user_id)
    metadata['thumbnail'] = await get_cover(a_meta.get('picture'), metadata, True, user_id)
    return metadata


async def get_video_metadata(video_id, v_meta, r_id, client=None, user_id=0):
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['itemid'] = video_id
    metadata['title'] = v_meta.get('title', 'Unknown Video')
    metadata['artist'] = get_artists_name(v_meta)
    metadata['albumartist'] = metadata['artist']
    metadata['duration'] = v_meta.get('duration', 0)
    metadata['explicit'] = v_meta.get('explicit', False)
    metadata['provider'] = 'Tidal'
    metadata['type'] = 'video'
    
    metadata['cover'] = await get_cover(v_meta.get('imageId'), metadata, False, user_id)
    metadata['thumbnail'] = await get_cover(v_meta.get('imageId'), metadata, True, user_id)
    
    return metadata
    

async def get_itunes_cover_url(metadata: dict, session: aiohttp.ClientSession) -> str | None:
    try:
        term = f"{metadata.get('artist', '')} {metadata.get('album', '')}".strip()
        if not term:
            return None
        encoded_term = urllib.parse.quote(term)
        url = f"https://itunes.apple.com/search?term={encoded_term}&entity=album&limit=1"
        async with session.get(url, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                if isinstance(data, dict) and data.get('resultCount', 0) > 0:
                    artwork_url = data['results'][0].get('artworkUrl100')
                    if artwork_url:
                        return artwork_url.replace('100x100bb', '10000x10000bb')
    except Exception as e:
        LOGGER.warning(f"iTunes cover lookup failed: {e}")
    return None


async def get_musicbrainz_cover_url(metadata: dict, session: aiohttp.ClientSession) -> str | None:
    try:
        if metadata.get('upc') and metadata['upc'] != "0":
            mb_url = f"https://musicbrainz.org/ws/2/release?query=barcode:{metadata['upc']}&fmt=json"
            async with MBZ_LIMITER:
                async with session.get(mb_url, headers={'User-Agent': 'TidalBot/1.0 ( mybot@example.com )'}) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        if isinstance(data, dict) and data.get('releases'):
                            release_id = data['releases'][0]['id']
                            caa_api = f"https://coverartarchive.org/release/{release_id}"
                            async with session.get(caa_api) as caa_resp:
                                if caa_resp.status == 200:
                                    caa_data = await caa_resp.json(content_type=None)
                                    if isinstance(caa_data, dict) and caa_data.get('images'):
                                        for img in caa_data['images']:
                                            if img.get('front'):
                                                return img['image']
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
    
    if thumbnail:
        return await create_cover_file(original_url, meta, thumbnail)

    cover_source = bot_set.user_data.get(user_id, {}).get("tidal_cover_source", "original")
    final_url = None

    if cover_source in ["itunes", "musicbrainz"]:
        cache_key = f"{cover_source}:{meta.get('upc') or ''}:{meta.get('artist') or ''}:{meta.get('album') or ''}"
        if cache_key in _COVER_URL_CACHE:
            final_url = _COVER_URL_CACHE[cache_key]
        else:
            session = get_tidal_meta_session()
            if cover_source == "itunes":
                final_url = await get_itunes_cover_url(meta, session)
            elif cover_source == "musicbrainz":
                final_url = await get_musicbrainz_cover_url(meta, session)
            if final_url:
                if len(_COVER_URL_CACHE) > 2000:
                    _COVER_URL_CACHE.clear()
                _COVER_URL_CACHE[cache_key] = final_url

    if not final_url:
        final_url = original_url

    return await create_cover_file(final_url, meta, thumbnail)


def get_artists_name(meta: dict):
    artists = []
    if meta.get('artists'): 
        for a in meta['artists']:
            if a.get('name'):
                artists.append(a['name'])
    elif meta.get('artist') and meta['artist'].get('name'): 
        artists.append(meta['artist']['name'])
        
    if not artists:
        return "Various Artists" 
        
    return ', '.join([str(artist) for artist in artists])
