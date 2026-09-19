# [GANTI TOTAL ISI FILE: bot/helpers/aria2_helper.py]

import os
import asyncio
import aiohttp
from aiohttp.client_exceptions import ClientError, ServerDisconnectedError
from bot.logger import LOGGER
from bot.helpers.proxy_manager import proxy_manager

ARIA2_RPC_URL = "http://127.0.0.1:6800/jsonrpc"
ACTIVE_DOWNLOADS = {}

_ARIA2_SESSION = None

# --- [TAMBAHAN] MANAJEMEN SESI DINAMIS ---
async def get_aria2_session(force_refresh=False):
    global _ARIA2_SESSION
    # Hancurkan sesi lama jika dipaksa refresh (misal saat terdeteksi bengong/putus)
    if force_refresh and _ARIA2_SESSION and not _ARIA2_SESSION.closed:
        await _ARIA2_SESSION.close()
        _ARIA2_SESSION = None

    if _ARIA2_SESSION is None or _ARIA2_SESSION.closed:
        # Gunakan TCPConnector dengan keepalive_timeout 30 detik
        connector = aiohttp.TCPConnector(keepalive_timeout=30)
        timeout = aiohttp.ClientTimeout(total=15)
        _ARIA2_SESSION = aiohttp.ClientSession(connector=connector, timeout=timeout)
    return _ARIA2_SESSION
# -----------------------------------------

async def aria2_download(url, filepath, details=None):
    from bot.helpers.ui_manager import progress_message 

    dir_path = os.path.abspath(os.path.dirname(filepath))
    file_name = os.path.basename(filepath)
    
    options = {
        "dir": dir_path,
        "out": file_name,
        "max-connection-per-server": "1",
        "split": "1",
        "min-split-size": "5M",
        "allow-overwrite": "true",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        
        "header": [
            "Accept: */*",
            "Accept-Encoding: gzip, deflate, br",
            "Connection: keep-alive"
        ],
        "disable-ipv6": "true",       
        "check-certificate": "false", 
        
        "continue": "false",
        "max-tries": "3",
        "retry-wait": "2",
        "timeout": "45",
        
        "content-disposition-default-utf8": "true" 
    }
    
    if details and 'headers' in details and isinstance(details['headers'], dict):
        header_list = [f"{k}: {v}" for k, v in details['headers'].items()]
        if header_list:
            options["header"] = header_list

    if details and 'proxy' in details and details['proxy']:
        proxy_string = details['proxy']
        if proxy_string.startswith("socks5h://"):
            proxy_string = proxy_string.replace("socks5h://", "socks5://", 1)
        options["all-proxy"] = proxy_string

    # --- INTEGASI SENTRAL PROXY MANAGER ---
    used_proxy = None
    if details and 'proxy' in details and details['proxy']:
        used_proxy = await proxy_manager.get_proxy(details['proxy'])
        formatted_proxy = proxy_manager.format_for_aria2(used_proxy)
        if formatted_proxy:
            options["all-proxy"] = formatted_proxy
    # --------------------------------------
    
    payload_add = {
        "jsonrpc": "2.0",
        "id": "bot_add",
        "method": "aria2.addUri",
        "params": [
            [url],
            options 
        ]
    }
    
    try:
        # --- [FIX] AMBIL SESI DINAMIS ---
        session = await get_aria2_session()
        
        # 1. Mengirim perintah ke Aria2 dengan penanganan Drop Koneksi
        try:
            async with session.post(ARIA2_RPC_URL, json=payload_add) as resp:
                res = await resp.json()
        except (ClientError, asyncio.TimeoutError) as net_err:
            LOGGER.warning(f"Aria2 RPC Drop saat AddURI: {net_err}. Menyegarkan sesi...")
            session = await get_aria2_session(force_refresh=True)
            async with session.post(ARIA2_RPC_URL, json=payload_add) as resp:
                res = await resp.json()
        # --------------------------------

        if "error" in res:
            LOGGER.error(f"Aria2 Add Error: {res['error']['message']}")
            return False
        
        gid = res["result"]
        ACTIVE_DOWNLOADS[gid] = file_name
        
        if not file_name.split('.')[-1].isdigit():
            LOGGER.info(f"Aria2 Memulai Unduhan: {file_name} (GID: {gid})")
        
        if details:
            details['task_id'] = gid
            details['title'] = file_name
            details['type'] = 'Download'

        payload_status = {
            "jsonrpc": "2.0",
            "id": "bot_status",
            "method": "aria2.tellStatus",
            "params": [gid]
        }
        
        # 2. Polling status unduhan secara Live
        while True:
            if details and 'task_id' in details:
                from bot.helpers.ui_manager import GLOBAL_CANCEL_DICT
                if details['task_id'] in GLOBAL_CANCEL_DICT:
                    await aria2_cancel(gid) 
                    LOGGER.info(f"Aria2 Task {gid} dipaksa berhenti oleh Sinyal Batal.")
                    return False

            # --- [FIX] KETAHANAN SESI SAAT POLLING ---
            try:
                async with session.post(ARIA2_RPC_URL, json=payload_status) as resp:
                    res = await resp.json()
            except (ClientError, ServerDisconnectedError, asyncio.TimeoutError) as poll_err:
                LOGGER.warning(f"Aria2 RPC Network Error (Polling): {poll_err}. Mengabaikan frame ini dan menyegarkan sesi...")
                # Refresh koneksi dan coba polling lagi di loop berikutnya
                session = await get_aria2_session(force_refresh=True)
                await asyncio.sleep(2.0)
                continue
            # -----------------------------------------

            if "error" in res:
                ACTIVE_DOWNLOADS.pop(gid, None)
                return False
                
            status = res["result"]
            state = status.get("status")
            
            total_length = int(status.get("totalLength", 0))
            completed_length = int(status.get("completedLength", 0))
            
            if details:
                if total_length > 0:
                    await progress_message(completed_length, total_length, details)
                else:
                    from bot.helpers.ui_manager import GLOBAL_TASKS
                    import time
                    task_id = details.get('task_id')
                    if task_id and task_id in GLOBAL_TASKS:
                        GLOBAL_TASKS[task_id]['timestamp'] = time.time()
                        GLOBAL_TASKS[task_id]['action'] = 'Connecting'
                        GLOBAL_TASKS[task_id]['processed'] = 'Mengalokasikan file...'
            
            if state == "complete":
                ACTIVE_DOWNLOADS.pop(gid, None)
                if not file_name.split('.')[-1].isdigit():
                    LOGGER.info(f"Aria2 Berhasil Mengunduh: {file_name}")
                if used_proxy:
                    await proxy_manager.report_success(used_proxy) # <-- Lapor Sukses
                return True
                
            elif state in ["error", "removed"]:
                ACTIVE_DOWNLOADS.pop(gid, None)
                err_msg = status.get("errorMessage", "Dibatalkan oleh pengguna / Unknown Error")
                LOGGER.warning(f"Aria2 Berhenti [{state}]: {err_msg}")
                if used_proxy:
                    await proxy_manager.report_fail(used_proxy) # <-- Lapor Gagal
                return False
                
            await asyncio.sleep(2.0)

    except Exception as e:
        LOGGER.error(f"Aria2 RPC Exception: {e}")
        return False

