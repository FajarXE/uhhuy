# [FILE: bot/helpers/aria2_helper.py]

import os
import asyncio
import aiohttp
from bot.logger import LOGGER

ARIA2_RPC_URL = "http://localhost:6800/jsonrpc"

# Dictionary untuk menyimpan ID unduhan yang sedang berjalan
ACTIVE_DOWNLOADS = {}

async def aria2_download(url, filepath, details=None):
    # Import di dalam fungsi untuk menghindari circular import
    from bot.helpers.utils import progress_message 

    dir_path = os.path.dirname(filepath)
    file_name = os.path.basename(filepath)
    
    payload_add = {
        "jsonrpc": "2.0",
        "id": "bot_add",
        "method": "aria2.addUri",
        "params": [
            [url],
            {
                "dir": dir_path,
                "out": file_name,
                "max-connection-per-server": "16",
                "split": "16",
                "min-split-size": "1M",
                "allow-overwrite": "true"
            }
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
                    
                    # Update Telegram Message UI secara Live
                    if details and total_length > 0:
                        await progress_message(completed_length, total_length, details)
                    
                    if state == "complete":
                        ACTIVE_DOWNLOADS.pop(gid, None)
                        LOGGER.info(f"Aria2 Berhasil Mengunduh: {file_name}")
                        return True
                    elif state in ["error", "removed"]:
                        ACTIVE_DOWNLOADS.pop(gid, None)
                        err_msg = status.get("errorMessage", "Dibatalkan oleh pengguna / Unknown Error")
                        LOGGER.warning(f"Aria2 Berhenti [{state}]: {err_msg}")
                        return False
                        
                await asyncio.sleep(2) 

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
