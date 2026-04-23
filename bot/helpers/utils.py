# [FILE: bot/helpers/utils.py] - QUEUE REMOVED & ANTI-FLOODWAIT

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
from .aria2_helper import aria2_download

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.enums import ButtonStyle

BOT_START_TIME = time.time()

GLOBAL_CANCEL_DICT = set()
GLOBAL_TASKS = {}
GLOBAL_UI_MSG = {}
GLOBAL_UI_PAGES = {}

# PENGHAPUSAN: GLOBAL_TASK_LOCK dan GLOBAL_QUEUE_COUNT telah dihapus.

def get_status_text(page=1, limit=5):
    current_time = time.time()
    
    stale = []
    for k, v in list(GLOBAL_TASKS.items()):
        action = str(v.get('action', '')).lower()
        
        if 'zipping' in action or 'processing' in action or 'connecting' in action or 'fetching' in action:
            v['timestamp'] = current_time
            continue
            
        if current_time - v.get('timestamp', current_time) > 120:
            stale.append(k)
            
    for k in stale:
        GLOBAL_TASKS.pop(k, None)

    tasks = list(GLOBAL_TASKS.values())
    if not tasks:
        return "💤 **Tidak ada task yang sedang berjalan saat ini.**", None

    total_tasks = len(tasks)
    max_pages = (total_tasks + limit - 1) // limit
    if page > max_pages: page = max_pages
    if page < 1: page = 1

    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    tasks_page = tasks[start_idx:end_idx]

    # PENGHAPUSAN: Teks 📊 GLOBAL STATUS (Page 1/1) dihapus sesuai permintaan
    text = ""
    for i, t in enumerate(tasks_page, start=start_idx + 1):
        text += f"**{i:02d}. {t['action']} {t['type']}**: `{t['title']}`\n"
        text += f"**Since**: {t['since']}\n\n"
        text += f"**Progress**: `[{t['progress_bar']}]` {t['percentage']}\n"
        text += f"**{t['processed_label']}**: {t['processed']}\n"
        text += f"**Current_Speed**: {t['speed']}\n"
        text += f"**Machine_type**: {t['machine']}\n"
        text += f"**Destination_mode**: {t['mode']}\n"
        text += f"**User_ID**: `{t.get('user_id', 'Unknown')}`\n"
        text += f"**Cancel**: /cancel_{t['cancel_id']}\n"
        
        if i < (start_idx + len(tasks_page)) and i < total_tasks:
            text += "\n➖➖➖➖➖➖➖➖➖➖➖➖\n\n"

    total_dl_raw = 0
    total_ul_raw = 0
    
    for t in tasks:
        total_dl_raw += t.get('speed_dl_raw', 0)
        total_ul_raw += t.get('speed_ul_raw', 0)
        
    global_dl = f"{get_readable_file_size(total_dl_raw)}/s" if total_dl_raw > 0 else "0B/s"
    global_ul = f"{get_readable_file_size(total_ul_raw)}/s" if total_ul_raw > 0 else "0B/s"
        
    try:
        import psutil
        cpu_usage = psutil.cpu_percent(interval=None)
        ram_usage = psutil.virtual_memory().percent
    except ImportError:
        cpu_usage = 0.0
        ram_usage = 0.0

    import shutil
    total, used, free = shutil.disk_usage(Config.DOWNLOAD_BASE_DIR)
    free_storage = free / (1024 ** 3)

    uptime_seconds = int(time.time() - BOT_START_TIME)
    h, rem = divmod(uptime_seconds, 3600)
    m, s = divmod(rem, 60)

    text += f"\nCPU: {cpu_usage:.1f}% | FREE: {free_storage:.2f} GB\n"
    text += f"RAM: {ram_usage:.1f}% | UPTIME: {h}h {m}m {s}s\n"
    text += f"🔻 {global_dl} | 🔺 {global_ul}\n"

    buttons = []
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"status_page_{page-1}", style=ButtonStyle.PRIMARY))
    if page < max_pages:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"status_page_{page+1}", style=ButtonStyle.PRIMARY))

    if nav_row:
        buttons.append(nav_row)

    buttons.append([
        InlineKeyboardButton("♻️ Refresh", callback_data=f"status_refresh_{page}", style=ButtonStyle.SUCCESS),
        InlineKeyboardButton("❌ Close", callback_data="status_close", style=ButtonStyle.DANGER)
    ])     

    return text, InlineKeyboardMarkup(buttons)

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
        except Exception as e:
            LOGGER.error(f"Download gagal: {e}")
            
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

