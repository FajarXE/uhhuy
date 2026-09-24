# [GANTI TOTAL ISI FILE: bot/helpers/ui_manager.py]

import time
import math
import random
import asyncio
import psutil
import shutil
import hashlib

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.enums import ButtonStyle

from config import Config
from bot.settings import bot_set
from bot.logger import LOGGER

# Import aman karena utils.py tidak lagi mengimpor balik file ini di top-level
from bot.helpers.utils import get_readable_file_size, get_readable_time
from bot.helpers.aria2_helper import get_aria2_global_stat

BOT_START_TIME = time.time()

# --- STATE GLOBAL UI & TASKS ---
GLOBAL_CANCEL_DICT = set()
GLOBAL_TASKS = {}
GLOBAL_UI_MSG = {}
GLOBAL_UI_PAGES = {}
GLOBAL_UI_LAST_UPDATE = {}
GLOBAL_STATE_LOCK = asyncio.Lock()
# -------------------------------

async def get_status_text(page=1, limit=5):
    current_time = time.time()
    
    # --- [FIX] AMANKAN PEMBACAAN DENGAN LOCK ---
    async with GLOBAL_STATE_LOCK:
        stale = []
        for k, v in list(GLOBAL_TASKS.items()):
            action = str(v.get('action', '')).lower()
            time_limit = 900 if 'zipping' in action else 120 
                
            if current_time - v.get('timestamp', current_time) > time_limit:
                stale.append(k)
                
        for k in stale:
            GLOBAL_TASKS.pop(k, None)

        tasks = list(GLOBAL_TASKS.values())
    # -------------------------------------------
        
    if not tasks:
        return "💤 **There are no tasks currently running.**", None

    total_tasks = len(tasks)
    max_pages = (total_tasks + limit - 1) // limit
    if page > max_pages: page = max_pages
    if page < 1: page = 1

    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    tasks_page = tasks[start_idx:end_idx]

    text = ""
    for i, t in enumerate(tasks_page, start=start_idx + 1):
        # Blok Header Task
        text += f"┎ **{i:02d}. {t['action']} {t['type']}**: `{t['title']}`\n"
        text += f"┖ **Since**: {t['since']}\n\n"
        
        # Blok Detail Progress
        text += f"┎ **Progress**: `[{t['progress_bar']}]` {t['percentage']}\n"
        text += f"┠ **{t['processed_label']}**: {t['processed']}\n"
        text += f"┠ **Current_Speed**: {t['speed']}\n"
        text += f"┠ **Machine_type**: {t['machine']}\n"
        text += f"┠ **Destination_mode**: {t['mode']}\n"
        text += f"┠ **User_ID**: `{t.get('user_id', 'Unknown')}`\n"
        text += f"┖ **Cancel**: `/cancel_{t['cancel_id']}`\n"
        
        if i < (start_idx + len(tasks_page)) and i < total_tasks:
            text += "\n" # Spasi antar task

    total_dl_raw = sum(t.get('speed_dl_raw', 0) for t in tasks)
    total_ul_raw = sum(t.get('speed_ul_raw', 0) for t in tasks)
        
    global_dl = f"{get_readable_file_size(total_dl_raw)}/s" if total_dl_raw > 0 else "0B/s"
    global_ul = f"{get_readable_file_size(total_ul_raw)}/s" if total_ul_raw > 0 else "0B/s"
        
    try:
        cpu_usage = psutil.cpu_percent(interval=None)
        ram_usage = psutil.virtual_memory().percent
    except ImportError:
        cpu_usage = ram_usage = 0.0

    total, used, free = shutil.disk_usage(Config.DOWNLOAD_BASE_DIR)
    free_storage = free / (1024 ** 3)

    uptime_seconds = int(time.time() - BOT_START_TIME)
    h, rem = divmod(uptime_seconds, 3600)
    m, s = divmod(rem, 60)

    # Blok System Stats dengan border
    text += f"\n┎ **CPU**: {cpu_usage:.1f}% | **FREE**: {free_storage:.2f} GB\n"
    text += f"┠ **RAM**: {ram_usage:.1f}% | **UPTIME**: {h}h {m}m {s}s\n"
    text += f"┖ 🔻 {global_dl} | 🔺 {global_ul}\n"

    buttons = []
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"status_page_{page-1}", style=ButtonStyle.PRIMARY))
    if page < max_pages:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"status_page_{page+1}", style=ButtonStyle.PRIMARY))

    if nav_row: buttons.append(nav_row)
    buttons.append([
        InlineKeyboardButton("♻️ Refresh", callback_data=f"status_refresh_{page}", style=ButtonStyle.SUCCESS),
        InlineKeyboardButton("❌ Close", callback_data="status_close", style=ButtonStyle.DANGER)
    ])     

    return text, InlineKeyboardMarkup(buttons)


