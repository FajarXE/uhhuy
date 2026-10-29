# [GANTI FILE: bot/helpers/qobuz/utils.py]

import re
import copy
import bot.helpers.translations as lang
import logging
import aiohttp
import urllib.parse
import os
import aiolimiter
from datetime import datetime
from config import Config

from ..message import send_message, edit_message
from ..utils import format_string
from ..metadata import metadata as base_meta
from ..metadata import create_cover_file

from bot.settings import bot_set

class QobuzContentUnavailableError(Exception):
    pass

# Limit 1 request setiap 1.5 detik untuk MusicBrainz
MBZ_LIMITER = aiolimiter.AsyncLimiter(1, 1.5)

FALLBACK_IMAGE_PATH = os.path.join(Config.WORK_DIR, "project-siesta.png")

# --- SHARED HTTP SESSION & CACHE COVER URL ---
_QOBUZ_UTILS_SESSION = None
_COVER_URL_CACHE = {}

def get_qobuz_utils_session() -> aiohttp.ClientSession:
    global _QOBUZ_UTILS_SESSION
    if _QOBUZ_UTILS_SESSION is None or _QOBUZ_UTILS_SESSION.closed:
        connector = aiohttp.TCPConnector(limit=30, keepalive_timeout=30, enable_cleanup_closed=True)
        timeout = aiohttp.ClientTimeout(total=15)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
        }
        _QOBUZ_UTILS_SESSION = aiohttp.ClientSession(connector=connector, timeout=timeout, headers=headers)
    return _QOBUZ_UTILS_SESSION

async def close_qobuz_utils_session():
    global _QOBUZ_UTILS_SESSION
    if _QOBUZ_UTILS_SESSION and not _QOBUZ_UTILS_SESSION.closed:
        await _QOBUZ_UTILS_SESSION.close()
        _QOBUZ_UTILS_SESSION = None
# ---------------------------------------------


