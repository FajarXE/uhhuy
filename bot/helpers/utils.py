# [GANTI TOTAL ISI FILE: bot/helpers/utils.py]

import os
import math
import asyncio
import shutil
import zipfile
import typing
import requests
import re
import time 
import aiohttp 

from pathlib import Path
from urllib.parse import quote
from pyrogram.errors import MessageNotModified
from concurrent.futures import ProcessPoolExecutor
from pyrogram.errors import FloodWait

from config import Config
import bot.helpers.translations as lang

from ..logger import LOGGER
from ..settings import bot_set
from .buttons.links import links_button
from .message import send_message, edit_message
from .aria2_helper import aria2_download

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.enums import ButtonStyle

BOT_START_TIME = time.time()
MAX_SIZE = 1.9 * 1024 * 1024 * 1024 


async def download_file(url, path, retries=3, timeout=30, details=None):
    if not url: return "URL is empty"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    for attempt in range(1, retries + 1):
        try:
            from .aria2_helper import aria2_download
            success = await aria2_download(url, path, details)
            
            if success and os.path.exists(path) and os.path.getsize(path) > 0:
                return None 
            else:
                LOGGER.warning(f"Aria2 attempt {attempt} gagal/dibatalkan...")
                
                try:
                    if os.path.exists(path): os.remove(path)
                    if os.path.exists(f"{path}.aria2"): os.remove(f"{path}.aria2")
                except Exception as e:
                    LOGGER.debug(f"Gagal menghapus file sisa Aria2 '{path}': {e}")
                
        except asyncio.TimeoutError:
            LOGGER.warning(f"Download Timeout pada percobaan {attempt}")
        except aiohttp.ClientError as e:
            LOGGER.warning(f"Download Network Error pada percobaan {attempt}: {e}")
        except Exception as e:
            LOGGER.error(f"Download Error Umum: {e}")
            
        if attempt == retries: 
            return f"Gagal mengunduh file setelah {retries} percobaan."
            
        await asyncio.sleep(2)
        
    return "Failed"


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


