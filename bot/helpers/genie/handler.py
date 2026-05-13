# [FILE: bot/helpers/genie/handler.py]

import os
import re
import asyncio
import aiohttp
import requests
from urllib.parse import unquote
from config import Config

from config import Config
from bot.logger import LOGGER
from bot.settings import bot_set
from bot.helpers.utils import format_string
from bot.helpers.message import send_message, edit_message
from bot.helpers.aria2_helper import aria2_download
from bot.helpers.uploder import track_upload, album_upload

from .manager import genie_manager

HEADERS = {
    'sec-ch-ua': '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
}

# Mapping kualitas berdasarkan API Genie
QUALITY_MAP = {
    "flac24": "24bit",
    "flac16": "16bit",
    "mp3": "320k"
}

import requests
import json
import asyncio
import aiohttp

async def fetch_json(session: aiohttp.ClientSession, url: str, max_retries=3):
    """Membungkus requests ke dalam thread dengan Proxy Opsional"""
    wait_time = 2
    loop = asyncio.get_event_loop()
    
    # Mengambil proxy dari config.py
    PROXY_STRING = getattr(Config, 'GENIE_PROXY', None) 
    
    # Jika proxy ada, buat dictionary. Jika tidak, atur sebagai None
    proxy_dict = {
        "http": PROXY_STRING,
        "https": PROXY_STRING
    } if PROXY_STRING else None
    
    for attempt in range(max_retries):
        try:
            def _do_request():
                # Parameter proxies akan menerima dict atau None dengan aman
                resp = requests.get(url, headers=HEADERS, timeout=15, proxies=proxy_dict)
                text = resp.text.strip()
                
                if resp.status_code != 200:
                    raise ValueError(f"HTTP {resp.status_code}")
                    
                # Validasi jika IP diblokir (Respons bukan JSON)
                if not text.startswith('{') and not text.startswith('['):
                    raise ValueError(f"Diblokir oleh Genie (Respons bukan JSON): {text[:100]}")
                    
                import json
                return json.loads(text)
            
            # Mengeksekusi request di background agar mesin uvloop tidak freeze
            return await loop.run_in_executor(None, _do_request)
            
        except Exception as e:
            from bot.logger import LOGGER
            LOGGER.warning(f"Genie Request failed: {e}. Retrying... ({attempt + 1}/{max_retries})")
        
        await asyncio.sleep(wait_time)
        wait_time *= 2
        
    raise Exception("Max retries exceeded. Gagal memuat data dari Genie.")

def parse_code(url: str) -> str:
    """Mengekstrak ID dari URL"""
    match = re.findall(r'\d+', url)
    if match:
        return match[0]
    raise ValueError("Invalid URL Genie")

async def process_track(session, track_id, quality_pref, download_dir, details):
    bitrate = QUALITY_MAP.get(quality_pref, "24bit")
    api_url = f"https://stm.genie.co.kr/player/j_StmInfo.json?uxtk=3173869132189.992&sign=Y&lpr=&svc=IV&bitrate={bitrate}&stk=Q3RoM0lJWUErZFdZVE1mREN2bi85UT09&itn=Y&dcd=ANDROID_ID%3A06568f5097d60690&xgnm={track_id}&uip=172.16.2.15&dvm=oppo%20r9tm&apvn=40607&ovn=5.1.1&unm=322011981&mts=Y"
    
    data = await fetch_json(session, api_url)
    try:
        track_data = data["DataSet"]["DATA"][0]
    except (KeyError, IndexError):
        raise Exception("Gagal mendapatkan data streaming untuk track ini.")

    stream_url = unquote(track_data["STREAMING_MP3_URL"])
    
    # --- FIX: Tambahkan unquote untuk membersihkan %28 dan %29 ---
    title = unquote(track_data.get("SONG_TTS", f"Track_{track_id}"))
    artist = unquote(track_data.get("ARTIST_NAME", "Unknown Artist"))
    album_name = unquote(track_data.get("ALBUM_NAME", "Unknown Album"))
    # -----------------------------------------------------------
    
    ext = "flac" if ".flac" in stream_url.lower() else "mp3"
    filename = f"{artist} - {title}.{ext}".replace("/", "_")
    filepath = os.path.join(download_dir, filename)

    metadata = {
        'title': title,
        'artist': artist,
        'album': album_name,
        'provider': 'Genie',
        'quality': quality_pref.upper(),
        'filepath': filepath,
        'type': 'track',
        'extension': ext
    }

    aria_details = details.copy() if details else {}
    aria_details['headers'] = HEADERS

    success = await aria2_download(stream_url, filepath, aria_details)
    if not success:
        raise Exception("Gagal mengunduh file melalui Aria2c.")
        
    return metadata

