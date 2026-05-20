# [GANTI FILE: bot/helpers/tidal/utils.py]

import re
import os
import aiofiles
import asyncio
import logging
import json
import base64
import urllib.parse

from shutil import copyfileobj
from xml.etree import ElementTree
from datetime import datetime 

from .manager import tidal_manager
try:
    from .tidal_api import TidalApi
except ImportError:
    class TidalApi: pass 

async def parse_url(url):
    patterns = [
        (r"/browse/track/(\d+)", "track"),
        (r"/browse/artist/(\d+)", "artist"),
        (r"/browse/album/(\d+)", "album"),
        (r"/browse/playlist/([\w-]+)", "playlist"),
        (r"/browse/video/(\d+)", "video"),  # <- TAUTAN VIDEO
        (r"/track/(\d+)", "track"),
        (r"/artist/(\d+)", "artist"),
        (r"/playlist/([\w-]+)", "playlist"),
        (r"/album/\d+/track/(\d+)", "track"),
        (r"/album/(\d+)", "album"),
        (r"/video/(\d+)", "video"),          # <- TAUTAN VIDEO
    ]
    
    for pattern, type_ in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1), type_
    
    return None, None

# Tambahkan fungsi baru di bagian paling bawah file
async def parse_m3u8_video(manifest_b64: str, auth_headers: dict):
    """Membaca master playlist HLS dan mengekstrak segment TS kualitas tertinggi."""
    manifest_json = json.loads(base64.b64decode(manifest_b64))
    master_url = manifest_json['urls'][0]
    
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(master_url, headers=auth_headers) as resp:
            master_m3u8 = await resp.text()
        
        best_url = None
        max_bw = 0
        lines = master_m3u8.splitlines()
        
        # Cari resolusi tertinggi
        for i, line in enumerate(lines):
            if line.startswith('#EXT-X-STREAM-INF:'):
                bw_match = re.search(r'BANDWIDTH=(\d+)', line)
                bw = int(bw_match.group(1)) if bw_match else 0
                if bw > max_bw and i + 1 < len(lines):
                    max_bw = bw
                    best_url = lines[i+1].strip()
                    # Tangani URL relatif
                    if not best_url.startswith('http'):
                        best_url = urllib.parse.urljoin(master_url, best_url)
                    
        if not best_url:
            best_url = master_url
            
        async with session.get(best_url, headers=auth_headers) as resp:
            media_m3u8 = await resp.text()
            
        # Ekstrak file TS
        segment_urls = []
        for line in media_m3u8.splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                if not line.startswith('http'):
                    line = urllib.parse.urljoin(best_url, line)
                segment_urls.append(line)
                
        return segment_urls

async def convert_ts_to_mp4(ts_path: str, output_path: str):
    """Membungkus ulang (muxing) file .ts hasil gabungan ke .mp4 tanpa re-encode visual."""
    cmd = f'ffmpeg -y -i "{ts_path}" -c copy -bsf:a aac_adtstoasc "{output_path}"'
    task = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await task.wait()


async def get_stream_session(track_data: dict, user: dict):
    # Ambil tag kemampuan audio dari metadata track
    media_tags = track_data['mediaMetadata']['tags']
    formats = None

    if 'tidal_api' not in user:
        raise ValueError("User dict tidak memiliki 'tidal_api' client instance.")
    
    client: TidalApi = user['tidal_api']
    
    # Ambil settingan user
    qual, spatial, _, __ = tidal_manager.get_user_quality_settings(user["user_id"])

    # Logika Session Spasial/HiRes
    if 'SONY_360RA' in media_tags and spatial == 'Sony 360RA':
        formats = '360ra'
    elif 'DOLBY_ATMOS' in media_tags and spatial == 'ATMOS AC3 JOC':
        formats = 'ac3'
    elif 'DOLBY_ATMOS' in media_tags and spatial == 'ATMOS AC4':
        formats = 'ac4'
    elif 'HIRES_LOSSLESS' in media_tags and qual == 'HI_RES':
        formats = 'flac_hires'

    # Pilih Session berdasarkan format
    session = {
            'flac_hires': client.mobile_hires,
            '360ra': client.mobile_hires if client.mobile_hires else client.mobile_atmos,
            'ac4': client.mobile_atmos,
            'ac3': client.tv_session,
            None: client.tv_session, 
    }[formats]

    # Handle kasus khusus Atmos di session mobile
    if not formats and 'DOLBY_ATMOS' in media_tags:
        if client.mobile_hires:
            session = client.mobile_hires

    # Logika Fallback Kualitas
    if formats == 'flac_hires':
        quality = 'HI_RES' 
    elif formats in ['360ra', 'ac3', 'ac4']:
        quality = 'DOLBY_ATMOS' if 'DOLBY' in str(formats) else 'LOW' 
    else:
        # Jika user minta MAX (HI_RES) TAPI lagu TIDAK punya tag HIRES_LOSSLESS
        if qual == 'HI_RES' and 'HIRES_LOSSLESS' not in media_tags:
            quality = 'LOSSLESS' 
        else:
            quality = qual 

    return session, quality
    

