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

from bot.helpers.utils import get_readable_file_size, get_readable_time
from bot.helpers.aria2_helper import get_aria2_global_stat

BOT_START_TIME = time.time()

GLOBAL_CANCEL_DICT = set()
GLOBAL_TASKS = {}
GLOBAL_UI_MSG = {}
GLOBAL_UI_PAGES = {}
GLOBAL_UI_LAST_UPDATE = {}
GLOBAL_UI_LAST_TEXT = {}
GLOBAL_FLOOD_UNTIL = 0.0
GLOBAL_STATE_LOCK = asyncio.Lock()

def _get_system_stats() -> dict:
    try:
        cpu_usage = psutil.cpu_percent(interval=None)
        ram_usage = psutil.virtual_memory().percent
    except ImportError:
        cpu_usage = ram_usage = 0.0

    # Kalkulasi Penyimpanan Server
    total, used, free = shutil.disk_usage(Config.DOWNLOAD_BASE_DIR)
    free_storage = free / (1024 ** 3)
    disk_percent = (used / total) * 100 if total > 0 else 0
    disk_total_str = f"{total / (1024 ** 3):.1f} GiB"

    # Kalkulasi Lalu Lintas Jaringan (Network IO)
    try:
        net_io = psutil.net_io_counters()
        dl_gb = net_io.bytes_recv / (1024 ** 3)
        up_gb = net_io.bytes_sent / (1024 ** 3)
        net_dl = f"{dl_gb:.1f} GiB" if dl_gb >= 0.1 else f"{net_io.bytes_recv / (1024**2):.1f} MiB"
        net_up = f"{up_gb:.1f} GiB" if up_gb >= 0.1 else f"{net_io.bytes_sent / (1024**2):.1f} MiB"
    except Exception:
        net_dl = "0 GiB"
        net_up = "0 GiB"

    uptime_seconds = int(time.time() - BOT_START_TIME)
    h, rem = divmod(uptime_seconds, 3600)
    m, s = divmod(rem, 60)
    
    return {
        'cpu': cpu_usage,
        'ram': ram_usage,
        'free_storage': free_storage,
        'disk_percent': disk_percent,
        'disk_total': disk_total_str,
        'net_dl': net_dl,
        'net_up': net_up,
        'uptime': f"{h}h {m}m {s}s"
    }

