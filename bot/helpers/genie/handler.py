# [FILE: bot/helpers/genie/handler.py]

import os
import re
import asyncio
import aiohttp
import requests
import json
from urllib.parse import unquote

from config import Config
from bot.logger import LOGGER
from bot.settings import bot_set
from bot.helpers.message import send_message, edit_message
from bot.helpers.utils import format_string, post_art_poster, run_concurrent_tasks
from bot.helpers.aria2_helper import aria2_download
from bot.helpers.uploder import track_upload, album_upload, playlist_upload
from bot.helpers.metadata import set_metadata

from .manager import genie_manager

HEADERS = {
    'sec-ch-ua': '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
}

QUALITY_MAP = {
    "flac24": "24bit",
    "flac16": "16bit",
    "mp3": "320k"
}

QUALITY_MAP_DISPLAY = {
    "flac24": "FLAC-24",
    "flac16": "FLAC-16",
    "mp3": "MP3 320kbps"
}

def find_val_ci(data, target_keys):
    """Mencari value di dalam JSON secara rekursif dan Case-Insensitive"""
    targets = [k.lower() for k in target_keys]
    if isinstance(data, dict):
        for k, v in data.items():
            if str(k).lower() in targets and v:
                return str(v)
        for k, v in data.items():
            res = find_val_ci(v, targets)
            if res: return res
    elif isinstance(data, list):
        for item in data:
            res = find_val_ci(item, targets)
            if res: return res
    return ""

def format_date(raw_date, use_dots=False):
    """Format string date ke YYYY.MM.DD atau YYYY-MM-DD dengan bersih (Tanpa 'Unknown')"""
    if not raw_date or str(raw_date).lower() == 'unknown': return ""
    rd = re.sub(r'[^0-9]', '', str(raw_date))
    if len(rd) >= 8:
        if use_dots: return f"{rd[:4]}.{rd[4:6]}.{rd[6:8]}"
        return f"{rd[:4]}-{rd[4:6]}-{rd[6:8]}"
    if len(rd) >= 4: 
        return rd[:4]
    return ""

async def fetch_json(session: aiohttp.ClientSession, url: str, max_retries=3):
    wait_time = 2
    loop = asyncio.get_event_loop()
    PROXY_STRING = getattr(Config, 'GENIE_PROXY', None) 
    proxy_dict = {"http": PROXY_STRING, "https": PROXY_STRING} if PROXY_STRING else None
    
    for attempt in range(max_retries):
        try:
            def _do_request():
                resp = requests.get(url, headers=HEADERS, timeout=15, proxies=proxy_dict)
                text = resp.text.strip()
                if resp.status_code != 200: raise ValueError(f"HTTP {resp.status_code}")
                if not text.startswith('{') and not text.startswith('['): raise ValueError(f"Diblokir oleh Genie: {text[:100]}")
                return json.loads(text)
            return await loop.run_in_executor(None, _do_request)
        except Exception as e:
            LOGGER.warning(f"Genie Request failed: {e}. Retrying... ({attempt + 1}/{max_retries})")
        await asyncio.sleep(wait_time)
        wait_time *= 2
    raise Exception("Max retries exceeded. Gagal memuat data dari Genie.")

def parse_code(url: str) -> str:
    match = re.findall(r'\d+', url)
    if match: return match[0]
    raise ValueError("Invalid URL Genie")

