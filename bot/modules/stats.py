import os
import time
import sys
import shutil
import psutil
import platform
import subprocess
import asyncio
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from async_pymongo import AsyncClient
from config import Config
from bot.logger import LOGGER

# Simpan waktu start bot
BOT_START_TIME = time.time()

# --- HELPER FUNCTIONS ---

def get_readable_time(seconds: int) -> str:
    count = 0
    ping_time = ""
    time_list = []
    time_suffix_list = ["s", "m", "h", "days"]
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
    return ping_time

def sizeof_fmt(num, suffix='B'):
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(num) < 1024.0:
            return "%3.1f %s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f %s%s" % (num, 'Yi', suffix)

def make_progress_bar(percentage):
    filled = int(percentage / 100 * 12)
    bar = "◙" * filled + "◘" * (12 - filled)
    return f"[{bar}]"

# --- SYSTEM INFO HELPERS ---

def get_distro_name():
    try:
        return subprocess.check_output("cat /etc/*release | grep ^PRETTY_NAME | cut -d= -f2", shell=True).decode().strip().replace('"', '')
    except:
        return platform.system()

def get_cpu_model():
    try:
        command = "cat /proc/cpuinfo | grep 'model name' | uniq | cut -d: -f2"
        output = subprocess.check_output(command, shell=True).decode().strip()
        if not output:
             command_arm = "cat /proc/cpuinfo | grep 'Model' | uniq | cut -d: -f2"
             output = subprocess.check_output(command_arm, shell=True).decode().strip()
        return output if output else platform.processor()
    except:
        return "Unknown CPU"

def get_packages_count():
    try:
        return subprocess.check_output("dpkg -l | grep -c ^ii", shell=True).decode().strip()
    except:
        return "N/A"

def get_host_info():
    if os.environ.get("RENDER"):
        return "Render (Cloud Container)"
    try:
        if os.path.exists("/sys/devices/virtual/dmi/id/product_name"):
            with open("/sys/devices/virtual/dmi/id/product_name", "r") as f:
                return f.read().strip()
    except: pass
    return platform.node()

def get_real_timezone():
    try:
        if os.path.islink("/etc/localtime"):
            return os.readlink("/etc/localtime").replace("/usr/share/zoneinfo/", "")
        if os.path.exists("/etc/timezone"):
            with open("/etc/timezone", "r") as f:
                return f.read().strip()
        return subprocess.check_output("date +%Z", shell=True).decode().strip()
    except: pass
    return time.tzname[0]

# --- MONGODB HELPER (FIXED DATABASE NAME) ---
async def get_mongo_stats(client_bot=None):
    try:
        mongo_client = None
        
        # 1. Coba ambil koneksi dari bot utama (Priority)
        # Di async_pymongo bot Anda, strukturnya: bot.mongo.db (Client)
        # Kita coba akses client raw-nya
        if client_bot and hasattr(client_bot, 'mongodb'):
            # Mencoba menebak struktur attribute database di bot Anda
            # Biasanya client_bot.mongodb adalah instance class MongoDB di mongo_async.py
            # Dan di dalamnya ada self.db (yang merupakan AsyncClient)
            if hasattr(client_bot.mongodb, 'db'):
                mongo_client = client_bot.mongodb.db
        
        # 2. Fallback: Buka koneksi baru jika tidak ketemu
        should_close = False
        if not mongo_client:
            # LOGGER.info("Stats: Membuka koneksi Mongo baru (Fallback)...")
            mongo_client = AsyncClient(Config.DATABASE_URL)
            should_close = True
        
        # [PERBAIKAN UTAMA DI SINI]
        # Jangan pakai .get_database() tanpa argumen jika URL tidak ada nama DB.
        # Kita pakai Config.BOT_USERNAME sesuai dengan 'mongo_async.py'.
        db = mongo_client[Config.BOT_USERNAME]
        
        # 3. Jalankan command dengan TIMEOUT 5 detik
        stats = await asyncio.wait_for(db.command("dbstats"), timeout=5.0)
        
        cols = stats.get('collections', 0)
        docs = stats.get('objects', 0)
        size_bytes = stats.get('storageSize', 0) 
        size_mb = size_bytes / (1024 * 1024)
        
        # Tutup jika kita membuka koneksi baru
        if should_close:
            try: mongo_client.close()
            except: pass
            
        return cols, docs, size_mb
        
    except asyncio.TimeoutError:
        LOGGER.error("Mongo Stats Timeout: Database terlalu lama merespon.")
        return 0, 0, 0
    except Exception as e:
        LOGGER.error(f"Mongo Stats Error: {e}")
        return 0, 0, 0

