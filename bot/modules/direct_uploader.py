# [GANTI TOTAL ISI FILE: bot/modules/direct_uploader.py]

import os
import asyncio
import requests
import json
import re
import io
import time
import aiohttp
from urllib.parse import quote
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bot.logger import LOGGER

class ProgressFileWrapper(io.IOBase):
    """
    Bungkus (Wrapper) file cerdas yang membaca data dari disk sedikit demi sedikit,
    sekaligus mengirimkan denyut (radar) laporan progres ke antarmuka Telegram.
    """
    def __init__(self, filename, details):
        self.file = open(filename, 'rb')
        self.total_size = os.path.getsize(filename)
        self.bytes_read = 0
        self.details = details
        self.loop = asyncio.get_event_loop()
        self.last_update = 0

    def read(self, size=-1):
        # --- DETEKSI TOMBOL CANCEL ---
        from bot.helpers.ui_manager import GLOBAL_CANCEL_DICT
        if self.details and self.details.get('task_id') in GLOBAL_CANCEL_DICT:
            # Membunuh koneksi upload seketika jika tombol Cancel ditekan
            raise Exception("DIBATALKAN_PENGGUNA")
        # -----------------------------
        
        chunk = self.file.read(size)
        if chunk:
            self.bytes_read += len(chunk)
            now = time.time()
            # Tembakkan radar progres setiap 1.5 detik agar Telegram tidak FloodWait
            if self.details and (now - self.last_update > 1.5 or self.bytes_read == self.total_size):
                self.last_update = now
                from bot.helpers.ui_manager import progress_message
                
                def schedule_progress(b_read, t_size, det):
                    asyncio.create_task(progress_message(b_read, t_size, det))
                    
                self.loop.call_soon_threadsafe(schedule_progress, self.bytes_read, self.total_size, self.details)
        return chunk
        
    # --- ANTI CHUNKED TRANSFER UNTUK SERVER PHP/VIKINGFILE ---
    def tell(self):
        return self.file.tell()
        
    def seek(self, offset, whence=io.SEEK_SET):
        return self.file.seek(offset, whence)
    # ---------------------------------------------------------
    
    def close(self):
        self.file.close()

    def readable(self):
        return True
        
    def fileno(self):
        # Penting agar AIOHTTP dapat mendeteksi ukuran Content-Length secara otomatis
        return self.file.fileno()


# --- MANAJER SESI GLOBAL UNTUK UPLOADER ---
_GLOBAL_UPLOAD_SESSION = None

def get_upload_session():
    global _GLOBAL_UPLOAD_SESSION
    if _GLOBAL_UPLOAD_SESSION is None or _GLOBAL_UPLOAD_SESSION.closed:
        # limit=0 mematikan limitasi TCP bawaan aiohttp (100) 
        # agar unggahan paralel file raksasa tidak mengalami bottleneck.
        conn = aiohttp.TCPConnector(limit=0)
        _GLOBAL_UPLOAD_SESSION = aiohttp.ClientSession(connector=conn)
    return _GLOBAL_UPLOAD_SESSION

async def close_upload_session():
    global _GLOBAL_UPLOAD_SESSION
    if _GLOBAL_UPLOAD_SESSION and not _GLOBAL_UPLOAD_SESSION.closed:
        await _GLOBAL_UPLOAD_SESSION.close()
        LOGGER.info("Cloud Uploader: Sesi aiohttp berhasil ditutup dengan aman.")
# ------------------------------------------