def parse_mpd(xml: bytes):
    xml = xml.decode('UTF-8')
    xml = re.sub(r'xmlns="[^"]+"', '', xml, count=1)
    root = ElementTree.fromstring(xml)
    tracks = []
    for period in root.findall('Period'):
        for adaptation_set in period.findall('AdaptationSet'):
            for rep in adaptation_set.findall('Representation'):
                content_type = adaptation_set.get('contentType')
                if content_type != 'audio':
                    raise ValueError('Only supports audio MPDs!')
                codec = rep.get('codecs').upper()
                if codec.startswith('MP4A'):
                    codec = 'AAC'
                seg_template = rep.find('SegmentTemplate')
                track_urls = [seg_template.get('initialization')]
                start_number = int(seg_template.get('startNumber') or 1)
                seg_timeline = rep.find('SegmentTimeline') or seg_template.find('SegmentTimeline')
                if seg_timeline is not None:
                    seg_time_list = []
                    cur_time = 0
                    for s in seg_timeline.findall('S'):
                        if s.get('t'):
                            cur_time = int(s.get('t'))
                        for i in range((int(s.get('r') or 0) + 1)):
                            seg_time_list.append(cur_time)
                            cur_time += int(s.get('d'))
                    seg_num_list = list(range(start_number, len(seg_time_list) + start_number))
                    track_urls += [seg_template.get('media').replace('$Number$', str(n)) for n in seg_num_list]
                tracks.append(track_urls)
    return tracks, codec


async def merge_tracks(temp_tracks: list, output_path: str):
    async with aiofiles.open(output_path, 'wb') as dest_file:
        for temp_location in temp_tracks:
            async with aiofiles.open(temp_location, 'rb') as segment_file:
                while True:
                    chunk = await segment_file.read(1024 * 64)
                    if not chunk:
                        break
                    await dest_file.write(chunk)
    delete_tasks = [asyncio.to_thread(os.remove, temp_location) for temp_location in temp_tracks]
    await asyncio.gather(*delete_tasks)


async def get_quality(stream_data: dict):
    quality_dict = qualities = {
        'LOW':'LOW',
        'HIGH':'HIGH',
        'LOSSLESS':'LOSSLESS',
        'HI_RES':'MAX',
        'HI_RES_LOSSLESS':'MAX'
    }
    if stream_data.get('audioMode') == 'DOLBY_ATMOS':
        return 'DOLBY ATMOS'
    return quality_dict.get(stream_data.get('audioQuality', 'LOW'), 'LOW')


async def sort_album_from_artist(album_data: dict, user: dict):
    albums = []
    _, spatial, _, __ = tidal_manager.get_user_quality_settings(user["user_id"])

    for album in album_data:
        audio_modes = album.get('audioModes', [])
        if 'DOLBY_ATMOS' in audio_modes \
            and spatial in ['ATMOS AC3 JOC', 'ATMOS AC4']: 
            albums.append(album)
        elif 'STEREO' in audio_modes \
            and spatial == 'OFF':
            albums.append(album)
        elif not audio_modes: 
             albums.append(album)

    unique_albums = {}
    for album in albums:
        unique_key = (album['title'], album.get('version', ''))
        if unique_key not in unique_albums:
            unique_albums[unique_key] = album
        else:
            existing_metadata = unique_albums[unique_key].get('mediaMetadata', {})
            new_metadata = album.get('mediaMetadata', {})
            if len(new_metadata) > len(existing_metadata):  
                unique_albums[unique_key] = album
    filtered_tracks = list(unique_albums.values())
    return filtered_tracks


