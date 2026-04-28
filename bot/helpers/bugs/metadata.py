# [GANTI FILE: bot/helpers/bugs/metadata.py]

import copy
import re
import asyncio
import logging
from datetime import datetime
from urllib.parse import urlparse
from config import Config 

from ..metadata import metadata as base_meta
from ..metadata import create_cover_file
from .manager import bugs_manager, BugsError
from bot.logger import LOGGER

# Urutan kualitas (Map display)
QUALITY_MAP_DISPLAY = {
    'flac': ("FLAC 16-bit", "flac"),
    'aac256': ("AAC 320k", "m4a"), 
    '320k': ("MP3 320k", "mp3"),
    'aac': ("AAC 128k", "m4a")
}
# Urutan prioritas kualitas
QUALITY_ORDER = ["flac", "aac256", "320k", "aac"]

# Ukuran gambar yang didukung
BUGS_SUPPORTED_COVER_SIZES = [75, 140, 200, 350, 500, 1000, 1280, 1400, 2000, 3001]

def custom_url_parse(link: str):
    """Mengekstrak Tipe dan ID dari URL Bugs"""
    url = urlparse(link)
    path_match = None
    
    if url.hostname in ('music.bugs.co.kr', 'm.bugs.co.kr'):
        path_match = re.match(r'^\/(track|album|artist)\/(\d+)', url.path)
    else:
        raise BugsError(f'URL tidak valid: {link}')
        
    if not path_match:
        raise BugsError(f'URL tidak valid atau tidak didukung: {link}')
    
    type = path_match.group(1)
    return type, path_match.group(2), {}

async def _process_cover(metadata: dict, cover_path: str, base_size: int = 1400):
    if not cover_path:
        return None
    best_size = min(BUGS_SUPPORTED_COVER_SIZES, key=lambda x: abs(x - base_size))
    cover_size_str = str(best_size) if best_size <= 3000 else 'original'
    url = f'https://image.bugsm.co.kr/album/images/{cover_size_str}{cover_path}'
    return await create_cover_file(url, metadata)

async def _process_thumbnail(metadata: dict, cover_path: str):
    if not cover_path:
        return None
    url = f'https://image.bugsm.co.kr/album/images/200{cover_path}'
    return await create_cover_file(url, metadata, True)