async def get_status_text(page=1, limit=5):
    current_time = time.time()
    
    async with GLOBAL_STATE_LOCK:
        stale = []
        for k, v in list(GLOBAL_TASKS.items()):
            action = str(v.get('action', '')).lower()
            time_limit = 1800 if 'zipping' in action else 900 
                
            if current_time - v.get('timestamp', current_time) > time_limit:
                stale.append(k)
                
        for k in stale:
            GLOBAL_TASKS.pop(k, None)

        tasks = list(GLOBAL_TASKS.values())
        
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
    buttons = []
    
    import re
    for i, t in enumerate(tasks_page, start=start_idx + 1):
        # Trik Hyperlink agar HANYA teks Action & Type yang menjadi BIRU (Angka tetap putih)
        blue_text = f"[{t['action']} {t['type']}](https://t.me/{Config.BOT_USERNAME})"
        unique_short_id = t['cancel_id'][:6]
        user_id_val = str(t.get('user_id', 'Unknown'))
        
        # Trik Zero-Width Space (\u200B) untuk memblokir auto-link Telegram
        safe_title = str(t['title']).replace(".", ".\u200B").replace("://", "://\u200B").replace("/", "/\u200B")
        # Menyisipkan spasi tak terlihat di tengah deretan angka agar tidak dikira nomor telepon
        safe_title = re.sub(r'(\d{4,})', lambda m: m.group(1)[:2] + '\u200B' + m.group(1)[2:], safe_title)
        safe_user_id = user_id_val[:4] + "\u200B" + user_id_val[4:] if len(user_id_val) > 4 else user_id_val
        
        # Header Utama (Angka i:02d diletakkan di luar kurung biru)
        text += f"**{i:02d}. {blue_text}**: {safe_title}\n"
        text += f"**Since**: {t['since']}\n\n"
        
        # Blok Processed (Biru, Bold, Titik dua putih)
        blue_bot_processed = f"[Bot Processed](https://t.me/{Config.BOT_USERNAME})"
        text += f"┎ **{blue_bot_processed}**:\n"
        text += f"┠ **Progress** [{t['progress_bar']}] {t['percentage']}\n"
        text += f"┠ **{t['processed_label']}**: {t['processed']}\n"
        text += f"┠ **Current_Speed**: {t['speed']}\n"
        text += f"┠ **Machine_type**: {t['machine']}\n"
        text += f"┠ **Destination_mode**: {t['mode']}\n"
        text += f"┠ **User_ID**: {safe_user_id}\n"
        text += f"┖ **Cancel_ID**: {unique_short_id}\n"
        
        if i < (start_idx + len(tasks_page)) and i < total_tasks:
            text += "\n" # Spasi antar task

        buttons.append([
            InlineKeyboardButton(
                f"Cancel (ID: {unique_short_id})", 
                callback_data=f"cancel_{t['cancel_id']}", 
                style=ButtonStyle.DANGER
            )
        ])

    # Ambil kecepatan global Aria2c & Deezer cukup 1 kali saja di sini
    try:
        aria_stats = await get_aria2_global_stat()
        aria2_dl = int(aria_stats.get('downloadSpeed', 0)) if aria_stats else 0
        aria2_ul = int(aria_stats.get('uploadSpeed', 0)) if aria_stats else 0
    except Exception:
        aria2_dl = aria2_ul = 0

    try:
        from bot.helpers.deezer.dzapi import get_deezer_speed
        dz_spd = get_deezer_speed()
        if dz_spd > 0:
            aria2_dl += dz_spd
    except Exception:
        pass

    total_dl_raw = aria2_dl + sum(t.get('speed_dl_raw', 0) for t in tasks)
    total_ul_raw = aria2_ul + sum(t.get('speed_ul_raw', 0) for t in tasks)
        
    global_dl = f"{get_readable_file_size(total_dl_raw)}/s" if total_dl_raw > 0 else "0B/s"
    global_ul = f"{get_readable_file_size(total_ul_raw)}/s" if total_ul_raw > 0 else "0B/s"

    stats = _get_system_stats()
    
    # Blok Statistics (Biru, Bold, Titik dua putih)
    blue_stats = f"[Bot Statistics](https://t.me/{Config.BOT_USERNAME})"
    text += f"\n┎ **{blue_stats}**:\n"
    text += f"┠ **CPU**: {stats['cpu']:.1f}% | **FREE**: {stats['free_storage']:.2f} GB\n"
    text += f"┠ **RAM**: {stats['ram']:.1f}% | **UPTIME**: {stats['uptime']}\n"
    text += f"┠ **DISK**: {stats['disk_percent']:.0f}% | **OF**: {stats['disk_total']}\n"
    text += f"┠ **DL**: {stats['net_dl']}  | **UP**: {stats['net_up']}\n"
    text += f"┖ 🔻 {global_dl} | 🔺 {global_ul}\n"

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

async def progress_message(done, total, details):
    if not details or not details.get('msg'): return
    now = time.time()
    
    if 'last_updated' in details:
        # Tahan update jika belum berlalu 4 detik
        if now - details['last_updated'] < 4.0 and done < total:
            return
    details['last_updated'] = now

    if 'start_time' not in details:
        details['start_time'] = now
        
    diff = max(now - details['start_time'], 1)
    speed = done / diff
    percentage = (done / total) * 100 if total > 0 else 0
    
    # --- LOGIKA PROGRESS BAR 3 TAHAP (■, ▥, □) ---
    blocks = 12
    fill_val = (percentage / 100) * blocks
    filled_blocks = math.floor(fill_val)
    remainder = fill_val - filled_blocks
    
    progress_bar = ""
    for b in range(blocks):
        if b < filled_blocks:
            progress_bar += "■"
        elif b == filled_blocks and remainder > 0.05:
            progress_bar += "▥"
        else:
            progress_bar += "□"
    # ---------------------------------------------
    
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
    
    # Menangkap ID Pengguna Asli
    try:
        msg_obj = details['msg']
        user_id_val = msg_obj.chat.id
        dest_mode = bot_set.user_data.get(user_id_val, {}).get('upload_mode', bot_set.upload_mode)
    except Exception: 
        user_id_val = 0
        dest_mode = bot_set.upload_mode

    machine = details.get('machine', 'Aria2c 1.37.0')

    # Hanya catat speed_dl_raw jika bukan dari Aria2c (agar tidak terhitung ganda dengan aria2_dl global)
    speed_dl_raw = speed if (action.lower() == 'download' and 'aria2' not in machine.lower()) else 0
    speed_ul_raw = speed if action.lower() == 'upload' else 0

    async with GLOBAL_STATE_LOCK:
        if task_id not in GLOBAL_TASKS:
            GLOBAL_TASKS[task_id] = {}
            
        GLOBAL_TASKS[task_id].update({
            'action': action, 'type': task_type, 'title': title, 'since': since_str,
            'progress_bar': progress_bar, 'percentage': f"{percentage:.2f}%",
            'processed_label': progress_label, 'processed': f"{done_str} of {total_str}",
            'speed': speed_str, 'machine': machine, 'mode': dest_mode,
            'cancel_id': task_id, 'dl_speed': f"{get_readable_file_size(speed_dl_raw)}/s",
            'ul_speed': f"{get_readable_file_size(speed_ul_raw)}/s", 'speed_dl_raw': speed_dl_raw,
            'speed_ul_raw': speed_ul_raw, 'user_id': user_id_val, 'timestamp': now
        })