class DirectUpload:
    def __init__(self, listener=None, name=None, path=None):
        self.name = name
        self.path = path
        self.listener = listener
        self.user_dict = listener.user_dict if listener else {}

    # ============================
    # GOFILE HANDLER (AIOHTTP)
    # ============================
    async def gofile_get_server(self):
        try:
            session = get_upload_session()
            async with session.get("https://api.gofile.io/servers", timeout=10) as r:
                res = await r.json()
                if res.get('status') == 'ok':
                    return res['data']['servers'][0]['name']
        except: pass
        return "store1"

    async def gofile_get_root(self, token):
        try:
            session = get_upload_session()
            async with session.get(f"https://api.gofile.io/accounts/getid?token={token}", timeout=10) as r1:
                res1 = await r1.json()
                if res1.get('status') == 'ok':
                    acc_id = res1['data']['id']
                    async with session.get(f"https://api.gofile.io/accounts/{acc_id}?token={token}", timeout=10) as r2:
                        res2 = await r2.json()
                        return res2['data']['rootFolder']
        except Exception as e:
            LOGGER.error(f"Gofile Get Root Error: {e}")
        return None

    async def gofile_create_folder_async(self, token, parent_id, name):
        try:
            data = {'token': token, 'parentFolderId': parent_id, 'folderName': name}
            session = get_upload_session()
            async with session.post("https://api.gofile.io/contents/createFolder", data=data, timeout=15) as r:
                res = await r.json()
                if res.get('status') == 'ok': return res['data']
        except: pass
        return None

    async def _upload_gofile_aiohttp(self, filepath, token, folder_id, details):
        server = await self.gofile_get_server()
        url = f"https://{server}.gofile.io/uploadFile"
        
        data = aiohttp.FormData(quote_fields=False)
        data.add_field('token', token)
        if folder_id:
            data.add_field('folderId', folder_id)
            
        filename = os.path.basename(filepath)
        wrapper = ProgressFileWrapper(filepath, details)
        data.add_field('file', wrapper, filename=filename)
        
        try:
            session = get_upload_session()
            async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=3600)) as resp:
                res = await resp.json()
                wrapper.close()
                if res.get('status') == 'ok':
                    return res['data']['downloadPage']
        except Exception as e:
            wrapper.close()
            if 'DIBATALKAN_PENGGUNA' in str(e):
                LOGGER.warning(f"Gofile Upload dibatalkan oleh pengguna: {filename}")
                try:
                    from bot.helpers.message import edit_message
                    if details and 'msg' in details:
                        await edit_message(details['msg'], "🛑 **Proses Dibatalkan oleh Pengguna.**", None, False)
                except: pass
                raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
            else:
                LOGGER.error(f"Gofile Upload Error: {e}")
        return None

    # ============================
    # BUZZHEAVIER HANDLER (AIOHTTP)
    # ============================
    async def buzzheavier_get_root(self, token):
        try:
            headers = {"Authorization": f"Bearer {token}"}
            session = get_upload_session()
            async with session.get("https://buzzheavier.com/api/fs", headers=headers, timeout=10) as r:
                res = await r.json()
                if res.get('code') == 200: 
                    return res['data']['id']
        except Exception as e: 
            LOGGER.error(f"Buzzheavier Get Root Error: {e}")
        return None
    
    async def buzzheavier_create_folder_async(self, token, parent_id, name):
        if not parent_id:
            return None
            
        try:
            url = f"https://buzzheavier.com/api/fs/{parent_id}"
            headers = {"Authorization": f"Bearer {token}"}
            data = {"name": name, "parentId": parent_id}
            
            session = get_upload_session()
            async with session.post(url, headers=headers, json=data, timeout=15) as r:
                res = await r.json()
                
                if res.get('code') == 200 or res.get('code') == 201: 
                    return res['data']['id']
                    
                # --- LOGIKA 409: FOLDER SUDAH ADA ---
                elif res.get('code') == 409:
                    # Deteksi apakah sudah ada angka di belakang nama, misal "(1)"
                    match = re.search(r"\s\((\d+)\)$", name)
                    if match:
                        num = int(match.group(1)) + 1
                        new_name = re.sub(r"\s\(\d+\)$", f" ({num})", name)
                    else:
                        new_name = f"{name} (1)"
                        
                    # Coba buat ulang dengan nama baru
                    return await self.buzzheavier_create_folder_async(token, parent_id, new_name)
                # ------------------------------------
                    
        except Exception as e:
            LOGGER.error(f"Buzzheavier Create Folder Error: {e}")
        return None

    async def _upload_buzzheavier_aiohttp(self, filepath, token, folder_id, details):
        filename = os.path.basename(filepath)
        url = f"https://w.buzzheavier.com/{folder_id}/{quote(filename)}" if folder_id else f"https://w.buzzheavier.com/{quote(filename)}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Length": str(os.path.getsize(filepath))
        }
        
        wrapper = ProgressFileWrapper(filepath, details)
        try:
            session = get_upload_session()
            async with session.put(url, headers=headers, data=wrapper, timeout=aiohttp.ClientTimeout(total=3600)) as resp:
                res = await resp.json()
                wrapper.close()
                if res.get('code') == 201:
                    return f"https://buzzheavier.com/{res['data']['id']}"
        except Exception as e:
            wrapper.close()
            if 'DIBATALKAN_PENGGUNA' in str(e):
                LOGGER.warning(f"Buzzheavier Upload dibatalkan oleh pengguna: {filename}")
                try:
                    from bot.helpers.message import edit_message
                    if details and 'msg' in details:
                        await edit_message(details['msg'], "🛑 **Proses Dibatalkan oleh Pengguna.**", None, False)
                except: pass
                raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
            else:
                LOGGER.error(f"Buzzheavier Upload Error: {e}")
        return None

    # ============================
    # VIKINGFILES HANDLER (AIOHTTP)
    # ============================
    async def _upload_viking_aiohttp(self, filepath, token, details):
        srv = None
        try:
            session = get_upload_session()
            async with session.get("https://vikingfile.com/api/get-server", timeout=10) as r:
                res = await r.json()
                srv = res.get('server')
        except: pass

        if not srv: 
            LOGGER.error("Viking Upload: Gagal mendapatkan server dari API.")
            return None

        data = aiohttp.FormData(quote_fields=False)
        data.add_field('user', token)
        
        filename = os.path.basename(filepath)
        wrapper = ProgressFileWrapper(filepath, details)
        data.add_field('file', wrapper, filename=filename)
        
        try:
            session = get_upload_session()
            async with session.post(srv, data=data, timeout=aiohttp.ClientTimeout(total=3600)) as resp:
                raw_text = await resp.text()
                wrapper.close()
                
                # --- PARSER & DIAGNOSTIK ---
                try:
                    res = json.loads(raw_text)
                    if res.get('url'): return res['url']
                except:
                    # re.DOTALL (re.S) agar bisa melacak JSON multi-baris di dalam HTML
                    match = re.search(r'(\{.*?\})', raw_text, re.DOTALL)
                    if match:
                        try:
                            res = json.loads(match.group(1))
                            if res.get('url'): return res['url']
                            else: LOGGER.warning(f"Viking Regex nemu JSON tapi tidak ada URL: {res}")
                        except: pass
                        
                # Jika sampai di baris ini, berarti server Vikingfile memberikan pesan error!
                LOGGER.error(f"Viking Response Mentah: {raw_text[:500]}")
                # ---------------------------
                        
        except Exception as e:
            wrapper.close()
            if 'DIBATALKAN_PENGGUNA' in str(e):
                LOGGER.warning(f"Vikingfiles Upload dibatalkan oleh pengguna: {filename}")
                try:
                    from bot.helpers.message import edit_message
                    if details and 'msg' in details:
                        await edit_message(details['msg'], "🛑 **Proses Dibatalkan oleh Pengguna.**", None, False)
                except: pass
                # Membunuh rantai Fallback dan Loop secara total!
                raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
            else:
                LOGGER.error(f"Viking Upload Error: {e}")
        return None

    # ============================
    # PUBLIC METHODS
    # ============================
    async def upload(self, file_name, size, upload_type, specific_folder_id=None, details=None):
        filepath = os.path.join(self.path, file_name)
        if not os.path.exists(filepath): return None
        
        if upload_type in ['gf', 'gofile']:
            token = self.user_dict.get("gofile", {}).get("api")
            fid = specific_folder_id or self.user_dict.get("gofile", {}).get("folder_id")
            if token:
                LOGGER.info(f"Uploading Gofile (Aiohttp): {file_name}")
                link = await self._upload_gofile_aiohttp(filepath, token, fid, details)
                return {'Gofile': link} if link else None

        elif upload_type in ['bh', 'buzzheavier']:
            token = self.user_dict.get("buzzheavier", {}).get("api")
            if token:
                LOGGER.info(f"Uploading Buzzheavier (Aiohttp): {file_name}")
                link = await self._upload_buzzheavier_aiohttp(filepath, token, specific_folder_id, details)
                return {'Buzzheavier': link} if link else None

        elif upload_type in ['vk', 'viking']:
            token = self.user_dict.get("vikingfiles", {}).get("api")
            if token:
                LOGGER.info(f"Uploading Viking (Aiohttp): {file_name}")
                link = await self._upload_viking_aiohttp(filepath, token, details)
                return {'Vikingfiles': link} if link else None

        return None