async def start_genie(link: str, user: dict):
    user_id = user['user_id']
    quality_pref = genie_manager.get_user_quality(user_id)
    download_dir = os.path.join(Config.DOWNLOAD_BASE_DIR, str(user['r_id']))
    os.makedirs(download_dir, exist_ok=True)
    
    try:
        code = parse_code(link)
    except ValueError as e:
        raise Exception(str(e))

    details = None
    if 'bot_msg' in user:
        import hashlib
        cancel_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
        details = {
            'msg': user['bot_msg'],
            'action': 'Download',
            'machine': 'Aria2c',
            'task_id': cancel_id
        }

    async with aiohttp.ClientSession() as session:
        # LOGIKA TRACK TUNGGAL
        if "xgnm" in link:
            if 'bot_msg' in user:
                await edit_message(user['bot_msg'], "🔍 **Fetching Genie Track...**")
            
            metadata = await process_track(session, code, quality_pref, download_dir, details)
            await track_upload(metadata, user)

                # LOGIKA ALBUM
        elif "axnm" in link:
            if 'bot_msg' in user:
                await edit_message(user['bot_msg'], "🔍 **Fetching Genie Album...**")
            
            # --- FIX: Ubah Label di Radar UI menjadi Download Album ---
            if details: 
                details['action'] = 'Download Album'
                
            api_url = f"https://info.genie.co.kr/info/album?axnm={code}"
            album_data = await fetch_json(session, api_url)
            
            # --- FIX: Bersihkan nama dari %28 dll ---
            album_name = unquote(album_data['album_info']['album_name'])
            album_artist = unquote(album_data['album_info']['artist_name'])
            
            album_dir_name = f"{album_artist} - {album_name}".replace("/", "_")
            album_dir = os.path.join(download_dir, album_dir_name)
            os.makedirs(album_dir, exist_ok=True)
            
            # --- FIX: Penanganan Cover Art Tanpa Protokol HTTP ---
            cover_url = unquote(album_data['album_info'].get("album_img_path600", ""))
            if cover_url.startswith("//"):
                cover_url = "https:" + cover_url
            
            cover_path = os.path.join(album_dir, "cover.jpg")
            if cover_url:
                # Eksekusi unduhan cover secara diam-diam (None) agar tidak menimpa status UI
                await aria2_download(cover_url, cover_path, None)
            # -----------------------------------------------------
            
            tracks_metadata = []
            song_list = album_data.get('album_song_list', [])
            
            for index, song in enumerate(song_list, start=1):
                track_id = song['song_id']
                if details: details['title'] = f"[{index}/{len(song_list)}] {unquote(song['song_name'])}"
                
                try:
                    meta = await process_track(session, track_id, quality_pref, album_dir, details)
                    tracks_metadata.append(meta)
                except Exception as e:
                    LOGGER.warning(f"Melewati Track ID {track_id}: {e}")

            if not tracks_metadata:
                raise Exception("Semua lagu dalam album gagal diunduh.")

            album_metadata = {
                'title': album_name,
                'artist': album_artist,
                'provider': 'Genie',
                'quality': quality_pref.upper(),
                'type': 'album',
                'folderpath': album_dir,
                'tracks': tracks_metadata,
                'cover': cover_path if os.path.exists(cover_path) else None
            }
            
            await album_upload(album_metadata, user)

        # LOGIKA PLAYLIST
        elif "plmSeq" in link:
            if 'bot_msg' in user:
                await edit_message(user['bot_msg'], "🔍 **Fetching Genie Playlist...**")
                
            api_url = f"https://app.genie.co.kr/Iv3/playlist/infosong.json?seq={code}"
            pl_data = await fetch_json(session, api_url)
            
            pl_title = unquote(pl_data['DATASET']['DATA_INFO']['DATA']['PLM_TITLE'])
            pl_dir_name = f"Genie - {pl_title}".replace("/", "_")
            pl_dir = os.path.join(download_dir, pl_dir_name)
            os.makedirs(pl_dir, exist_ok=True)
            
            tracks_metadata = []
            song_list = pl_data['DATASET']['DATA_SONG']['DATA']
            
            for index, song in enumerate(song_list, start=1):
                track_id = unquote(song['SONG_ID'])
                if details: details['title'] = f"[{index}/{len(song_list)}] {unquote(song['SONG_NAME'])}"
                
                try:
                    meta = await process_track(session, track_id, quality_pref, pl_dir, details)
                    tracks_metadata.append(meta)
                except Exception as e:
                    LOGGER.warning(f"Melewati Track ID {track_id} di Playlist: {e}")

            if not tracks_metadata:
                raise Exception("Semua lagu dalam playlist gagal diunduh.")

            pl_metadata = {
                'title': pl_title,
                'provider': 'Genie',
                'quality': quality_pref.upper(),
                'type': 'playlist',
                'folderpath': pl_dir,
                'tracks': tracks_metadata
            }
            
            # bot/helpers/uploder.py menggunakan fungsi album_upload dan playlist_upload secara terpisah
            from bot.helpers.uploder import playlist_upload
            await playlist_upload(pl_metadata, user)

        elif "xxnm" in link:
            raise NotImplementedError("Fitur unduhan Artist Batch untuk Genie belum diterapkan. Harap unduh per-Album.")
        else:
            raise Exception("URL Genie tidak valid atau tidak didukung.")