async def aria2_cancel(gid):
    payload = {
        "jsonrpc": "2.0",
        "id": "bot_cancel",
        "method": "aria2.forceRemove",
        "params": [gid]
    }
    try:
        session = await get_aria2_session()
        async with session.post(ARIA2_RPC_URL, json=payload) as resp:
            res = await resp.json()
            if "error" not in res:
                ACTIVE_DOWNLOADS.pop(gid, None)
                return True
    except Exception:
        pass
    return False

async def get_aria2_global_stat():
    payload = {
        "jsonrpc": "2.0",
        "id": "bot_global_stat",
        "method": "aria2.getGlobalStat",
        "params": []
    }
    try:
        session = await get_aria2_session()
        async with session.post(ARIA2_RPC_URL, json=payload) as resp:
            res = await resp.json()
            if "error" not in res:
                return res["result"]
    except Exception:
        pass
    return None

async def aria2_purge_all():
    payload_active = {
        "jsonrpc": "2.0",
        "id": "bot_purge",
        "method": "aria2.tellActive",
        "params": []
    }
    try:
        session = await get_aria2_session()
        async with session.post(ARIA2_RPC_URL, json=payload_active) as resp:
            res = await resp.json()
            if "result" in res:
                for task in res["result"]:
                    gid = task.get("gid")
                    if gid:
                        kill_payload = {
                            "jsonrpc": "2.0",
                            "id": "bot_kill",
                            "method": "aria2.forceRemove",
                            "params": [gid]
                        }
                        await session.post(ARIA2_RPC_URL, json=kill_payload)
                        
        ACTIVE_DOWNLOADS.clear()
    except Exception:
        pass

async def close_aria2_session():
    global _ARIA2_SESSION
    if _ARIA2_SESSION and not _ARIA2_SESSION.closed:
        await _ARIA2_SESSION.close()
        LOGGER.info("Aria2: Sesi aiohttp global berhasil ditutup dengan aman.")