async def run_concurrent_tasks(tasks: list, update_details: dict, limit: int = 100):
    import asyncio
    import hashlib
    import time
    import math
    from bot.settings import bot_set
    from .message import edit_message
    from .utils import get_readable_file_size, get_readable_time, GLOBAL_CANCEL_DICT

    sem = asyncio.Semaphore(limit)
    total_tasks = len(tasks)
    completed_tasks = 0
    is_running = True

    start_time = time.time()
    
    if update_details and update_details.get('msg'):
        batch_id = hashlib.md5(str(update_details['msg'].id).encode()).hexdigest()[:16]
    
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
                res = await task
        except Exception:
            res = None
            
        completed_tasks += 1
        return res

    pending_tasks = [asyncio.create_task(run_with_sem(task)) for task in tasks]

    async def live_updater():
        from .aria2_helper import get_aria2_global_stat
        try:
            user_id = update_details['msg'].chat.id if update_details and update_details.get('msg') else 0
            dest_mode = bot_set.user_data.get(user_id, {}).get('upload_mode', bot_set.upload_mode) if user_id else bot_set.upload_mode
        except:
            dest_mode = bot_set.upload_mode
            
        while is_running:
            if batch_id in GLOBAL_CANCEL_DICT:
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
                
                text_to_send = f"**{action} {task_type}**: `{title}`\n"
                text_to_send += f"**Since**: {since_str}\n\n"
                text_to_send += f"**Progress**: `[{progress_bar}]` {percentage:.2f}%\n"
                text_to_send += f"**Processed_tasks**: {completed_tasks} of {total_tasks}\n"
                text_to_send += f"**Current_Speed**: {speed_str}\n"
                text_to_send += f"**Machine_type**: Aria2c 1.37.0\n"
                text_to_send += f"**Destination_mode**: {dest_mode}\n"
                text_to_send += f"**Cancel**: /cancel_{batch_id}\n\n"
                text_to_send += f"🔻 {get_readable_file_size(speed_dl)}/s | 🔺 {get_readable_file_size(speed_ul)}/s"

                GLOBAL_TASKS[batch_id] = {
                    'action': action,
                    'type': task_type,
                    'title': title,
                    'since': since_str,
                    'progress_bar': progress_bar,
                    'percentage': f"{percentage:.2f}%",
                    'processed_label': "Processed_tasks",
                    'processed': f"{completed_tasks} of {total_tasks}",
                    'speed': speed_str,
                    'machine': "Aria2c 1.37.0",
                    'mode': dest_mode,
                    'cancel_id': batch_id,
                    'dl_speed': f"{get_readable_file_size(speed_dl)}/s",
                    'ul_speed': f"{get_readable_file_size(speed_ul)}/s",
                    'speed_dl_raw': speed_dl, 
                    'speed_ul_raw': speed_ul, 
                    'user_id': update_details['msg'].chat.id if update_details and update_details.get('msg') else 0,
                    'timestamp': time.time()
                }
                
                try: 
                    from bot.helpers.utils import get_status_text, GLOBAL_UI_MSG, GLOBAL_UI_PAGES
                    
                    targets = {}
                    if update_details and update_details.get('msg'):
                        targets[update_details['msg'].chat.id] = update_details['msg']
                    
                    if GLOBAL_UI_MSG:
                        for cid, m in list(GLOBAL_UI_MSG.items()):
                            targets[cid] = m
                    
                    from bot.helpers.message import edit_message
                    
                    for cid, m in targets.items():
                        current_page = GLOBAL_UI_PAGES.get(cid, 1)
                        g_text, g_markup = get_status_text(page=current_page)
                        try: await edit_message(m, g_text, g_markup, False)
                        except: pass
                except: pass
            
            # ANTI-FLOODWAIT BATCH TASK: Diubah agar update lebih jarang tapi loop tetap responsif terhadap cancel
            for _ in range(100): # Naik jadi ~10.0 detik jeda UI Update
                if not is_running or batch_id in GLOBAL_CANCEL_DICT:
                    break
                await asyncio.sleep(0.1)

    updater_task = asyncio.create_task(live_updater())
    
    results = await asyncio.gather(*pending_tasks, return_exceptions=True)
    
    is_running = False
    await updater_task
    
    if batch_id in GLOBAL_CANCEL_DICT:
        if update_details and 'msg' in update_details:
            try: await edit_message(update_details['msg'], "🛑 **Proses Dibatalkan oleh Pengguna.**", None, False)
            except: pass
            
        import asyncio
        GLOBAL_TASKS.pop(batch_id, None) 
        raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
        
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
                if not u_data:
                     u_data = bot_set.user_data.get(str(u_id), {})
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

    return await asyncio.to_thread(_sync_move)

def fetch_zip_settings(users: typing.Dict) -> typing.Tuple[bool, bool, bool, bool]:
    raw_id = users.get("user_id")
    if not raw_id:
        return (False, False, False, False)
        
    user_id = int(raw_id)
    mem_data = bot_set.user_data.get(user_id)
    if not mem_data:
        mem_data = bot_set.user_data.get(str(user_id), {})

    def check(key_base):
        if key_base.lower() in mem_data: return bool(mem_data[key_base.lower()])
        if key_base.upper() in mem_data: return bool(mem_data[key_base.upper()])
        if hasattr(bot_set, key_base.lower()): return bool(getattr(bot_set, key_base.lower()))
        return False

    pl_zip = check("playlist_zip")
    al_zip = check("album_zip")
    ar_zip = check("artist_zip")
    poster = check("art_poster")

    return (pl_zip, al_zip, ar_zip, poster)

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
            if not err:
                photo = temp_thumb 
        
        try:
            msg = await send_message(user, photo, 'pic', caption)
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
        if seconds == 0 and remainder == 0:
            break
        time_list.append(int(result))
        seconds = int(remainder)
    for x in range(len(time_list)):
        time_list[x] = str(time_list[x]) + time_suffix_list[x]
    if len(time_list) == 4:
        ping_time += time_list.pop() + ", "
    time_list.reverse()
    ping_time += ":".join(time_list)
    return ping_time if ping_time else "0s"

