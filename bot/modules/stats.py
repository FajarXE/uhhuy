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

def get_cpu_model():
    """Membaca detail model CPU langsung dari /proc/cpuinfo"""
    try:
        command = "cat /proc/cpuinfo | grep 'model name' | uniq | cut -d: -f2"
        # Coba cara standar (Intel/AMD)
        output = subprocess.check_output(command, shell=True).decode().strip()
        
        # Jika kosong (biasanya di ARM/Aarch64 kuncinya 'Model' atau 'Processor')
        if not output:
             command_arm = "cat /proc/cpuinfo | grep 'Model' | uniq | cut -d: -f2"
             output = subprocess.check_output(command_arm, shell=True).decode().strip()
        
        # Jika masih kosong, coba ambil Hardware
        if not output:
             command_hw = "cat /proc/cpuinfo | grep 'Hardware' | uniq | cut -d: -f2"
             output = subprocess.check_output(command_hw, shell=True).decode().strip()
             
        if output:
            return output
    except:
        pass
    
    # Fallback jika gagal baca file
    return platform.processor() or "Unknown CPU"

def get_host_info():
    """Mendeteksi Virtualisasi Host (KVM/Docker/dll)"""
    try:
        # Cara paling akurat di Linux: membaca DMI product name
        if os.path.exists("/sys/devices/virtual/dmi/id/product_name"):
            with open("/sys/devices/virtual/dmi/id/product_name", "r") as f:
                return f.read().strip()
        elif os.path.exists("/sys/class/dmi/id/product_name"):
            with open("/sys/class/dmi/id/product_name", "r") as f:
                return f.read().strip()
    except:
        pass
    
    # Fallback ke platform
    return "Render / Linux Container"

def get_gpu_info():
    """Mendeteksi GPU menggunakan lspci"""
    try:
        # Mencari device VGA atau 3D controller
        command = "lspci | grep -i 'vga\\|3d' | cut -d: -f3"
        output = subprocess.check_output(command, shell=True).decode().strip()
        if output:
            return output
    except:
        pass
    return "N/A (Headless/No GPU Access)"

def get_distro_name():
    try:
        return subprocess.check_output("cat /etc/*release | grep ^PRETTY_NAME | cut -d= -f2", shell=True).decode().strip().replace('"', '')
    except:
        return platform.system()

@Client.on_message(filters.command(["stats", "status"]) & admin_only)
async def stats_handler(client, message):
    msg = await message.reply("🔄 **Mengambil Data Sistem...**", quote=True)
    
    # 1. System Info
    uname = platform.uname()
    os_name = get_distro_name()
    kernel = uname.release
    arch = uname.machine
    
    # [PERBAIKAN HOST]
    host_name = get_host_info()
    
    # 2. Uptime
    boot_time_timestamp = psutil.boot_time()
    os_uptime_seconds = int(time.time() - boot_time_timestamp)
    os_uptime = get_readable_time(os_uptime_seconds)
    
    bot_uptime_seconds = int(time.time() - BOT_START_TIME)
    bot_uptime = get_readable_time(bot_uptime_seconds)
    
    # 3. CPU Info [PERBAIKAN CPU]
    cpu_model = get_cpu_model()
    cpu_count = psutil.cpu_count(logical=True)
    cpu_usage = psutil.cpu_percent()
    
    # 4. GPU Info [PERBAIKAN GPU]
    gpu_info = get_gpu_info()
    
    # 5. Memory (RAM)
    mem = psutil.virtual_memory()
    mem_used = sizeof_fmt(mem.used)
    mem_total = sizeof_fmt(mem.total)
    mem_percent = mem.percent
    
    # 6. Disk Usage
    total, used, free = shutil.disk_usage(".")
    disk_used = sizeof_fmt(used)
    disk_total = sizeof_fmt(total)
    disk_percent = int((used / total) * 100)
    
    # 7. Bot Process Usage
    process = psutil.Process(os.getpid())
    bot_ram_usage = sizeof_fmt(process.memory_info().rss)
    
    # 8. Network Stats
    net_io = psutil.net_io_counters()
    upload = sizeof_fmt(net_io.bytes_sent)
    download = sizeof_fmt(net_io.bytes_recv)

    # 9. Versions
    py_ver = sys.version.split()[0]
    
    stats_text = f"""
<code>
OS: {os_name} {arch}
Host: {host_name}
Kernel: {kernel}
Uptime: {os_uptime}

CPU: {cpu_model} ({cpu_count} Core) @ {cpu_usage}%
GPU: {gpu_info}

Memory: {mem_used} / {mem_total} ({mem_percent}%)
Swap: Disabled
Disk (/): {disk_used} / {disk_total} ({disk_percent}%)

OS Uptime: {os_uptime}
Bot Uptime: {bot_uptime}
Bot Usage: {bot_ram_usage}

Download: {download}
Upload: {upload}

PyroFork Version: {pyro_ver}
Python Version: {py_ver}
</code>
"""
    await msg.edit(stats_text)
