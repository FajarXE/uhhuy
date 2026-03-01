# [FILE: bot/helpers/aria2_helper.py]

import os
import asyncio
import aiohttp
from bot.logger import LOGGER

# Alamat RPC bawaan Aria2 yang kita set di start.sh
ARIA2_RPC_URL = "http://localhost:6800/jsonrpc"

async def aria2_download(url, filepath):
    """
    Fungsi ringan untuk mengunduh file menggunakan daemon Aria2 via JSON-RPC.
    Mendukung unduhan multi-connection (lebih cepat dari requests biasa).
    """
    dir_path = os.path.dirname(filepath)
    file_name = os.path.basename(filepath)
    
    # Konfigurasi perintah download Aria2
    payload_add = {
        "jsonrpc": "2.0",
        "id": "bot_add",
        "method": "aria2.addUri",
        "params": [
            [url],
            {
                "dir": dir_path,
                "out": file_name,
                "max-connection-per-server": "16", # Memecah 1 file jadi 16 koneksi
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
                gid = res["result"]
                LOGGER.info(f"Aria2 Memulai Unduhan: {file_name} (GID: {gid})")

            # 2. Polling status unduhan
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
                        return False
                        
                    status = res["result"]
                    state = status.get("status")
                    
                    if state == "complete":
                        LOGGER.info(f"Aria2 Berhasil Mengunduh: {file_name}")
                        return True
                    elif state in ["error", "removed"]:
                        err_msg = status.get("errorMessage", "Unknown Error")
                        LOGGER.error(f"Aria2 Gagal [{state}]: {err_msg}")
                        return False
                        
                # Cek status setiap 2 detik agar tidak membebani sistem
                await asyncio.sleep(2) 

    except Exception as e:
        LOGGER.error(f"Aria2 RPC Exception: {e}")
        return False