async def dedicated_ui_worker():
    from bot.helpers.message import edit_message
    from bot.helpers.database.mongo_async import database
    global GLOBAL_FLOOD_UNTIL
    last_memory_sweep = time.time()

    while True:
        await asyncio.sleep(7.0)  # Naikkan dari 5.0 ke 7.0 detik agar aman dari rate-limit
        now = time.time()

        # Circuit Breaker: Jangan lakukan edit apa pun jika sedang masa penalti FloodWait
        if now < GLOBAL_FLOOD_UNTIL:
            continue

        if now - last_memory_sweep > 60:
            last_memory_sweep = now
            async with GLOBAL_STATE_LOCK:
                stale_tasks = []
                for k, v in list(GLOBAL_TASKS.items()):
                    action = str(v.get('action', '')).lower()
                    time_limit = 1800 if 'zipping' in action else 900
                    if now - v.get('timestamp', now) > time_limit:
                        stale_tasks.append(k)

                for k in stale_tasks:
                    GLOBAL_TASKS.pop(k, None)
                    GLOBAL_CANCEL_DICT.discard(k)

                stale_pages = [cid for cid in GLOBAL_UI_PAGES if cid not in GLOBAL_UI_MSG]
                for cid in stale_pages:
                    GLOBAL_UI_PAGES.pop(cid, None)
                    GLOBAL_UI_LAST_TEXT.pop(cid, None)

        if not GLOBAL_UI_MSG:
            continue

        has_tasks = bool(GLOBAL_TASKS)
        targets = list(GLOBAL_UI_MSG.items())

        for chat_id, msg in targets:
            if time.time() < GLOBAL_FLOOD_UNTIL:
                break
            try:
                page = GLOBAL_UI_PAGES.get(chat_id, 1)
                g_text, g_markup = await get_status_text(page=page)

                # Cegah pengiriman RPC ke Telegram jika isi teks sama persis
                if GLOBAL_UI_LAST_TEXT.get(chat_id) == g_text:
                    # Jika sudah tidak ada task aktif, cabut dari radar agar tidak terus dipolling
                    if not has_tasks:
                        GLOBAL_UI_MSG.pop(chat_id, None)
                        GLOBAL_UI_PAGES.pop(chat_id, None)
                        GLOBAL_UI_LAST_TEXT.pop(chat_id, None)
                        await database.remove_ui_state(chat_id)
                    continue

                edited = await edit_message(msg, g_text, g_markup, antiflood=False)
                if edited is not None:
                    GLOBAL_UI_LAST_TEXT[chat_id] = g_text

                # Jika baru saja berubah menjadi idle (tidak ada task), hentikan polling untuk chat ini
                if not has_tasks and (edited is not None or chat_id not in GLOBAL_UI_MSG):
                    GLOBAL_UI_MSG.pop(chat_id, None)
                    GLOBAL_UI_PAGES.pop(chat_id, None)
                    GLOBAL_UI_LAST_TEXT.pop(chat_id, None)
                    await database.remove_ui_state(chat_id)

                await asyncio.sleep(0.3)
            except Exception:
                pass