# --- MAIN COMMAND ---

@Client.on_message(filters.command(["stats", "status"]))
async def stats_handler(client, message):
    msg = await message.reply("🔄 **Mengumpulkan Data...**", quote=True)
    
    # --- 1. System Info ---
    uname = platform.uname()
    os_name = get_distro_name()
    kernel = uname.release
    arch = uname.machine
    host_name = get_host_info()
    timezone = get_real_timezone()
    shell = os.environ.get("SHELL", "/bin/bash").split("/")[-1]
    packages = get_packages_count()
    
    # Uptime
    boot_time_timestamp = psutil.boot_time()
    os_uptime = get_readable_time(int(time.time() - boot_time_timestamp))
    bot_uptime = get_readable_time(int(time.time() - BOT_START_TIME))
    
    # --- 2. Resources ---
    cpu_model = get_cpu_model()
    cpu_count = psutil.cpu_count(logical=True)
    cpu_usage = psutil.cpu_percent()
    cpu_bar = make_progress_bar(cpu_usage)
    
    mem = psutil.virtual_memory()
    mem_used = sizeof_fmt(mem.used)
    mem_total = sizeof_fmt(mem.total)
    mem_percent = mem.percent
    mem_free = sizeof_fmt(mem.available)
    mem_bar = make_progress_bar(mem_percent)
    
    swap = psutil.swap_memory()
    swap_total = sizeof_fmt(swap.total) if swap.total > 0 else "Not Set"
    swap_used = sizeof_fmt(swap.used) if swap.total > 0 else "Not Set"
    
    total, used, free = shutil.disk_usage(".")
    disk_used = sizeof_fmt(used)
    disk_total = sizeof_fmt(total)
    disk_free = sizeof_fmt(free)
    disk_percent = int((used / total) * 100)
    disk_bar = make_progress_bar(disk_percent)
    
    net_io = psutil.net_io_counters()
    upload = sizeof_fmt(net_io.bytes_sent)
    download = sizeof_fmt(net_io.bytes_recv)
    total_bw = sizeof_fmt(net_io.bytes_sent + net_io.bytes_recv)
    
    final_text = f"""
<code>OS: {os_name} {arch}
Host: {host_name}
Kernel: {kernel}
Uptime: {os_uptime}
Packages: {packages} (dpkg)
Shell: {shell}
CPU: {cpu_model} ({cpu_count})
Memory: {mem_used} / {mem_total} ({mem_percent}%)
Swap: {swap_total}
Disk (/): {disk_used} / {disk_total} ({disk_percent}%) - overlay

SERVER AREA: {timezone}
BOT UPTIME : {bot_uptime}

「 DISK 」
{disk_bar} | {disk_percent}% of {disk_total}
Available : {disk_free}
Used      : {disk_used}

「 CPU 」
{cpu_bar} | {cpu_usage}%
Cores     : {cpu_count}
Logical   : {cpu_count}
Frequency : Disabled

「 MEMORY 」
{mem_bar} | {mem_percent}% of {mem_total}
Available : {mem_free}
Used      : {mem_used}

「 SWAP 」
Total     : {swap_total}
Used      : {swap_used}

「 BANDWIDTH TOTAL 」
Download  : {download}
Upload    : {upload}
All BW    : {total_bw}
</code>
"""
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 MongoDB Stats", callback_data="stats_mongo")],
        [InlineKeyboardButton("❌ Tutup", callback_data="rnd_close")]
    ])
    
    await msg.edit(final_text, reply_markup=buttons)

# --- CALLBACK: MONGODB STATS ---
@Client.on_callback_query(filters.regex("^stats_mongo$"))
async def mongo_stats_callback(client, query: CallbackQuery):
    await query.answer("🔄 Mengambil data MongoDB...", show_alert=False)
    
    try:
        # Kirim 'client' (bot instance) untuk mencoba reuse koneksi
        cols, docs, size_mb = await get_mongo_stats(client)
        
        text = (
            f"Total Collection : {cols}\n"
            f"Total Documents  : {docs}\n"
            f"Used Storage     : {size_mb:.2f} MB\n"
            f"Host Storage     : Atlas Storage"
        )
        
        await query.answer(text, show_alert=True)
        
    except Exception as e:
        LOGGER.error(f"Callback Stats Error: {e}")
        await query.answer(f"Error System: {e}", show_alert=True)

# --- CALLBACK: CLOSE ---
@Client.on_callback_query(filters.regex("^rnd_close$"))
async def close_callback(client, query: CallbackQuery):
    await query.message.delete()
