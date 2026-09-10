# [FILE: bot/helpers/aria2_helper.py]

import os
import asyncio
import aiohttp
from bot.logger import LOGGER

ARIA2_RPC_URL = "http://127.0.0.1:6800/jsonrpc"

# Dictionary untuk menyimpan ID unduhan yang sedang berjalan
ACTIVE_DOWNLOADS = {}

async def aria2_download(url, filepath, details=None):
    # Import di dalam fungsi untuk menghindari circular import
    from bot.helpers.utils import progress_message 

    # --- FIX: Ubah path menjadi Absolut agar daemon Aria2 tidak nyasar ---
    dir_path = os.path.abspath(os.path.dirname(filepath))
    file_name = os.path.basename(filepath)
    
    # --- [FIX ARIA2] KEMAMPUAN MEMAKAI TOPENG (HEADERS) & ANTI-THROTTLING ---
    options = {
        "dir": dir_path,
        "out": file_name,
        
        # 1. Agresi Koneksi Diturunkan
        # Menggunakan 16 koneksi ke CDN Akamai sering dianggap sebagai serangan/leeching.
        # Menurunkannya ke 8 (atau bahkan 4) justru akan menghasilkan kecepatan yang lebih stabil.
        "max-connection-per-server": "8",
        "split": "8",
        
        # 2. Ukuran Potongan Diperbesar
        # Jangan memecah file terlalu kecil. 5M berarti Aria2 baru akan memecah file jika ukurannya > 5MB.
        # Ini mengurangi jumlah request ke server Akamai.
        "min-split-size": "5M",
        
        "allow-overwrite": "true",
        
        # 3. Toleransi Waktu & Retry Ditingkatkan
        "max-tries": "15",
        "retry-wait": "5",
        "timeout": "60",
        
        # 4. Batas Kecepatan Terendah Dilonggarkan
        # Turunkan dari 100K menjadi 10K (10 KB/s). 
        # Ini mencegah Aria2 memutus koneksi secara prematur saat CDN sedang melakukan micro-throttling.
        "lowest-speed-limit": "10K",
        
        # Ekstra: Mencegah error nama file jika server mengirim karakter aneh
        "content-disposition-default-utf8": "true" 
    }
    
    # Jika ada headers dari layanan musik, pasangkan ke opsi Aria2!
    if details and 'headers' in details and isinstance(details['headers'], dict):
        header_list = [f"{k}: {v}" for k, v in details['headers'].items()]
        if header_list:
            options["header"] = header_list
    # ------------------------------------------------------

    # --- FIX AKAMAI 403: Pasangkan Proxy ke Aria2 ---
    if details and 'proxy' in details and details['proxy']:
        proxy_string = details['proxy']
        
        # Sanitasi scheme socks5h ke socks5 untuk kompatibilitas daemon Aria2c
        if proxy_string.startswith("socks5h://"):
            proxy_string = proxy_string.replace("socks5h://", "socks5://", 1)
            
        options["all-proxy"] = proxy_string
    # ------------------------------------------------
    
    payload_add = {
        "jsonrpc": "2.0",
        "id": "bot_add",
        "method": "aria2.addUri",
        "params": [
            [url],
            options # <--- Masukkan opsi yang sudah ditambahkan headers
        ]
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            # 1. Mengirim perintah ke Aria2
            async with session.post(ARIA2_RPC_URL, json=payload_add) as resp:
                res = await resp.json()
                if "error" in res:
                    LOGGER.error(f"Aria2 Add Error: {res['error']['message']}")
                    return False
                
                # Mendapatkan Task ID (GID) asli dari Aria2
                gid = res["result"]
                ACTIVE_DOWNLOADS[gid] = file_name
                
                # --- FIX: Sembunyikan log 'Memulai Unduhan' untuk file berakhiran angka (.0, .1) ---
                if not file_name.split('.')[-1].isdigit():
                    LOGGER.info(f"Aria2 Memulai Unduhan: {file_name} (GID: {gid})")
                
                # Menyiapkan data untuk UI Progress Bar
                if details:
                    details['task_id'] = gid
                    details['title'] = file_name
                    details['type'] = 'Download'

            # 2. Polling status unduhan secara Live
            payload_status = {
                "jsonrpc": "2.0",
                "id": "bot_status",
                "method": "aria2.tellStatus",
                "params": [gid]
            }
            
            while True:
                # --- [FIX ZOMBIE TASK] CEK SINYAL BATAL GLOBAL ---
                if details and 'task_id' in details:
                    from bot.helpers.utils import GLOBAL_CANCEL_DICT
                    if details['task_id'] in GLOBAL_CANCEL_DICT:
                        await aria2_cancel(gid) # Hancurkan task di sisi server Aria2
                        LOGGER.info(f"Aria2 Task {gid} dipaksa berhenti oleh Sinyal Batal.")
                        return False
                # -------------------------------------------------

                async with session.post(ARIA2_RPC_URL, json=payload_status) as resp:
                    res = await resp.json()
                    if "error" in res:
                        ACTIVE_DOWNLOADS.pop(gid, None)
                        return False
                        
                    status = res["result"]
                    state = status.get("status")
                    
                    # Ambil angka bytes untuk progress bar
                    total_length = int(status.get("totalLength", 0))
                    completed_length = int(status.get("completedLength", 0))
                    
                    # --- [FIX GHOST TASK] JANTUNG BUATAN ---
                    if details:
                        if total_length > 0:
                            await progress_message(completed_length, total_length, details)
                        else:
                            # Memompa detak jantung meski Aria2 nyangkut agar tidak dihapus sistem
                            from bot.helpers.utils import GLOBAL_TASKS
                            import time
                            task_id = details.get('task_id')
                            if task_id and task_id in GLOBAL_TASKS:
                                GLOBAL_TASKS[task_id]['timestamp'] = time.time()
                                GLOBAL_TASKS[task_id]['action'] = 'Connecting'
                                GLOBAL_TASKS[task_id]['processed'] = 'Mengalokasikan file...'
                    # ----------------------------------------
                    
                    if state == "complete":
                        ACTIVE_DOWNLOADS.pop(gid, None)
                        # Sembunyikan log pecahan DASH (.0, .1) agar terminal tidak kotor/lag
                        if not file_name.split('.')[-1].isdigit():
                            LOGGER.info(f"Aria2 Berhasil Mengunduh: {file_name}")
                        return True
                        
                    elif state in ["error", "removed"]:
                        ACTIVE_DOWNLOADS.pop(gid, None)
                        err_msg = status.get("errorMessage", "Dibatalkan oleh pengguna / Unknown Error")
                        LOGGER.warning(f"Aria2 Berhenti [{state}]: {err_msg}")
                        return False
                        
                # --- [PROPER FIX CPU OVERLOAD & SPEED UNLOCK] ---
                # Titik ideal: 0.05 detik (20x request/detik).
                # CPU server tetap sangat rileks, tapi potongan DASH Tidal akan dieksekusi secepat kilat!
                await asyncio.sleep(0.05)
 
    except Exception as e:
        LOGGER.error(f"Aria2 RPC Exception: {e}")
        return False

# FUNGSI BARU: Untuk membatalkan unduhan (Force Remove)
async def aria2_cancel(gid):
    payload = {
        "jsonrpc": "2.0",
        "id": "bot_cancel",
        "method": "aria2.forceRemove",
        "params": [gid]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(ARIA2_RPC_URL, json=payload) as resp:
                res = await resp.json()
                if "error" not in res:
                    ACTIVE_DOWNLOADS.pop(gid, None)
                    return True
    except:
        pass
    return False

async def get_aria2_global_stat():
    """Mengambil total kecepatan download Aria2 secara realtime"""
    payload = {
        "jsonrpc": "2.0",
        "id": "bot_global_stat",
        "method": "aria2.getGlobalStat",
        "params": []
    }
    
    # Pastikan URL di dalam fungsi juga menggunakan IP statis
    ARIA2_RPC_URL = "http://127.0.0.1:6800/jsonrpc" 
    
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(ARIA2_RPC_URL, json=payload) as resp:
                res = await resp.json()
                if "error" not in res:
                    return res["result"]
    except Exception:
        # [FIX] Hapus/Bungkam LOGGER.error di sini agar tidak membanjiri log 
        # saat Aria2 sedang dimuat ulang atau gagal berjalan.
        pass
        
    return None

async def aria2_purge_all():
    """Membersihkan SEMUA task Aria2 yang nyangkut di background saat bot baru nyala"""
    payload_active = {
        "jsonrpc": "2.0",
        "id": "bot_purge",
        "method": "aria2.tellActive",
        "params": []
    }
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            # Cari semua task yang sedang berjalan
            async with session.post(ARIA2_RPC_URL, json=payload_active) as resp:
                res = await resp.json()
                if "result" in res:
                    for task in res["result"]:
                        gid = task.get("gid")
                        if gid:
                            # Bunuh paksa task yang nyangkut
                            kill_payload = {
                                "jsonrpc": "2.0",
                                "id": "bot_kill",
                                "method": "aria2.forceRemove",
                                "params": [gid]
                            }
                            await session.post(ARIA2_RPC_URL, json=kill_payload)
                            
            # Bersihkan cache memori bot kita
            ACTIVE_DOWNLOADS.clear()
    except Exception:
        pass