async def run_concurrent_tasks(tasks: list, update_details: dict, limit: int = 20):
    import asyncio
    import hashlib
    import time
    import math
    from bot.settings import bot_set
    from .utils import get_readable_file_size, get_readable_time
    
    from bot.helpers.ui_manager import GLOBAL_CANCEL_DICT, GLOBAL_TASKS, GLOBAL_STATE_LOCK

    sem = asyncio.Semaphore(limit)
    total_tasks = len(tasks)
    completed_tasks = 0
    is_running = True

    start_time = time.time()
    
    if update_details and update_details.get('msg'):
        batch_id = hashlib.md5(str(update_details['msg'].id).encode()).hexdigest()[:16]
    else:
        batch_id = "unknown_batch"
    
    async def run_with_sem(task):
        nonlocal completed_tasks
        if batch_id in GLOBAL_CANCEL_DICT:
            if hasattr(task, 'close'): task.close() 
            return None
        try:
            async with sem:
                if batch_id in GLOBAL_CANCEL_DICT:
                    if hasattr(task, 'close'): task.close()
                    return None
                res = await asyncio.wait_for(task, timeout=600.0)
        except asyncio.TimeoutError:
            LOGGER.warning("⚠️ 1 Lagu dilewati karena macet (Timeout > 10 Menit). Playlist dilanjutkan.")
            res = None
        except Exception as e:
            res = e
            
        completed_tasks += 1
        return res

    pending_tasks = [asyncio.create_task(run_with_sem(task)) for task in tasks]

    async def live_updater():
        from .aria2_helper import get_aria2_global_stat
        import bot.helpers.ui_manager as ui_module 
        from bot.logger import LOGGER
        
        try:
            user_id = update_details['msg'].chat.id if update_details and update_details.get('msg') else 0
            dest_mode = bot_set.user_data.get(user_id, {}).get('upload_mode', bot_set.upload_mode) if user_id else bot_set.upload_mode
        except:
            dest_mode = bot_set.upload_mode
            
        try:
            while is_running:
                if batch_id in ui_module.GLOBAL_CANCEL_DICT:
                    for t in pending_tasks:
                        if not t.done():
                            t.cancel()
                    break 

                if update_details:
                    try:
                        stats = await get_aria2_global_stat()
                        speed_dl = int(stats.get('downloadSpeed', 0)) if stats else 0
                        speed_ul = int(stats.get('uploadSpeed', 0)) if stats else 0
                    except:
                        speed_dl = 0
                        speed_ul = 0
                        
                    percentage = (completed_tasks / total_tasks) * 100 if total_tasks > 0 else 0
                    filled_blocks = math.floor((percentage / 100) * 12)
                    empty_blocks = 12 - filled_blocks
                    progress_bar = "■" * filled_blocks + "□" * empty_blocks
                    
                    speed_str = f"{get_readable_file_size(speed_dl)}/s"
                    since_str = get_readable_time(int(time.time() - start_time))
                    
                    title = update_details.get('title', 'Unknown')
                    action = update_details.get('action', 'Download').capitalize()
                    task_type = update_details.get('type', 'Task').capitalize()

                async with ui_module.GLOBAL_STATE_LOCK:
                    ui_module.GLOBAL_TASKS[batch_id] = {
                        'action': action, 'type': task_type, 'title': title, 'since': since_str,
                        'progress_bar': progress_bar, 'percentage': f"{percentage:.2f}%",
                        'processed_label': "Processed_tasks", 'processed': f"{completed_tasks} of {total_tasks}",
                        'speed': speed_str, 'machine': "Aria2c 1.37.0", 'mode': dest_mode,
                        'cancel_id': batch_id, 'dl_speed': f"{get_readable_file_size(speed_dl)}/s",
                        'ul_speed': f"{get_readable_file_size(speed_ul)}/s", 'speed_dl_raw': speed_dl, 
                        'speed_ul_raw': speed_ul, 'user_id': user_id, 'timestamp': time.time()
                    }
                
                for _ in range(10): 
                    if not is_running or batch_id in ui_module.GLOBAL_CANCEL_DICT:
                        break
                    await asyncio.sleep(0.1)
                    
        except Exception as e:
            LOGGER.error(f"Live Updater CRASH: {e}") 

    updater_task = asyncio.create_task(live_updater())
    
    try:
        results = await asyncio.gather(*pending_tasks, return_exceptions=True)
    finally:
        is_running = False
        if not updater_task.done():
            updater_task.cancel()
    
    if batch_id in GLOBAL_CANCEL_DICT:
        from bot.helpers.message import edit_message
        if update_details and 'msg' in update_details:
            try: await edit_message(update_details['msg'], "🛑 **Proses Dibatalkan oleh Pengguna.**", None, False)
            except: pass
            
        async with GLOBAL_STATE_LOCK:
            GLOBAL_TASKS.pop(batch_id, None) 
        
        raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
        
    return results