async def process_track_metadata(track_id: str, r_id: str, user: dict, pre_data: dict = None, alb_info_pre: dict = None):
    """
    Memproses metadata untuk satu lagu Bugs (Lengkap dengan Credits & ISRC).
    """
    client = user['bugs_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    track_data = {}
    credits_list = []
    
    try:
        # Fetch data jika belum ada pre_data
        if pre_data:
            track_data = pre_data
            # Jika pre_data dari list album, kita mungkin perlu fetch detail untuk dapat credits/ISRC lengkap
            # Namun untuk efisiensi, kita coba pakai yang ada dulu.
            # Idealnya, untuk ISRC dan Credits lengkap, kita tetap butuh 'get_track'
            # Jika pre_data minim, kita force fetch:
            if 'isrc' not in track_data:
                track_data_list = await asyncio.to_thread(client.get_track, track_id)
                track_data = track_data_list[0].get('track').get('result')
                if len(track_data_list) > 1:
                    credits_list = track_data_list[1].get('track_artist_role', {}).get('list', [])
        else:
            # [0] = track info, [1] = track_artist_role (Credits)
            track_data_list = await asyncio.to_thread(client.get_track, track_id)
            track_data = track_data_list[0].get('track').get('result')
            if len(track_data_list) > 1:
                credits_list = track_data_list[1].get('track_artist_role', {}).get('list', [])
            
        # Dapatkan info album
        album_id = track_data.get('album', {}).get('album_id')
        if not album_id:
            raise BugsError(f"Gagal mendapatkan album_id dari track {track_id}")

        if alb_info_pre:
            album_data = alb_info_pre
        else:
            album_data_list = await asyncio.to_thread(client.get_album, album_id)
            album_data = album_data_list[0].get('album').get('result')

    except Exception as e:
        LOGGER.error(f"Bugs: Gagal mendapatkan metadata track {track_id}: {e}")
        raise e

    # --- 1. Basic Metadata ---
    metadata['itemid'] = track_id
    metadata['title'] = track_data.get('track_title')
    metadata['album'] = album_data.get('title')
    
    # Artist Utama
    metadata['artist'] = ", ".join([a.get('artist_nm') for a in track_data.get('artists')])
    metadata['albumartist'] = album_data.get('artists')[0].get('artist_nm')
    
    # --- PERUBAHAN DI SINI ---
    # Menggunakan .zfill(2) agar nomor track menjadi 01, 02, dst.
    metadata['tracknumber'] = str(track_data.get('track_no')).zfill(2)
    # -------------------------
    
    metadata['totaltracks'] = str(album_data.get('track_count'))
    metadata['discnumber'] = str(track_data.get('disc_no'))
    metadata['totalvolume'] = str(album_data.get('disc_count') or 1)
    
    # Date Handling
    release_date_str = album_data.get('release_ymd')
    if release_date_str:
        try:
            if len(release_date_str) == 6: release_date_str += '01'
            release_date_obj = datetime.strptime(release_date_str, '%Y%m%d')
            metadata['date'] = release_date_obj.strftime('%Y-%m-%d')
            metadata['year'] = release_date_obj.strftime('%Y')
        except ValueError:
            metadata['date'] = None
            metadata['year'] = None

    if album_data.get('genres'):
        metadata['genre'] = ", ".join([g.get('svc_nm') for g in album_data.get('genres')])
    
    metadata['provider'] = 'Bugs'
    metadata['type'] = 'track'
    metadata['explicit'] = False # Bugs jarang mengirim flag eksplisit via API ini

    # --- 2. Advanced Metadata (YANG SEBELUMNYA HILANG) ---

    # A. ISRC
    if track_data.get('isrc'):
        metadata['isrc'] = track_data.get('isrc')

    # B. Label & Copyright
    if album_data.get("labels"):
        label_name = album_data.get("labels")[0].get("label_nm")
        metadata['label'] = label_name
        metadata['publisher'] = label_name
        metadata['copyright'] = f'© {metadata["year"]} {label_name}'
    
    # C. UPC / Barcode / EAN
    # Bugs API kadang menyebutnya 'upc' atau 'barcode' di object album
    if album_data.get('upc'):
        metadata['upc'] = album_data.get('upc')
        metadata['barcode'] = album_data.get('upc')
        metadata['ean'] = album_data.get('upc')

    # D. Credits (Composer, Lyricist, Producer)
    # Parsing dari 'credits_list' yang diambil dari 'track_artist_role'
    composers = []
    lyricists = []
    producers = []
    
    for credit in credits_list:
        role = credit.get('artist_role_nm', '').lower() # Nama role (misal: Composer, Lyricist)
        # Atau gunakan code: credit.get('artist_role_cd')
        name = credit.get('artist_nm')
        
        # Cek role (support bahasa Inggris dan Korea jika API berubah)
        if 'composer' in role or '작곡' in role:
            composers.append(name)
        elif 'lyricist' in role or 'lyrics' in role or '작사' in role:
            lyricists.append(name)
        elif 'producer' in role or 'arranger' in role or '편곡' in role:
            producers.append(name)

    if composers:
        metadata['composer'] = ", ".join(composers)
    if lyricists:
        metadata['lyricist'] = ", ".join(lyricists)
    if producers:
        metadata['producer'] = ", ".join(producers)

    # --- End Advanced Metadata ---
    
    # --- Sampul ---
    cover_path = album_data.get('image', {}).get('path')
    if cover_path:
        metadata['cover'] = await _process_cover(metadata, cover_path)
        metadata['thumbnail'] = await _process_thumbnail(metadata, cover_path)

    # --- Logika Kualitas ---
    user_id = user.get('user_id')
    preferred_quality = bugs_manager.get_user_quality(user_id)
    
    try:
        user_quality_order = QUALITY_ORDER[QUALITY_ORDER.index(preferred_quality):]
    except ValueError:
        user_quality_order = QUALITY_ORDER

    chosen_quality_key = None
    track_bitrates = track_data.get('bitrates', [])
    
    rights = track_data.get('rights', {}).get('streaming', {})
    needs_premium_flac = rights.get('flac_premium_yn', False)
    account_has_premium = getattr(client, 'account_flac_premium', False)

    if not rights.get('service_yn'):
        raise BugsError(f"Track '{metadata['title']}' tidak tersedia untuk streaming.")
    
    for q_key in user_quality_order:
        if q_key in track_bitrates:
            if 'flac' in q_key and needs_premium_flac and not account_has_premium:
                continue
            chosen_quality_key = q_key
            break
            
    if not chosen_quality_key:
        fallback_order = reversed(QUALITY_ORDER)
        for q_key in fallback_order:
            if q_key in track_bitrates:
                if 'flac' in q_key and needs_premium_flac and not account_has_premium:
                    continue
                chosen_quality_key = q_key
                break

    if not chosen_quality_key:
        raise BugsError(f"Tidak ada kualitas kompatibel untuk track {track_id}")

    metadata['quality'], metadata['extension'] = QUALITY_MAP_DISPLAY[chosen_quality_key]
    metadata['download_id'] = track_id
    metadata['download_quality_key'] = chosen_quality_key
    
    return metadata

async def process_album_metadata(album_id: str, r_id: str, user: dict):
    """
    Memproses metadata untuk album.
    """
    client = user['bugs_api']
    metadata = copy.deepcopy(base_meta)
    metadata['tempfolder'] += f"{r_id}-temp/"
    
    try:
        album_data_list = await asyncio.to_thread(client.get_album, album_id)
        album_data = album_data_list[0].get('album').get('result')
        
        tracks_list_data = await asyncio.to_thread(client.get_album_tracks, album_id)
        tracks_list = tracks_list_data[0].get('album_track').get('list')
        
    except Exception as e:
        LOGGER.error(f"Bugs: Gagal mendapatkan metadata album {album_id}: {e}")
        raise e

    # --- Metadata Album ---
    metadata['itemid'] = album_id
    metadata['title'] = album_data.get('title')
    metadata['album'] = album_data.get('title')
    metadata['artist'] = album_data.get('artists')[0].get('artist_nm')
    metadata['albumartist'] = album_data.get('artists')[0].get('artist_nm')
    
    # UPC / Barcode
    if album_data.get('upc'):
        metadata['upc'] = album_data.get('upc')
        metadata['barcode'] = album_data.get('upc')
    
    # Label
    if album_data.get("labels"):
        label_name = album_data.get("labels")[0].get("label_nm")
        metadata['label'] = label_name
        metadata['publisher'] = label_name
        metadata['copyright'] = f'© {metadata["year"] if "year" in metadata else ""} {label_name}'

    release_date_str = album_data.get('release_ymd')
    if release_date_str:
        try:
            if len(release_date_str) == 6: release_date_str += '01'
            release_date_obj = datetime.strptime(release_date_str, '%Y%m%d')
            metadata['date'] = release_date_obj.strftime('%Y-%m-%d')
            metadata['year'] = release_date_obj.strftime('%Y')
        except ValueError:
            metadata['date'] = None
            metadata['year'] = None
    
    metadata['totaltracks'] = str(album_data.get('track_count'))
    
    # --- PERBAIKAN: DETEKSI MULTI-DISC BUGS SECARA MANUAL ---
    max_vol = 1
    if tracks_list:
        for t in tracks_list:
            try:
                v = int(t.get('disc_no', 1))
                if v > max_vol: 
                    max_vol = v
            except: 
                pass
    metadata['totalvolume'] = str(max_vol)
    # --------------------------------------------------------
    
    metadata['provider'] = 'Bugs'
    metadata['type'] = 'album'
    metadata['explicit'] = False

    cover_path = album_data.get('image', {}).get('path')
    if cover_path:
        metadata['cover'] = await _process_cover(metadata, cover_path)
        metadata['thumbnail'] = await _process_thumbnail(metadata, cover_path)

    metadata['tracks'] = []
    for song_data in tracks_list:
        try:
            track_id = song_data.get('track_id')
            # Kita kirim song_data sebagai pre_data, tapi PERHATIKAN:
            # song_data dari 'get_album_tracks' biasanya TIDAK punya ISRC atau Credits lengkap.
            # Jadi process_track_metadata akan melakukan fetch ulang via get_track untuk mengisi ISRC/Credits.
            track_meta = await process_track_metadata(
                track_id, r_id, user, 
                pre_data=song_data, 
                alb_info_pre=album_data
            )
            
            # --- SUNTIKAN TOTAL VOLUME YANG BENAR KE TRACK ---
            track_meta['totalvolume'] = str(max_vol)
            # -------------------------------------------------
            
            track_meta['cover'] = metadata['cover'] 
            track_meta['thumbnail'] = metadata['thumbnail']
            metadata['tracks'].append(track_meta)
        except Exception as e:
            LOGGER.warning(f"Bugs: Gagal memproses track {song_data.get('track_id')} di album: {e}")
            continue

    if not metadata['tracks']:
        raise Exception(f"Tidak ada lagu yang valid ditemukan untuk album {metadata['title']}")
    
    metadata['quality'] = metadata['tracks'][0]['quality']
    return metadata
