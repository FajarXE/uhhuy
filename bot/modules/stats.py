import os
import time
import sys
import shutil
import psutil
import platform
import subprocess
from pyrogram import Client, filters, __version__ as pyro_ver
from config import Config

# Simpan waktu start bot
BOT_START_TIME = time.time()

# Filter Admin
admin_only = filters.user(list(Config.ADMINS))

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

def get_os_info():
    try:
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=")[1].strip().strip('"')
    except:
        pass
    return platform.system() + " " + platform.release()

@Client.on_message(filters.command(["stats", "status"]) & admin_only)
async def stats_handler(client, message):
    msg = await message.reply("🔄 **Mengambil Data Sistem...**", quote=True)
    
    # 1. System Info
    uname = platform.uname()
    os_name = get_os_info()
    kernel = uname.release
    arch = uname.machine
    
    # 2. Uptime Calculation
    boot_time_timestamp = psutil.boot_time()
    os_uptime_seconds = int(time.time() - boot_time_timestamp)
    os_uptime = get_readable_time(os_uptime_seconds)
    
    bot_uptime_seconds = int(time.time() - BOT_START_TIME)
    bot_uptime = get_readable_time(bot_uptime_seconds)
    
    # 3. CPU Info
    cpu_count = psutil.cpu_count(logical=True)
    cpu_freq = psutil.cpu_freq()
    cpu_freq_str = f"{cpu_freq.current:.2f}Mhz" if cpu_freq else "N/A"
    cpu_usage = psutil.cpu_percent()
    
    # 4. Memory (RAM)
    mem = psutil.virtual_memory()
    mem_used = sizeof_fmt(mem.used)
    mem_total = sizeof_fmt(mem.total)
    mem_percent = mem.percent
    
    # 5. Disk Usage
    total, used, free = shutil.disk_usage(".")
    disk_used = sizeof_fmt(used)
    disk_total = sizeof_fmt(total)
    disk_free = sizeof_fmt(free)
    disk_percent = int((used / total) * 100)
    
    # 6. Bot Process Usage
    process = psutil.Process(os.getpid())
    bot_ram_usage = sizeof_fmt(process.memory_info().rss)
    
    # 7. Network Stats (Total since boot)
    net_io = psutil.net_io_counters()
    upload = sizeof_fmt(net_io.bytes_sent)
    download = sizeof_fmt(net_io.bytes_recv)

    # 8. Python & Lib Versions
    py_ver = sys.version.split()[0]
    
    # Menyusun Text (Format Neofetch-like)
    stats_text = f"""
<code>
OS: {os_name} {arch}
Host: Render / VPS
Kernel: {kernel}
Uptime: {os_uptime}
CPU: {uname.processor} ({cpu_count} Core) @ {cpu_usage}%
Memory: {mem_used} / {mem_total} ({mem_percent}%)
Swap: Disabled
Disk (/): {disk_used} / {disk_total} ({disk_percent}%)

OS Uptime: {os_uptime}
Bot Uptime: {bot_uptime}
Bot Usage: {bot_ram_usage}

Total Space: {disk_total}
Free Space: {disk_free}

Download: {download}
Upload: {upload}

PyroFork Version: {pyro_ver}
Python Version: {py_ver}
</code>
"""
    await msg.edit(stats_text)