async def progress_message(done, total, details):
    if not details or not details.get('msg'): return
    
    now = time.time()
    
    # Jeda internal kalkulasi agar tidak boros CPU
    if 'last_updated' in details:
        if now - details['last_updated'] < 1.0 and done < total:
            return
    details['last_updated'] = now

    if 'start_time' not in details:
        details['start_time'] = now
        
    diff = max(now - details['start_time'], 1)
        
    speed = done / diff
    percentage = (done / total) * 100 if total > 0 else 0
    
    filled_blocks = math.floor((percentage / 100) * 12)
    empty_blocks = 12 - filled_blocks
    progress_bar = "■" * filled_blocks + "□" * empty_blocks
    
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
    
    if task_type.lower() == action.lower() or task_type == 'Download':
        task_type = 'Track'
    
    task_id = hashlib.md5(str(details['msg'].id).encode()).hexdigest()[:16] if details.get('msg') else details.get('task_id', 'unknown')
    
    try:
        user_id = details['msg'].chat.id
        dest_mode = bot_set.user_data.get(user_id, {}).get('upload_mode', bot_set.upload_mode)
    except: dest_mode = bot_set.upload_mode
        
    try:
        stats = await get_aria2_global_stat()
        speed_dl = int(stats.get('downloadSpeed', 0)) if stats else 0
        speed_ul = int(stats.get('uploadSpeed', 0)) if stats else 0
    except: speed_dl = speed_ul = 0

    machine = details.get('machine', 'Aria2c 1.37.0')

    if action.lower() == 'upload': speed_ul += speed
    elif action.lower() == 'download' and machine == 'Telegram API': speed_dl += speed

    # --- [FIX] UPDATE DICTIONARY DALAM LOCK MEMORI ---
    # Ini mencegah alokasi memori berulang kali dan mengatasi CPU Overhead
    async with GLOBAL_STATE_LOCK:
        if task_id not in GLOBAL_TASKS:
            GLOBAL_TASKS[task_id] = {}
            
        GLOBAL_TASKS[task_id].update({
            'action': action, 'type': task_type, 'title': title, 'since': since_str,
            'progress_bar': progress_bar, 'percentage': f"{percentage:.2f}%",
            'processed_label': progress_label, 'processed': f"{done_str} of {total_str}",
            'speed': speed_str, 'machine': machine, 'mode': dest_mode,
            'cancel_id': task_id, 'dl_speed': f"{get_readable_file_size(speed_dl)}/s",
            'ul_speed': f"{get_readable_file_size(speed_ul)}/s", 'speed_dl_raw': speed_dl,
            'speed_ul_raw': speed_ul, 'user_id': details['msg'].chat.id if details.get('msg') else 0,
            'timestamp': now
        })
    # ------------------------------------------------


async def dedicated_ui_worker():
    """ Mandor UI (Daemon) yang berputar di latar belakang """
    from bot.helpers.message import edit_message
    
    last_memory_sweep = time.time()

    while True:
        await asyncio.sleep(2.5)
        
        now = time.time()
        
        # --- [GARBAGE COLLECTOR OTONOM] ---
        # Membersihkan RAM setiap 60 detik tanpa menunggu interaksi pengguna
        if now - last_memory_sweep > 60:
            last_memory_sweep = now
            async with GLOBAL_STATE_LOCK:
                stale_tasks = []
                for k, v in list(GLOBAL_TASKS.items()):
                    action = str(v.get('action', '')).lower()
                    time_limit = 900 if 'zipping' in action else 120 
                    
                    if now - v.get('timestamp', now) > time_limit:
                        stale_tasks.append(k)
                
                for k in stale_tasks:
                    GLOBAL_TASKS.pop(k, None)
                    GLOBAL_CANCEL_DICT.discard(k) # Bersihkan juga ID Cancel agar RAM tidak bocor
                
                # Bersihkan memori paginasi (halaman) yang ditinggalkan
                stale_pages = [cid for cid in GLOBAL_UI_PAGES if cid not in GLOBAL_UI_MSG]
                for cid in stale_pages:
                    GLOBAL_UI_PAGES.pop(cid, None)
        # ----------------------------------

        if not GLOBAL_UI_MSG: continue

        targets = list(GLOBAL_UI_MSG.items()) 
        for chat_id, msg in targets:
            try:
                page = GLOBAL_UI_PAGES.get(chat_id, 1)
                g_text, g_markup = await get_status_text(page=page)
                
                await edit_message(msg, g_text, g_markup, antiflood=False)
                await asyncio.sleep(0.15) # Rem API Telegram
            except Exception: pass