async def process_track(session, track_id, quality_pref, download_dir, details, extra_meta=None):
    if extra_meta is None: extra_meta = {}
    bitrate = QUALITY_MAP.get(quality_pref, "24bit")
    api_url = f"https://stm.genie.co.kr/player/j_StmInfo.json?uxtk=3173869132189.992&sign=Y&lpr=&svc=IV&bitrate={bitrate}&stk=Q3RoM0lJWUErZFdZVE1mREN2bi85UT09&itn=Y&dcd=ANDROID_ID%3A06568f5097d60690&xgnm={track_id}&uip=172.16.2.15&dvm=oppo%20r9tm&apvn=40607&ovn=5.1.1&unm=322011981&mts=Y"
    
    data = await fetch_json(session, api_url)
    try: track_data = data["DataSet"]["DATA"][0]
    except: raise Exception("Gagal mendapatkan data streaming untuk track ini.")

    stream_url = unquote(track_data["STREAMING_MP3_URL"])
    
    title = extra_meta.get('title') or unquote(find_val_ci(track_data, ['SONG_TTS', 'SONG_NAME', 'SONG_NM'])) or f"Track_{track_id}"
    artist = extra_meta.get('artist') or unquote(find_val_ci(track_data, ['ARTIST_NAME', 'ARTIST_NM'])) or "Unknown Artist"
    album_name = extra_meta.get('album') or unquote(find_val_ci(track_data, ['ALBUM_NAME', 'ALBUM_NM'])) or "Unknown Album"
    
    track_date_raw = find_val_ci(track_data, ['ALBUM_DATE', 'RELEASE_DATE', 'ISSUE_DATE', 'RLS_DT'])
    track_date_meta = format_date(track_date_raw, use_dots=False)
    
    track_pub = unquote(find_val_ci(track_data, ['PUBLISHER_NM', 'AGENCY_NM', 'COPYRIGHT', 'PLANNING_NM', 'LABEL_NM']))
    
    final_date_meta = extra_meta.get('date') or track_date_meta
    final_pub = extra_meta.get('publisher') or track_pub

    ext = "flac" if ".flac" in stream_url.lower() else "mp3"
    filename = f"{artist} - {title}.{ext}".replace("/", "_")
    filepath = os.path.join(download_dir, filename)

    metadata = {
        'title': title,
        'artist': artist,
        'album': album_name,
        'albumartist': extra_meta.get('albumartist', artist),
        'provider': 'Genie',
        'quality': QUALITY_MAP_DISPLAY.get(quality_pref, quality_pref.upper()),
        'filepath': filepath,
        'type': 'track',
        'extension': ext,
        'tracknumber': extra_meta.get('tracknumber', '1'),
        'totaltracks': extra_meta.get('totaltracks', '1'),
        'volume': extra_meta.get('volume', '1'),               
        'totalvolume': extra_meta.get('totalvolume', '1'),     
        'date': final_date_meta,            
        'release_date': final_date_meta,    
        'copyright': final_pub,
        'publisher': final_pub,
        'label': final_pub,                 
        'organization': final_pub
    }

    aria_details = details.copy() if details else {}
    aria_details['headers'] = HEADERS

    success = await aria2_download(stream_url, filepath, aria_details)
    if not success: raise Exception("Gagal mengunduh file melalui Aria2c.")
        
    try: await set_metadata(metadata, extra_meta.get('user_id', 0))
    except Exception as e: LOGGER.warning(f"Gagal menulis metadata: {e}")
        
    return metadata

