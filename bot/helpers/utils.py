# [FILE: bot/helpers/utils.py]

import os
import math
import asyncio
import shutil
import zipfile
import typing
import requests
import re
import time 

from pathlib import Path
from urllib.parse import quote
from pyrogram.errors import MessageNotModified
from concurrent.futures import ThreadPoolExecutor
from pyrogram.errors import FloodWait

from config import Config
import bot.helpers.translations as lang

from ..logger import LOGGER
from ..settings import bot_set
from .buttons.links import links_button
from .message import send_message, edit_message

# Batas aman Telegram (1.9GB)
MAX_SIZE = 1.9 * 1024 * 1024 * 1024 

async def download_file(url, path, retries=3, timeout=30):
    """
    Mengunduh file menggunakan requests (sync) yang dibungkus to_thread
    untuk menghindari bug SSL shutdown pada aiohttp.
    """
    if not url: return "URL is empty"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    def _sync_download():
        with requests.Session() as s:
            with s.get(url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                with open(path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk: f.write(chunk)

    for attempt in range(1, retries + 1):
        try:
            await asyncio.to_thread(_sync_download)
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return None
            else:
                if attempt == retries: return f"Download finished but file is missing: {path}"
                await asyncio.sleep(1)
        except Exception as e:
            if attempt == retries: return str(e)
            await asyncio.sleep(1)

async def format_string(text:str, data:dict, user=None):
    def safe_get(key):
        val = data.get(key)
        if val is None: return ''
        return str(val)

    title = safe_get('title')
    album = safe_get('album')
    artist = safe_get('artist')
    albumartist = safe_get('albumartist')
    tracknumber = safe_get('tracknumber')
    date = safe_get('date') 
    release_date = safe_get('release_date') 
    release_date_fallback = release_date if release_date else date
    upc = safe_get('upc')
    isrc = safe_get('isrc')
    totaltracks = safe_get('totaltracks')
    volume = safe_get('volume')
    totalvolume = safe_get('totalvolumes') or safe_get('totalvolume')
    extension = safe_get('extension')
    duration = safe_get('duration')
    copyright = safe_get('copyright')
    genre = safe_get('genre')
    provider = (data.get('provider') or '').title()
    quality = safe_get('quality')
    explicit = safe_get('explicit') 
    
    text = text.replace(R'{title}', title).replace(R'{album}', album).replace(R'{artist}', artist)
    text = text.replace(R'{albumartist}', albumartist).replace(R'{tracknumber}', tracknumber)
    text = text.replace(R'{date}', date).replace(R'{release_date}', release_date_fallback)
    text = text.replace(R'{upc}', upc).replace(R'{isrc}', isrc).replace(R'{totaltracks}', totaltracks)
    text = text.replace(R'{volume}', volume).replace(R'{totalvolume}', totalvolume)
    text = text.replace(R'{extension}', extension).replace(R'{duration}', duration)
    text = text.replace(R'{copyright}', copyright).replace(R'{genre}', genre)
    text = text.replace(R'{provider}', provider).replace(R'{quality}', quality)
    text = text.replace(R'{explicit}', explicit)

    if user:
        text = text.replace(R'{user}', user.get('name') or '').replace(R'{username}', user.get('user_name') or '')
    return text

async def run_concurrent_tasks(tasks: list, update_details: dict, limit: int = 100):
    sem = asyncio.Semaphore(limit)
    total_tasks = len(tasks)
    completed_tasks = 0
    results = []

    async def run_with_sem(task):
        nonlocal completed_tasks
        result = None 
        try:
            async with sem:
                result = await task
        except Exception: result = None
        completed_tasks += 1
        
        if update_details:
            try:
                if completed_tasks % 5 == 0 or completed_tasks == total_tasks: 
                    progress_bar = "{0}{1}".format(
                        ''.join(["▰" for _ in range(math.floor((completed_tasks/total_tasks) * 10))]),
                        ''.join(["▱" for _ in range(10 - math.floor((completed_tasks/total_tasks) * 10))])
                    )
                    text_to_send = update_details['text'].format(
                        progress_bar, completed_tasks, total_tasks,
                        update_details['title'], update_details['type'].title()
                    )
                    await edit_message(update_details['msg'], text_to_send, None, False)
            except: pass
        return result

    wrapped_tasks = [run_with_sem(task) for task in tasks]
    results = await asyncio.gather(*wrapped_tasks)
    return results

async def create_link(path, basepath):
    if isinstance(path, list): path = Path(path[0]).parent
    path = str(Path(path).relative_to(basepath))
    rclone_link, index_link = None, None

    if bot_set.link_options == 'RCLONE' or bot_set.link_options=='Both':
        cmd = f'rclone link --config ./rclone.conf "{Config.RCLONE_DEST}/{path}"'
        task = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await task.communicate()
        if task.returncode == 0: rclone_link = stdout.decode().strip()
            
    if bot_set.link_options == 'Index' or bot_set.link_options=='Both':
        if Config.INDEX_LINK: index_link =  Config.INDEX_LINK + '/' + quote(path)

    return rclone_link, index_link

async def zip_handler(folderpath):
    loop = asyncio.get_running_loop()
    user_mode = bot_set.upload_mode
    try:
        parts = folderpath.split(os.sep)
        for part in parts:
            if part.isdigit() and len(part) > 5:
                u_id = int(part)
                u_data = bot_set.user_data.get(u_id, {})
                if u_data.get('upload_mode'):
                    user_mode = u_data['upload_mode']
                break
    except: pass

    if user_mode == 'Telegram':
        LOGGER.info(f"[ZIP] Mode Telegram: Menggunakan Split Zip (.zip, .part2.zip)")
        with ThreadPoolExecutor() as pool:
            zips = await loop.run_in_executor(pool, split_zip_folder, folderpath)
        return zips
    else:
        LOGGER.info(f"[ZIP] Mode {user_mode}: Menggunakan System Zip (Single File Utuh)")
        zip_file = await create_zip_system(folderpath)
        return zip_file

async def create_zip_system(folderpath):
    zip_path = f"{folderpath}.zip"
    if os.path.exists(zip_path): 
        try: os.remove(zip_path)
        except: pass
    cmd = ["zip", "-r", "-0", zip_path, "."]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd, cwd=folderpath,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        if process.returncode == 0: return zip_path
        else:
            with ThreadPoolExecutor() as pool:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(pool, zip_folder, folderpath)
    except:
        with ThreadPoolExecutor() as pool:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(pool, zip_folder, folderpath)

def split_zip_folder(folderpath) -> list:
    zip_paths = []
    part_num = 1
    current_size = 0
    current_files = []

    def add_to_zip(zip_name, files_to_add):
        nonlocal part_num
        if part_num == 1:
            zip_path = f"{zip_name}.zip"
        else:
            zip_path = f"{zip_name}.part{part_num}.zip"

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zipf:
            for file_path, arcname in files_to_add:
                zipf.write(file_path, arcname)
        return zip_path

    for root, dirs, files in os.walk(folderpath):
        for file in files:
            file_path = os.path.join(root, file)
            file_size = os.path.getsize(file_path)
            arcname = os.path.relpath(file_path, folderpath)

            if current_size + file_size > MAX_SIZE:
                zip_paths.append(add_to_zip(folderpath, current_files))
                part_num += 1
                current_files = []
                current_size = 0

            current_files.append((file_path, arcname))
            current_size += file_size

    if current_files:
        zip_paths.append(add_to_zip(folderpath, current_files))

    return zip_paths

def zip_folder(folderpath) -> str:
    zip_path = f"{folderpath}.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED, allowZip64=True) as zipf:
        for root, dirs, files in os.walk(folderpath):
            for file in files:
                file_path = os.path.join(root, file)
                zipf.write(file_path, os.path.relpath(file_path, folderpath))
    return zip_path

async def move_sorted_playlist(metadata, user) -> str:
    def _sync_move():
        source_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{metadata['provider']}"
        destination_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{metadata['provider']}/{metadata['title']}"
        os.makedirs(destination_folder, exist_ok=True)
        folders = [os.path.join(source_folder, name) for name in os.listdir(source_folder) if os.path.isdir(os.path.join(source_folder, name))]
        for folder in folders: 
            shutil.move(folder, destination_folder)
        return destination_folder

    # Jalankan di thread terpisah agar tidak lag
    return await asyncio.to_thread(_sync_move)

# --- [PERBAIKAN UTAMA: LOGIKA DOWNLOAD POSTER] ---
async def post_art_poster(user:dict, meta:dict):
    photo = meta.get('cover')
    if not photo: return None

    # Tentukan caption
    if meta['type'] == 'album': caption = await format_string(lang.s.ALBUM_TEMPLATE, meta, user)
    elif meta['type'] == 'artist': caption = await format_string(lang.s.ARTIST_TEMPLATE, meta, user)
    else: caption = await format_string(lang.s.PLAYLIST_TEMPLATE, meta, user)
    
    _, __, ___, art_poster = fetch_zip_settings(user)
    if art_poster:
        # Cek apakah photo adalah URL
        temp_thumb = None
        if isinstance(photo, str) and photo.startswith('http'):
            temp_thumb = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-poster.jpg"
            # Download manual pakai requests (bypass aiohttp Pyrogram)
            err = await download_file(photo, temp_thumb)
            if not err:
                photo = temp_thumb # Gunakan path lokal
        
        try:
            msg = await send_message(user, photo, 'pic', caption)
        except Exception as e:
            LOGGER.error(f"Failed to send poster: {e}")
            msg = None
        
        # Hapus file temp
        if temp_thumb and os.path.exists(temp_thumb):
            try: os.remove(temp_thumb)
            except: pass
            
        return msg
# ------------------------------------------------

async def create_simple_text(meta, user):
    name = meta.get('title', 'N/A')
    type_ = meta.get('type', 'N/A').title()
    provider = meta.get('provider', 'N/A')
    quality = meta.get('quality', 'N/A')
    return f"NAME : {name}\nTYPE : {type_}\nPROVIDER : {provider}\nQUALITY : {quality}"

async def edit_art_poster(metadata, user, r_link, i_link, caption):
    markup = links_button(r_link, i_link)
    await edit_message(metadata['poster_msg'], caption, markup)

async def post_simple_message(user, meta, r_link=None, i_link=None):
    caption = await create_simple_text(meta, user)
    markup = links_button(r_link, i_link)
    await send_message(user, caption, markup=markup)

async def progress_message(done, total, details):
    progress_bar = "{0}{1}".format(''.join(["▰" for i in range(math.floor((done/total) * 10))]), ''.join(["▱" for i in range(10 - math.floor((done/total) * 10))]))
    try: await edit_message(details['msg'], details['text'].format(progress_bar, done, total, details['title'], details['type'].title()), None, False)
    except FloodWait: pass

async def cleanup(user=None, metadata=None, user_dict: dict=None):
    def _sync_cleanup():
        if metadata:
            try:
                folder_path = metadata.get('folderpath')
                if isinstance(folder_path, str) and os.path.isdir(folder_path): 
                    shutil.rmtree(folder_path)
                elif isinstance(folder_path, list):
                    for i in folder_path: 
                        if os.path.exists(i): os.remove(i)
                if metadata.get('zip_path'):
                    zip_files = metadata['zip_path']
                    if isinstance(zip_files, str): zip_files = [zip_files]
                    for zp in zip_files: 
                        if os.path.exists(zp): os.remove(zp)
            except: pass
        if user:
            try: shutil.rmtree(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/")
            except: pass
            try: shutil.rmtree(f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/")
            except: pass

    # Jalankan cleanup di thread background
    await asyncio.to_thread(_sync_cleanup)

def fetch_zip_settings(users: typing.Dict) -> typing.Tuple[bool, bool, bool, bool]:
    user_dict = bot_set.user_data.get(users.get("user_id", 0), {})
    return (user_dict.get("playlist_zip", bot_set.playlist_zip),
            user_dict.get("album_zip", bot_set.album_zip),
            user_dict.get("artist_zip", bot_set.artist_zip),
            user_dict.get("art_poster", bot_set.art_poster))