async def ffmpeg_convert_and_tag(input_file: str, track_meta: dict):
    """
    Mengonversi dan menulis tag metadata lengkap menggunakan FFmpeg.
    """
    
    def escape_str(value):
        if value is None:
            value = ''
        if not isinstance(value, str):
            value = str(value)
        # Escape untuk shell command
        return value.replace("\\", "\\\\").replace("\"", "\\\"").replace("$", "\\$").replace("`", "\\`")

    input_file_escaped = escape_str(input_file)
    output_file_escaped = f"{input_file_escaped}.flac"
    
    # 1. Setup Cover Art
    cover_cmd = ""
    map_cmd = "-map 0:a" 
    
    cover_path = track_meta.get('cover')
    if cover_path and os.path.exists(cover_path):
        cover_cmd = f'-i "{escape_str(cover_path)}"' 
        # Attach cover sebagai stream video (standar FFmpeg)
        map_cmd += " -map 1 -c:v copy -disposition:v attached_pic -metadata:s:v title=\"Album cover\" -metadata:s:v comment=\"Cover (front)\""

    # 2. Persiapan Data Metadata
    # Format "1/10" untuk Track/Total
    t_num = str(track_meta.get('tracknumber') or '1')
    t_tot = str(track_meta.get('totaltracks') or '1')
    track_str = f"{t_num}/{t_tot}" 
    
    # Format "1/2" untuk Part/Total (Disc)
    d_num = str(track_meta.get('volume') or '1')
    d_tot = str(track_meta.get('totalvolume') or '1')
    disc_str = f"{d_num}/{d_tot}" 

    # --- PERBAIKAN: PUBLISHER MENGGUNAKAN DATA YANG SUDAH DIBERSIHKAN ---
    publisher = track_meta.get('publisher') or ''
    # --------------------------------------------------------------------
    
    copyright_val = track_meta.get('copyright') or ''
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 3. Mapping Metadata FFmpeg
    tags_to_write = {
        'title': track_meta.get('title'),
        'album': track_meta.get('album'),
        'album_artist': track_meta.get('albumartist'),
        'artist': track_meta.get('artist'),
        
        # Copyright
        'copyright': copyright_val,
        
        # --- PERBAIKAN: MENYAMAKAN TAG SESUAI PERMINTAAN USER ---
        # Publisher, Label, Organization, dan Producer menggunakan string Copyright yang dibersihkan
        'publisher': publisher,
        'organization': publisher, 
        'label': publisher,
        'producer': publisher, # User meminta "Producer" juga diisi dengan ini
        # ----------------------------------------------------------
        
        'track': track_str,
        'disc': disc_str,
        
        'genre': track_meta.get('genre'),
        'date': track_meta.get('date'), # Year
        
        'creation_time': now_str, 
        
        'ISRC': track_meta.get('isrc'),
        'UPC': track_meta.get('upc'),
        'BARCODE': track_meta.get('upc'),
        
        'lyrics': track_meta.get('lyrics'),
        'composer': track_meta.get('composer'),
        
        'rating': '1' if track_meta.get('explicit') is True else '0'
    }

    # 4. Custom Metadata (Force Write)
    # Menambahkan field spesifik 'pub' sesuai permintaan user
    tags_to_write['pub'] = publisher
    tags_to_write['cpr'] = copyright_val
    tags_to_write['encoded_date'] = now_str
    tags_to_write['tagging_time'] = now_str

    # 5. Build Command
    metadata_cmd = ""
    for key, value in tags_to_write.items():
        if value is not None and value != '':
            metadata_cmd += f' -metadata {key}="{escape_str(value)}"'

    # Jalankan FFmpeg
    cmd = (
        f'ffmpeg -i "{input_file_escaped}" {cover_cmd} '
        f'{map_cmd} '
        f'-c:a flac -compression_level 8 ' 
        f'{metadata_cmd} ' 
        f'-loglevel error -y "{output_file_escaped}"' 
    )
    
    task = await asyncio.create_subprocess_shell(cmd)
    await task.wait()