async def start_genie(link: str, user: dict):
    user_id = user['user_id']
    quality_pref = genie_manager.get_user_quality(user_id)
    download_dir = os.path.join(Config.DOWNLOAD_BASE_DIR, str(user['r_id']))
    os.makedirs(download_dir, exist_ok=True)
    
    code = parse_code(link)
    details = None
    if 'bot_msg' in user:
        import hashlib
        cancel_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
        details = {'msg': user['bot_msg'], 'action': 'Download', 'machine': 'Aria2c', 'task_id': cancel_id}

    async with aiohttp.ClientSession() as session:
        if "xgnm" in link:
            if 'bot_msg' in user: await edit_message(user['bot_msg'], "🔍 **Fetching Genie Track...**")
            extra_base = {'user_id': user_id}
            metadata = await process_track(session, code, quality_pref, download_dir, details, extra_base)
            await track_upload(metadata, user)

        elif "axnm" in link:
            if 'bot_msg' in user: await edit_message(user['bot_msg'], "🔍 **Fetching Genie Album...**")
            api_url = f"https://info.genie.co.kr/info/album?axnm={code}"
            album_data = await fetch_json(session, api_url)
            
            album_info_dict = album_data.get('album_info', {})
            album_name = unquote(find_val_ci(album_info_dict, ['album_name', 'album_nm'])) or "Unknown Album"
            album_artist = unquote(find_val_ci(album_info_dict, ['artist_name', 'artist_nm'])) or "Unknown Artist"
            
            album_dir = os.path.join(download_dir, f"{album_artist} - {album_name}".replace("/", "_"))
            os.makedirs(album_dir, exist_ok=True)
            
            cover_url = unquote(find_val_ci(album_info_dict, ['album_img_path600', 'album_img_path']))
            if cover_url.startswith("//"): cover_url = "https:" + cover_url
            cover_path = os.path.join(album_dir, "cover.jpg")
            if cover_url:
                try:
                    async with session.get(cover_url, headers=HEADERS) as resp:
                        if resp.status == 200:
                            with open(cover_path, 'wb') as f: f.write(await resp.read())
                except: pass

            song_list = album_data.get('album_song_list', [])
            
            # PENCARIAN TANGGAL (DEEP SCAN HINGGA DAPAT)
            raw_date = find_val_ci(album_info_dict, ['album_date', 'release_dt', 'release_date', 'issue_date', 'rls_dt'])
            if not raw_date and song_list:
                raw_date = find_val_ci(song_list[0], ['album_date', 'release_date', 'issue_date', 'rls_dt'])
                
            poster_date = format_date(raw_date, use_dots=True) 
            meta_date = format_date(raw_date, use_dots=False)   
            
            # PENCARIAN PUBLISHER / LABEL (DEEP SCAN HINGGA DAPAT)
            publisher = unquote(find_val_ci(album_info_dict, ['publisher_name', 'publisher_nm', 'agency_name', 'agency_nm', 'planning_nm', 'copyright']))
            if not publisher and song_list:
                publisher = unquote(find_val_ci(song_list[0], ['publisher_nm', 'agency_nm', 'planning_nm', 'copyright']))

            max_cd = 1
            for s in song_list:
                cd_no = str(s.get('album_cd', '1'))
                if cd_no.isdigit() and int(cd_no) > max_cd:
                    max_cd = int(cd_no)
            
            album_metadata = {
                'title': album_name,
                'artist': album_artist,
                'provider': 'Genie',
                'quality': QUALITY_MAP_DISPLAY.get(quality_pref, quality_pref.upper()),
                'type': 'album',
                'folderpath': album_dir,
                'tracks': [], 
                'cover': cover_path if os.path.exists(cover_path) else None,
                'release_date': poster_date,    
                'date': poster_date,
                'total_volumes': str(max_cd),   
                'totalvolumes': str(max_cd),    
                'totalvolume': str(max_cd),     
                'explicit': 'False',
                'copyright': publisher,
                'publisher': publisher,
                'label': publisher,
                'organization': publisher
            }
            
            album_metadata['poster_msg'] = await post_art_poster(user, album_metadata)

            extra_meta_base = {
                'user_id': user_id,
                'album': album_name,            
                'albumartist': album_artist,
                'totaltracks': str(len(song_list)),
                'totalvolume': str(max_cd),
                'date': meta_date,              
                'release_date': meta_date,      
                'copyright': publisher,
                'publisher': publisher,
                'label': publisher,
                'organization': publisher
            }
            
            tasks = []
            for index, song in enumerate(song_list, start=1):
                track_id = song['song_id']
                cur_extra = extra_meta_base.copy()
                cur_extra['title'] = unquote(song.get('song_name', ''))
                cur_extra['artist'] = unquote(song.get('artist_name', ''))
                cur_extra['tracknumber'] = str(song.get('track_no', index))
                cur_extra['volume'] = str(song.get('album_cd', '1'))
                tasks.append(process_track(session, track_id, quality_pref, album_dir, None, cur_extra))

            update_details = {'text': "Downloading...", 'msg': user['bot_msg'], 'title': album_name, 'type': 'Album', 'action': 'Download'}
            task_results = await run_concurrent_tasks(tasks, update_details, limit=Config.MAX_WORKERS)
            successful_tracks = [res for res in task_results if res]

            if not successful_tracks: raise Exception("Semua lagu dalam album gagal diunduh.")

            album_metadata['tracks'] = successful_tracks
            album_metadata['totaltracks'] = len(successful_tracks)
            await album_upload(album_metadata, user)

        elif "plmSeq" in link:
            if 'bot_msg' in user: await edit_message(user['bot_msg'], "🔍 **Fetching Genie Playlist...**")
            api_url = f"https://app.genie.co.kr/Iv3/playlist/infosong.json?seq={code}"
            pl_data = await fetch_json(session, api_url)
            
            pl_title = unquote(find_val_ci(pl_data, ['plm_title'])) or "Unknown Playlist"
            pl_dir_name = f"Genie - {pl_title}".replace("/", "_")
            pl_dir = os.path.join(download_dir, pl_dir_name)
            os.makedirs(pl_dir, exist_ok=True)
            
            song_list = find_val_ci(pl_data, ['data_song'])
            if not isinstance(song_list, list): 
                # Mengakses struktur data langsung jika find_val_ci gagal mengambil list bersarang
                try: song_list = pl_data['DATASET']['DATA_SONG']['DATA']
                except: song_list = []
            
            pl_poster_date = ""
            pl_meta_date = ""
            pl_publisher = ""
            
            if song_list:
                first_song = song_list[0]
                raw_d = find_val_ci(first_song, ['album_date', 'release_date', 'issue_date', 'rls_dt'])
                pl_poster_date = format_date(raw_d, use_dots=True)
                pl_meta_date = format_date(raw_d, use_dots=False)
                pl_publisher = unquote(find_val_ci(first_song, ['publisher_nm', 'agency_nm', 'planning_nm', 'copyright']))
            
            pl_metadata = {
                'title': pl_title,
                'provider': 'Genie',
                'quality': QUALITY_MAP_DISPLAY.get(quality_pref, quality_pref.upper()),
                'type': 'playlist',
                'folderpath': pl_dir,
                'tracks': [],
                'release_date': pl_poster_date,
                'date': pl_poster_date,
                'total_volumes': '1',
                'totalvolumes': '1',
                'totalvolume': '1',
                'explicit': 'False',
                'copyright': pl_publisher,
                'publisher': pl_publisher,
                'label': pl_publisher,
                'organization': pl_publisher
            }
            
            pl_metadata['poster_msg'] = await post_art_poster(user, pl_metadata)
            
            tasks = []
            for index, song in enumerate(song_list, start=1):
                track_id = unquote(str(song.get('SONG_ID', '')))
                cur_extra = {
                    'user_id': user_id,
                    'album': pl_title,
                    'title': unquote(song.get('SONG_NAME', '')),
                    'artist': unquote(song.get('ARTIST_NAME', '')),
                    'tracknumber': str(index),
                    'totaltracks': str(len(song_list)),
                    'date': pl_meta_date,
                    'release_date': pl_meta_date,
                    'volume': '1',
                    'totalvolume': '1',
                    'copyright': pl_publisher,
                    'publisher': pl_publisher,
                    'label': pl_publisher,
                    'organization': pl_publisher
                }
                tasks.append(process_track(session, track_id, quality_pref, pl_dir, None, cur_extra))

            update_details = {'text': "Downloading...", 'msg': user['bot_msg'], 'title': pl_title, 'type': 'Playlist', 'action': 'Download'}
            task_results = await run_concurrent_tasks(tasks, update_details, limit=Config.MAX_WORKERS)
            successful_tracks = [res for res in task_results if res]

            if not successful_tracks: raise Exception("Semua lagu gagal diunduh.")

            pl_metadata['tracks'] = successful_tracks
            pl_metadata['totaltracks'] = len(successful_tracks)
            
            from bot.helpers.uploder import playlist_upload
            await playlist_upload(pl_metadata, user)

        elif "xxnm" in link: raise NotImplementedError("Artist Batch belum diterapkan.")
        else: raise Exception("URL tidak didukung.")