async def create_link(path, basepath):
    from pathlib import Path
    from urllib.parse import quote
    
    if isinstance(path, list): path = Path(path[0]).parent
    path = str(Path(path).relative_to(basepath))
    rclone_link, index_link = None, None

    if bot_set.link_options == 'RCLONE' or bot_set.link_options == 'Both':
        target_dest = f"{Config.RCLONE_DEST}/{path}"
        
        task = await asyncio.create_subprocess_exec(
            "rclone", "link", "--config", "./rclone.conf", target_dest,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await task.communicate()
        if task.returncode == 0: 
            rclone_link = stdout.decode().strip()
            
    if bot_set.link_options == 'Index' or bot_set.link_options == 'Both':
        if Config.INDEX_LINK: 
            index_link = Config.INDEX_LINK + '/' + quote(path)

    return rclone_link, index_link


# --- [FIX] OPTIMASI NATIVE SYSTEM ZIP UNTUK SPLIT ---
async def zip_handler(folderpath):
    user_mode = bot_set.upload_mode
    try:
        parts = folderpath.split(os.sep)
        for part in parts:
            if part.isdigit() and len(part) > 5:
                u_id = int(part)
                u_data = bot_set.user_data.get(u_id, {})
                if not u_data:
                     u_data = bot_set.user_data.get(str(u_id), {})
                if u_data.get('upload_mode'):
                    user_mode = u_data['upload_mode']
                break
    except: pass

    if user_mode == 'Telegram':
        LOGGER.info(f"[ZIP] Mode Telegram: Menggunakan Native OS Split Zip (1900MB)")
        return await split_zip_system(folderpath)
    else:
        LOGGER.info(f"[ZIP] Mode {user_mode}: Menggunakan System Zip (Single File Utuh)")
        return await create_zip_system(folderpath)


async def split_zip_system(folderpath):
    zip_path = f"{folderpath}.zip"
    base_name = os.path.basename(folderpath)
    parent_dir = os.path.dirname(folderpath)
    
    # Bersihkan sisa zip part lama jika folder diulang
    for f in os.listdir(parent_dir):
        if f == f"{base_name}.zip" or (f.startswith(f"{base_name}.z") and f.replace(f"{base_name}.z", "").isdigit()):
            try: os.remove(os.path.join(parent_dir, f))
            except: pass
            
    # Menggunakan Native OS Zip (Jauh lebih ringan untuk CPU/RAM)
    cmd = ["zip", "-r", "-0", "-s", "1900m", zip_path, "."]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd, cwd=folderpath,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        
        # --- [PERBAIKAN: STREAM CONSUMER] ---
        # Membaca pipe secara asinkron lalu membuangnya untuk mencegah Buffer Penuh & Deadlock
        async def consume_stream(stream):
            while True:
                line = await stream.readline()
                if not line:
                    break

        await asyncio.gather(
            consume_stream(process.stdout),
            consume_stream(process.stderr),
            process.wait()
        )
        # ------------------------------------
        
        if process.returncode == 0:
            zip_files = []
            for f in os.listdir(parent_dir):
                if f == f"{base_name}.zip" or (f.startswith(f"{base_name}.z") and f.replace(f"{base_name}.z", "").isdigit()):
                    zip_files.append(os.path.join(parent_dir, f))
            
            # Sort agar .z01, .z02, ..., .zip terkirim berurutan
            zip_files.sort()
            return zip_files
        else:
            LOGGER.warning("System split zip gagal, fallback ke Python Zipfile.")
            return await asyncio.to_thread(split_zip_folder, folderpath)
    except Exception as e:
        LOGGER.error(f"Split zip system error: {e}")
        return await asyncio.to_thread(split_zip_folder, folderpath)


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
        
        # --- [PERBAIKAN: STREAM CONSUMER] ---
        async def consume_stream(stream):
            while True:
                line = await stream.readline()
                if not line:
                    break

        await asyncio.gather(
            consume_stream(process.stdout),
            consume_stream(process.stderr),
            process.wait()
        )
        # ------------------------------------
        
        if process.returncode == 0: return zip_path
        else:
            return await asyncio.to_thread(zip_folder, folderpath)
    except:
        return await asyncio.to_thread(zip_folder, folderpath)


def split_zip_folder(folderpath) -> list:
    """Fallback Python-based Split Zip jika Native OS Zip tidak tersedia"""
    zip_paths = []
    part_num = 1
    current_size = 0
    current_files = []

    def add_to_zip(zip_name, files_to_add):
        nonlocal part_num
        zip_path = f"{zip_name}.zip" if part_num == 1 else f"{zip_name}.part{part_num}.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zipf:
            for file_path, arcname in files_to_add:
                zipf.write(file_path, arcname)
        return zip_path

    def scan_dir_recursive(path):
        for entry in os.scandir(path):
            if entry.is_dir(follow_symlinks=False):
                yield from scan_dir_recursive(entry.path)
            elif entry.is_file(follow_symlinks=False):
                yield entry

    for entry in scan_dir_recursive(folderpath):
        file_path = entry.path
        file_size = entry.stat().st_size
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
        def scan_dir_recursive(path):
            for entry in os.scandir(path):
                if entry.is_dir(follow_symlinks=False):
                    yield from scan_dir_recursive(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    yield entry
                    
        for entry in scan_dir_recursive(folderpath):
            zipf.write(entry.path, os.path.relpath(entry.path, folderpath))
    return zip_path
# ----------------------------------------------------


async def move_sorted_playlist(metadata, user) -> str:
    def _sync_move():
        source_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{metadata['provider']}"
        destination_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{metadata['provider']}/{metadata['title']}"
        os.makedirs(destination_folder, exist_ok=True)
        folders = [os.path.join(source_folder, name) for name in os.listdir(source_folder) if os.path.isdir(os.path.join(source_folder, name))]
        for folder in folders: 
            shutil.move(folder, destination_folder)
        return destination_folder

    return await asyncio.to_thread(_sync_move)


def fetch_zip_settings(users: typing.Dict) -> typing.Tuple[bool, bool, bool, bool]:
    raw_id = users.get("user_id")
    if not raw_id: return (False, False, False, False)
        
    user_id = int(raw_id)
    mem_data = bot_set.user_data.get(user_id)
    if not mem_data: mem_data = bot_set.user_data.get(str(user_id), {})

    def check(key_base):
        if key_base.lower() in mem_data: return bool(mem_data[key_base.lower()])
        if key_base.upper() in mem_data: return bool(mem_data[key_base.upper()])
        if hasattr(bot_set, key_base.lower()): return bool(getattr(bot_set, key_base.lower()))
        return False

    return (check("playlist_zip"), check("album_zip"), check("artist_zip"), check("art_poster"))


async def post_art_poster(user:dict, meta:dict):
    photo = meta.get('cover')
    if not photo: return None

    if meta['type'] == 'album': caption = await format_string(lang.s.ALBUM_TEMPLATE, meta, user)
    elif meta['type'] == 'artist': caption = await format_string(lang.s.ARTIST_TEMPLATE, meta, user)
    else: caption = await format_string(lang.s.PLAYLIST_TEMPLATE, meta, user)
    
    _, __, ___, art_poster = fetch_zip_settings(user)
    if art_poster:
        temp_thumb = None
        if isinstance(photo, str) and photo.startswith('http'):
            temp_thumb = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-poster.jpg"
            err = await download_file(photo, temp_thumb)
            if not err: photo = temp_thumb 
        
        try: msg = await send_message(user, photo, 'pic', caption)
        except Exception as e:
            LOGGER.error(f"Failed to send poster: {e}")
            msg = None
        
        if temp_thumb and os.path.exists(temp_thumb):
            try: os.remove(temp_thumb)
            except: pass
            
        return msg
    return None


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


def get_readable_time(seconds: int) -> str:
    count = 0
    ping_time = ""
    time_list = []
    time_suffix_list = ["s", "m", "h", "d"]
    while count < 4:
        count += 1
        remainder, result = divmod(seconds, 60) if count < 3 else divmod(seconds, 24)
        if seconds == 0 and remainder == 0: break
        time_list.append(int(result))
        seconds = int(remainder)
    for x in range(len(time_list)):
        time_list[x] = str(time_list[x]) + time_suffix_list[x]
    if len(time_list) == 4: ping_time += time_list.pop() + ", "
    time_list.reverse()
    ping_time += ":".join(time_list)
    return ping_time if ping_time else "0s"


def get_readable_file_size(size_in_bytes) -> str:
    if not size_in_bytes: return "0B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if size_in_bytes < 1024.0: return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} YB"


async def cleanup(user=None, metadata=None, user_dict: dict=None):
    # Memindahkan jeda waktu ke ruang asinkron agar tidak memblokir thread pool
    await asyncio.sleep(0.5)
    
    def _sync_cleanup():
        if metadata:
            try:
                folder_path = metadata.get('folderpath')
                if isinstance(folder_path, str) and os.path.isdir(folder_path): 
                    shutil.rmtree(folder_path, ignore_errors=True)
                elif isinstance(folder_path, list):
                    for i in folder_path: 
                        if os.path.exists(i):
                            try: os.remove(i)
                            except OSError: pass
                if metadata.get('zip_path'):
                    zip_files = metadata['zip_path']
                    if isinstance(zip_files, str): zip_files = [zip_files]
                    for zp in zip_files: 
                        if os.path.exists(zp):
                            try: os.remove(zp)
                            except OSError: pass
            except Exception as e: 
                from bot.logger import LOGGER
                LOGGER.debug(f"Cleanup metadata error: {e}")
                
        if user:
            try: 
                target_dir = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/"
                if os.path.exists(target_dir): shutil.rmtree(target_dir, ignore_errors=True)
            except OSError as e: 
                from bot.logger import LOGGER
                LOGGER.debug(f"Cleanup user dir OSError: {e}")
                
            try: 
                temp_dir = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/"
                if os.path.exists(temp_dir): shutil.rmtree(temp_dir, ignore_errors=True)
            except OSError as e: 
                from bot.logger import LOGGER
                LOGGER.debug(f"Cleanup user temp dir OSError: {e}")

    await asyncio.to_thread(_sync_cleanup)