def get_readable_file_size(size_in_bytes) -> str:
    if not size_in_bytes:
        return "0B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} YB"

async def progress_message(done, total, details):
    if not details or not details.get('msg'):
        return
    import time
    import math
    now = time.time()
    
    # ANTI FLOODWAIT: Edit delay minimum 10.0 detik
    if 'last_updated' in details:
        if now - details['last_updated'] < 10.0 and done < total:
            return
    details['last_updated'] = now

    if 'start_time' not in details:
        details['start_time'] = now
        
    diff = now - details['start_time']
    if diff < 1: diff = 1 
        
    speed = done / diff
    percentage = (done / total) * 100 if total > 0 else 0
    
    filled_blocks = math.floor((percentage / 100) * 12)
    empty_blocks = 12 - filled_blocks
    progress_bar = "■" * filled_blocks + "□" * empty_blocks
    
    from bot.helpers.utils import get_readable_file_size, get_readable_time
    if total > 1000:
        done_str = get_readable_file_size(done)
        total_str = get_readable_file_size(total)
        speed_str = f"{get_readable_file_size(speed)}/s"
        progress_label = "Processed_bytes"
    else: 
        done_str = str(done)
        total_str = str(total)
        speed_str = "0B/s"
        progress_label = "Processed_tasks"
        
    since_str = get_readable_time(int(diff))
    
    title = details.get('title', 'Unknown File')
    action = details.get('action', 'Download').capitalize()
    task_type = details.get('type', 'Task').capitalize()
    
    # --- [FIX TEKS KEMBAR] ---
    if task_type.lower() == action.lower() or task_type == 'Download':
        task_type = 'Track'
    # -------------------------
    
    if details and details.get('msg'):
        import hashlib
        task_id = hashlib.md5(str(details['msg'].id).encode()).hexdigest()[:16]
    else:
        task_id = details.get('task_id', 'unknown')
    
    from bot.settings import bot_set
    try:
        user_id = details['msg'].chat.id
        dest_mode = bot_set.user_data.get(user_id, {}).get('upload_mode', bot_set.upload_mode)
    except:
        dest_mode = bot_set.upload_mode
        
    from .aria2_helper import get_aria2_global_stat
    try:
        stats = await get_aria2_global_stat()
        speed_dl = int(stats.get('downloadSpeed', 0)) if stats else 0
        speed_ul = int(stats.get('uploadSpeed', 0)) if stats else 0
    except:
        speed_dl = 0
        speed_ul = 0

    machine = details.get('machine', 'Aria2c 1.37.0')

    if action.lower() == 'upload':
        speed_ul += speed
    elif action.lower() == 'download' and machine == 'Telegram API':
        speed_dl += speed

    from bot.helpers.utils import GLOBAL_TASKS
    GLOBAL_TASKS[task_id] = {
        'action': action,
        'type': task_type,
        'title': title,
        'since': since_str,
        'progress_bar': progress_bar,
        'percentage': f"{percentage:.2f}%",
        'processed_label': progress_label,
        'processed': f"{done_str} of {total_str}",
        'speed': speed_str,
        'machine': machine,
        'mode': dest_mode,
        'cancel_id': task_id,
        'dl_speed': f"{get_readable_file_size(speed_dl)}/s",
        'ul_speed': f"{get_readable_file_size(speed_ul)}/s",
        'speed_dl_raw': speed_dl,
        'speed_ul_raw': speed_ul,
        'user_id': details['msg'].chat.id if details and details.get('msg') else 0,
        'timestamp': now
    }
    
    from bot.helpers.utils import get_status_text, GLOBAL_UI_MSG, GLOBAL_UI_PAGES
    try: 
        targets = {}
        if details and details.get('msg'):
            targets[details['msg'].chat.id] = details['msg']
        
        if GLOBAL_UI_MSG:
            for cid, m in list(GLOBAL_UI_MSG.items()): 
                targets[cid] = m
                
        from bot.helpers.message import edit_message
        
        for cid, m in targets.items():
            current_page = GLOBAL_UI_PAGES.get(cid, 1) 
            g_text, g_markup = get_status_text(page=current_page)
            
            try: 
                await edit_message(m, g_text, g_markup, False)
            except: 
                pass
    except FloodWait: pass
    except MessageNotModified: pass
    except Exception: pass

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

    await asyncio.to_thread(_sync_cleanup)