async def get_itunes_cover_url(metadata: dict, session: aiohttp.ClientSession) -> str | None:
    try:
        if metadata.get('upc') and metadata['upc'] != "0":
            upc_url = f"https://itunes.apple.com/lookup?upc={metadata['upc']}&entity=album&limit=1"
            async with session.get(upc_url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if data.get('resultCount', 0) > 0:
                        artwork_url = data['results'][0].get('artworkUrl100')
                        if artwork_url:
                            return artwork_url.replace('100x100bb.jpg', '10000x10000bb.jpg')
        if metadata.get('albumartist') and metadata.get('album'):
            search_term = urllib.parse.quote(f"{metadata['albumartist']} {metadata['album']}")
            search_url = f"https://itunes.apple.com/search?term={search_term}&entity=album&media=music&limit=5"
            async with session.get(search_url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if data.get('resultCount', 0) > 0:
                        for result in data['results']:
                            itunes_album = result.get('collectionName', '').lower()
                            itunes_artist = result.get('artistName', '').lower()
                            local_album = metadata['album'].lower()
                            local_artist = metadata['albumartist'].lower()
                            if (local_album in itunes_album or itunes_album in local_album) and \
                               (local_artist in itunes_artist):
                                artwork_url = result.get('artworkUrl100')
                                if artwork_url:
                                    return artwork_url.replace('100x100bb.jpg', '10000x10000bb.jpg')
    except Exception as e:
        logging.warning(f"Pencarian sampul iTunes gagal untuk UPC {metadata.get('upc')}: {e}")
        return None
    return None


async def get_musicbrainz_cover_url(metadata: dict, session: aiohttp.ClientSession) -> str | None:
    try:
        if metadata.get('upc') and metadata['upc'] != "0":
            mb_url = f"https://musicbrainz.org/ws/2/release?query=barcode:{metadata['upc']}&fmt=json"
            async with MBZ_LIMITER:
                async with session.get(mb_url, headers={'User-Agent': 'MusicBot/1.0 ( mybot@example.com )'}) as resp:
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
                                            if img.get('front'):
                                                return img['image']
                                        return caa_data['images'][0]['image']
    except Exception as e:
        logging.warning(f"Pencarian sampul MusicBrainz gagal untuk UPC {metadata.get('upc')}: {e}")
        return None
    return None


async def resolve_qobuz_cover_url(metadata: dict, q_meta: dict, user: dict) -> str:
    """Menentukan URL cover art terbaik dengan sistem caching agar tidak spam API pada playlist."""
    u_id = user.get('user_id', 0) if user else 0
    cover_source = bot_set.user_data.get(u_id, {}).get("qobuz_cover_source", "itunes")

    if 'album' in q_meta and isinstance(q_meta['album'], dict) and 'image' in q_meta['album']:
        img_dict = q_meta['album'].get('image') or {}
    else:
        img_dict = q_meta.get('image') or {}
    qobuz_fallback_url = img_dict.get('original') or img_dict.get('large')

    if cover_source == "original":
        return qobuz_fallback_url or (FALLBACK_IMAGE_PATH if os.path.exists(FALLBACK_IMAGE_PATH) else '')

    cache_key = f"{cover_source}:{metadata.get('upc') or ''}:{metadata.get('albumartist') or ''}:{metadata.get('album') or ''}"
    if cache_key in _COVER_URL_CACHE:
        return _COVER_URL_CACHE[cache_key]

    cover_url = None
    try:
        session = get_qobuz_utils_session()
        if cover_source == "itunes":
            cover_url = await get_itunes_cover_url(metadata, session)
        elif cover_source == "musicbrainz":
            cover_url = await get_musicbrainz_cover_url(metadata, session)
    except Exception as e:
        logging.warning(f"Sesi pencarian sampul ({cover_source}) gagal: {e}")

    final_url = cover_url or qobuz_fallback_url
    if final_url:
        if len(_COVER_URL_CACHE) > 2000:
            _COVER_URL_CACHE.clear()
        _COVER_URL_CACHE[cache_key] = final_url
        return final_url

    if os.path.exists(FALLBACK_IMAGE_PATH):
        return FALLBACK_IMAGE_PATH
    return ''


def get_credits(meta, keys, roles=None):
    """Mengambil daftar nama dari berbagai sumber secara agresif."""
    names = []
    target_roles = [r.lower() for r in roles] if roles else []
    
    if roles and meta.get('performers'):
        try:
            raw_perf = meta['performers'].replace('\r', '').replace('\n', '')
            chunks = raw_perf.split(' - ')
            for chunk in chunks:
                chunk_lower = chunk.lower()
                if any(tr in chunk_lower for tr in target_roles):
                    parts = chunk.split(',')
                    if len(parts) > 0:
                        potential_name = parts[0].strip()
                        if potential_name.lower() not in target_roles:
                            names.append(potential_name)
        except Exception as e:
            logging.warning(f"Gagal parsing performers: {e}")

    if roles and 'contributors' in meta and isinstance(meta['contributors'], list):
        for item in meta['contributors']:
            item_role = item.get('role', '').lower()
            if any(tr in item_role for tr in target_roles):
                if item.get('name'):
                    names.append(item['name'])

    for key in keys:
        if key in meta:
            val = meta[key]
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and item.get('name'):
                        names.append(item['name'])
                    elif isinstance(item, str):
                        names.append(item)
            elif isinstance(val, dict):
                if val.get('name'):
                    names.append(val['name'])
            elif isinstance(val, str):
                names.append(val)

    seen = set()
    unique_names = [x for x in names if not (x in seen or seen.add(x))]
    
    return ', '.join(unique_names)


async def get_track_metadata(item_id, r_id, q_meta=None, user: dict=None, download_cover: bool=True):
    if user is None:
        logging.error("User dict None in get_track_metadata! Multi-login will fail.")
        return None, "Error: User data tidak ditemukan."
    
    client = user['qobuz_api'] 

    if q_meta is None:
        raw_meta = await client.get_track_url(item_id, user)
        if raw_meta and "sample" not in raw_meta and raw_meta.get('sampling_rate'):
            q_meta = await client.get_track_meta(item_id)
            if not q_meta or not q_meta.get('streamable'):
                return None, "UNAVAILABLE" 
        else:
            return None, "UNAVAILABLE"
    elif not q_meta.get('streamable', True):
        return None, "UNAVAILABLE"
    
    metadata = copy.deepcopy(base_meta)

    now = datetime.now()
    tag_time_str = now.strftime('%Y-%m-%d %H:%M:%S')
    utc_time_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['itemid'] = item_id
    
    metadata['title'] = q_meta.get('title', 'Unknown Title')
    if q_meta.get('version'):
        metadata['title'] += f' ({q_meta["version"]})'
        
    album_obj = q_meta.get('album') or {}
    metadata['album'] = album_obj.get('title', 'Unknown Album')
    metadata['albumartist'] = (album_obj.get('artist') or {}).get('name', 'Unknown Artist')
    metadata['artist'] = await get_artists_name(album_obj) if album_obj else metadata['albumartist']
    
    metadata['copyright'] = q_meta.get('copyright', '')
    metadata['cpr'] = q_meta.get('copyright', '')
    
    label_name = (album_obj.get('label') or {}).get('name', '')
    metadata['label'] = label_name
    metadata['publisher'] = label_name
    metadata['pub'] = label_name
    
    upc_code = album_obj.get('upc', '')
    metadata['upc'] = upc_code
    metadata['ean'] = upc_code
    metadata['barcode'] = upc_code
    metadata['isrc'] = q_meta.get('isrc', '')
    
    rel_date = q_meta.get('release_date_original', '')
    metadata['date'] = rel_date
    metadata['creation_time'] = utc_time_str
    metadata['releasetime'] = rel_date
    metadata['RELEASETIME'] = rel_date
    metadata['originaldate'] = rel_date
    metadata['ORIGINALDATE'] = rel_date
    metadata['tagging_time'] = tag_time_str
    metadata['date_tagged'] = tag_time_str
    metadata['encoded_date'] = utc_time_str

    metadata['duration'] = q_meta.get('duration', 0)
    
    metadata['tracknumber'] = str(q_meta.get('track_number', 1)).zfill(2)
    metadata['totaltracks'] = str(album_obj.get('tracks_count', 1))
    metadata['volume'] = str(q_meta.get('media_number', '1'))
    metadata['totalvolume'] = str(album_obj.get('media_count', '1'))
    
    if album_obj.get('genre'):
         metadata['genre'] = album_obj['genre'].get('name', '')
    
    is_explicit = q_meta.get('parental_warning', False)
    metadata['explicit'] = is_explicit
    metadata['itunesadvisory'] = '1' if is_explicit else '0'
    
    metadata['composer'] = get_credits(
        q_meta, 
        ['composers', 'composer'], 
        ['composer', 'writer', 'author']
    )
    metadata['lyricist'] = get_credits(
        q_meta, 
        ['lyricist', 'writer'], 
        ['lyricist', 'writer', 'author']
    )
    metadata['writer'] = metadata['lyricist']
    metadata['producer'] = get_credits(q_meta, ['producer'], ['producer'])

    if q_meta.get('performer'):
        metadata['performer'] = q_meta['performer'].get('name', '')

    metadata['provider'] = 'Qobuz'
    metadata['type'] = 'track'

    metadata['bps'] = str(q_meta.get('bit_depth', ''))
    metadata['sample_rate'] = str(q_meta.get('sampling_rate', ''))

    metadata['_raw_q_meta'] = q_meta
    if download_cover:
        final_cover_path_or_url = await resolve_qobuz_cover_url(metadata, q_meta, user)
        metadata['cover'] = await create_cover_file(final_cover_path_or_url, metadata)
        metadata['thumbnail'] = await create_cover_file(final_cover_path_or_url, metadata, True)
        metadata.pop('_raw_q_meta', None)

    return metadata, None
  
async def get_album_metadata(item_id, r_id, user: dict):
    client = user['qobuz_api'] 
    q_meta = await client.get_album_meta(item_id)
    
    if not q_meta or not isinstance(q_meta, dict) or not q_meta.get('streamable'):
        return None, "UNAVAILABLE"
    
    metadata = copy.deepcopy(base_meta)

    now = datetime.now()
    tag_time_str = now.strftime('%Y-%m-%d %H:%M:%S')
    utc_time_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    
    metadata['tempfolder'] += f"{r_id}-temp/"
    metadata['itemid'] = item_id
    
    metadata['title'] = q_meta.get('title', 'Unknown Album')
    if q_meta.get('version'):
        metadata['title'] += f" ({q_meta['version']})"
        
    metadata['album'] = metadata['title']
    artist_name = (q_meta.get('artist') or {}).get('name', 'Unknown Artist')
    metadata['albumartist'] = artist_name
    metadata['artist'] = artist_name
    
    metadata['upc'] = q_meta.get('upc', '')
    metadata['ean'] = q_meta.get('upc', '')
    metadata['barcode'] = q_meta.get('upc', '')
    
    label_name = (q_meta.get('label') or {}).get('name', '')
    metadata['label'] = label_name
    metadata['publisher'] = label_name
    metadata['pub'] = label_name
    
    metadata['copyright'] = q_meta.get('copyright', '')
    metadata['cpr'] = q_meta.get('copyright', '')

    rel_date = q_meta.get('release_date_original', '')
    metadata['date'] = rel_date
    metadata['creation_time'] = utc_time_str
    metadata['releasetime'] = rel_date
    metadata['RELEASETIME'] = rel_date
    metadata['originaldate'] = rel_date
    metadata['ORIGINALDATE'] = rel_date
    metadata['tagging_time'] = tag_time_str
    metadata['date_tagged'] = tag_time_str
    
    metadata['totaltracks'] = str(q_meta.get('tracks_count', 1))
    metadata['totalvolume'] = str(q_meta.get('media_count', '1'))
    metadata['duration'] = q_meta.get('duration', 0)
    
    metadata['genre'] = (q_meta.get('genre') or {}).get('name', '')
    is_explicit = q_meta.get('parental_warning', False)
    metadata['explicit'] = is_explicit
    metadata['itunesadvisory'] = '1' if is_explicit else '0'
    
    metadata['provider'] = 'Qobuz'
    metadata['type'] = 'album'

    final_cover_path_or_url = await resolve_qobuz_cover_url(metadata, q_meta, user)
    metadata['cover'] = await create_cover_file(final_cover_path_or_url, metadata)
    metadata['thumbnail'] = await create_cover_file(final_cover_path_or_url, metadata, True)

    # --- BOOKLET CHECK ---
    metadata['booklet_url'] = None
    if q_meta.get('goodies'):
        for goodie in q_meta['goodies']:
            if goodie.get('file_format_id') == 21 and goodie.get('url'):
                metadata['booklet_url'] = goodie['url']
                logging.info(f"Booklet ditemukan untuk album: {metadata['title']}")
                break
    # ---------------------

    metadata['tracks'] = await get_track_meta_from_alb(q_meta, metadata) 

    return metadata, None

async def get_track_meta_from_alb(q_meta:dict, alb_meta):
    tracks = []
    
    now = datetime.now()
    tag_time_str = now.strftime('%Y-%m-%d %H:%M:%S')
    utc_time_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

    for track in (q_meta.get('tracks') or {}).get('items', []):
        metadata = copy.deepcopy(alb_meta)
        metadata['itemid'] = track['id']
        metadata['title'] = track.get('title', 'Unknown Title')
        if track.get('version'):
            metadata['title'] += f' ({track["version"]})'
        metadata['duration'] = track.get('duration', 0)
        metadata['isrc'] = track.get('isrc', '')
        
        metadata['tracknumber'] = str(track.get('track_number', 1)).zfill(2)
        metadata['volume'] = str(track.get('media_number', '1'))
        
        metadata['composer'] = get_credits(
            track, 
            ['composers', 'composer'], 
            ['composer', 'writer', 'author']
        )
        metadata['lyricist'] = get_credits(
            track, 
            ['lyricist', 'writer'], 
            ['lyricist', 'writer', 'author']
        )
        metadata['writer'] = metadata['lyricist']
        metadata['producer'] = get_credits(track, ['producer'], ['producer'])
            
        if track.get('performer'):
             metadata['performer'] = track['performer'].get('name', '')
             
        metadata['tagging_time'] = tag_time_str
        metadata['date_tagged'] = tag_time_str
        metadata['encoded_date'] = utc_time_str
        
        is_explicit_track = track.get('parental_warning', False)
        metadata['explicit'] = is_explicit_track
        metadata['itunesadvisory'] = '1' if is_explicit_track else '0'

        metadata['tracks'] = ''
        metadata['type'] = 'track'
        tracks.append(metadata)
    return tracks


async def get_playlist_meta(raw_meta, tracks, r_id, user: dict):
    metadata = copy.deepcopy(base_meta)

    metadata['tempfolder'] += f"{r_id}-temp/"

    metadata['title'] = raw_meta.get('name', 'Unknown Playlist')
    metadata['duration'] = raw_meta.get('duration', 0)
    
    metadata['totaltracks'] = str((raw_meta.get('tracks') or {}).get('total', len(tracks)))
    metadata['itemid'] = raw_meta.get('id', '')
    
    metadata['type'] = 'playlist'
    metadata['provider'] = 'Qobuz'
    
    if os.path.exists(FALLBACK_IMAGE_PATH):
        metadata['cover'] = FALLBACK_IMAGE_PATH
        metadata['thumbnail'] = FALLBACK_IMAGE_PATH
    else:
        metadata['cover'] = None 
        metadata['thumbnail'] = None
    
    for track in tracks:
        # Tunda download cover ke saat start_track berjalan paralel agar inisialisasi playlist instan!
        track_meta, err = await get_track_metadata(track['id'], r_id, track, user=user, download_cover=False)
        if err or not track_meta:
            continue
        metadata['tracks'].append(track_meta)

    if not metadata['tracks']:
        raise QobuzContentUnavailableError(f"Tidak ada lagu yang dapat di-stream pada playlist ini.")

    return metadata

async def get_artist_meta(artist_raw):
    metadata = copy.deepcopy(base_meta)
    metadata['title'] = artist_raw.get('name', 'Unknown Artist')
    metadata['type'] = 'artist'
    metadata['provider'] = 'Qobuz'
    return metadata

async def get_artists_name(meta):
    artists = []
    try:
        for a in meta['artists']:
            artists.append(a['name'])
    except Exception:
        if meta.get('artist') and meta['artist'].get('name'):
            artists.append(meta['artist']['name'])
    return ', '.join([str(artist) for artist in artists]) if artists else 'Unknown Artist'


async def check_type(url, user: dict):
    client = user['qobuz_api'] 
    possibles = {
            "playlist": {
                "func": "get_plist_meta", 
                "iterable_key": "tracks",
                "multi_type": "tracks" 
            },
            "artist": {
                "func": "get_artist_meta", 
                "iterable_key": "albums",
                "multi_type": "albums" 
            },
            "interpreter": {
                "func": "get_artist_meta", 
                "iterable_key": "albums",
                "multi_type": "albums" 
            },
            "label": {
                "func": "get_label_meta", 
                "iterable_key": "albums",
                "multi_type": "albums" 
            },
            "album": {"album": True, "func": None, "iterable_key": None},
            "track": {"album": False, "func": None, "iterable_key": None},
        }
    try:
        url_info = await get_url_info(url)
        if url_info is None:
            raise TypeError
            
        url_type, item_id = url_info
        type_dict = possibles[url_type]
        
    except (KeyError, IndexError):
        raise Exception(f"URL tidak dapat dikenali: {url}")
    except TypeError:
        raise Exception(f"URL Qobuz tidak valid atau tidak dapat di-parse: {url}")
        
    content = None
    items = None
    if type_dict["func"]:
        content = []
        if type_dict["multi_type"]:
            if url_type == "playlist":
                epoint = "playlist/get"
                key = "total"
            elif url_type in ["artist", "label", "interpreter"]:
                epoint = f"{url_type}/get"
                key = "total"
            else:
                raise Exception("Tipe multi-meta tidak terdefinisi.")
            res_iterator = client.multi_meta(epoint, key, item_id, type_dict["multi_type"])
            async for data in res_iterator:
                content.append(data)
            if not content:
                raise QobuzContentUnavailableError(f"API Qobuz gagal mengembalikan data untuk {url_type}/{item_id}. Coba akun lain.")
        if content:
            smart_discography = True
            if smart_discography and url_type == "artist":
                items = smart_discography_filter(
                    content,
                    save_space=True,
                    skip_extras=True,
                )
            else:
                if type_dict["iterable_key"] not in content[0]:
                     raise QobuzContentUnavailableError(f"Respons Qobuz tidak memiliki '{type_dict['iterable_key']}'")
                if 'items' in content[0][type_dict["iterable_key"]]:
                    items = content[0][type_dict["iterable_key"]]['items']
                else:
                    raise QobuzContentUnavailableError(f"Playlist ID:{item_id} kosong atau tidak memiliki track.")
        return items, item_id, type_dict, content
    else:
        return None, item_id, type_dict, content


async def get_url_info(url):
    regex_pattern = (
        r"(?:https:\/\/(?:w{3}|open|play)\.qobuz\.com)?(?:\/[a-z]{2}-[a-z]{2})?"
        r"?\/(album|artist|track|playlist|label|interpreter)(?:\/[-\w\d]+)?\/([\w\d]+)"
    )
    r = re.search(regex_pattern, url)
    if r:
        return r.groups()

    logging.info(f"Qobuz URL tidak dikenali, mencoba scrape HTML untuk: {url}")
    try:
        session = get_qobuz_utils_session()
        async with session.get(url, allow_redirects=True, timeout=10) as response:
            final_url = str(response.url)
            if response.status != 200:
                return None

            r_final = re.search(regex_pattern, final_url)
            if r_final:
                return r_final.groups()

            html_content = await response.text()
            og_type_match = re.search(r'<meta\s+property="og:type"\s+content="music\.(album|artist|song|playlist)"', html_content)
            id_match = re.search(r"\/(\d+)(?:\?.*)?$", final_url.split('?')[0])
            
            if og_type_match and id_match:
                og_type = og_type_match.group(1)
                item_id = id_match.group(1)
                if og_type == "song": og_type = "track"
                elif og_type == "artist":
                    if "/interpreter/" in final_url: og_type = "interpreter"
                    else: og_type = "artist"
                return (og_type, item_id)

            if "/interpreter/" in final_url and id_match:
                 return ("interpreter", id_match.group(1))
            return None
    except Exception as e:
        logging.error(f"Gagal meng-scrape HTML Qobuz: {e}")
        return None


def smart_discography_filter(contents: list, save_space: bool = False, skip_extras: bool = False) -> list:
    TYPE_REGEXES = {
        "remaster": r"(?i)(re)?master(ed)?",
        "extra": r"(?i)(anniversary|deluxe|live|collector|demo|expanded)",
    }
    def is_type(album_t: str, album: dict) -> bool:
        version = album.get("version", "")
        title = album.get("title", "")
        regex = TYPE_REGEXES[album_t]
        return re.search(regex, f"{title} {version}") is not None
    def essence(album: str) -> str:
        r = re.match(r"([^\(]+)(?:\s*[\(\[][^\)][\)\]])*", album)
        if not r: return album.lower()
        return r.group(1).strip().lower()
    requested_artist = contents[0].get('name', '')
    items = []
    for item in contents:
        if 'albums' in item and 'items' in item['albums']:
            items.extend(item['albums']['items'])
    title_grouped = dict()
    for item in items:
        title_ = essence(item.get("title", ""))
        if title_ not in title_grouped:
            title_grouped[title_] = []
        title_grouped[title_].append(item)
    items = []
    for albums in title_grouped.values():
        if not albums:
            continue
        best_bit_depth = max(a.get("maximum_bit_depth", 16) for a in albums)
        get_best = min if save_space else max
        best_sampling_rate = get_best(
            a.get("maximum_sampling_rate", 44.1)
            for a in albums
            if a.get("maximum_bit_depth", 16) == best_bit_depth
        )
        remaster_exists = any(is_type("remaster", a) for a in albums)
        def is_valid(album: dict) -> bool:
            return (
                album.get("maximum_bit_depth", 16) == best_bit_depth
                and album.get("maximum_sampling_rate", 44.1) == best_sampling_rate
                and (album.get("artist") or {}).get("name") == requested_artist
                and not (
                    (remaster_exists and not is_type("remaster", album))
                    or (skip_extras and is_type("extra", album))
                )
            )
        filtered = tuple(filter(is_valid, albums))
        if len(filtered) >= 1:
            items.append(filtered[0])
        else:
            items.append(albums[0])
    return items

    
async def get_quality(meta: dict, user: dict):
    client = user['qobuz_api'] 
    
    try:
        u_id = int(user.get("user_id", 0))
    except Exception:
        u_id = 0
        
    quality = client.quality
    
    if u_id in bot_set.user_data:
        user_settings = bot_set.user_data[u_id]
        user_qual = user_settings.get("qobuz_qual")
        if user_qual is not None:
            quality = user_qual
    
    if int(quality) == 5:
        return 'mp3', '320K'
    else:
        bit_depth = meta.get("bit_depth", 16)
        sampling_rate = meta.get("sampling_rate", 44.1)
        
        if isinstance(sampling_rate, float) and sampling_rate.is_integer():
            sampling_rate = int(sampling_rate)

        return 'flac', f'{bit_depth}B - {sampling_rate}k'
