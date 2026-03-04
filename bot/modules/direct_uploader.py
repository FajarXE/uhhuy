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
        # --- [TAMBAHAN: DETEKSI TOMBOL CANCEL] ---
        from bot.helpers.utils import GLOBAL_CANCEL_DICT
        if self.details and self.details.get('task_id') in GLOBAL_CANCEL_DICT:
            # Membunuh koneksi upload seketika jika tombol Cancel ditekan
            raise Exception("DIBATALKAN_PENGGUNA")
        # -----------------------------------------
        
        chunk = self.file.read(size)
        if chunk:
            self.bytes_read += len(chunk)
            now = time.time()
            if self.details and (now - self.last_update > 1.5 or self.bytes_read == self.total_size):
                self.last_update = now
                from bot.helpers.utils import progress_message
                
                def schedule_progress(b_read, t_size, det):
                    asyncio.create_task(progress_message(b_read, t_size, det))
                    
                self.loop.call_soon_threadsafe(schedule_progress, self.bytes_read, self.total_size, self.details)
        return chunk
    
    def close(self):
        self.file.close()

    def readable(self):
        return True
        
    def fileno(self):
        # Penting agar AIOHTTP dapat mendeteksi ukuran Content-Length secara otomatis
        return self.file.fileno()

class DirectUpload:
    def __init__(self, listener=None, name=None, path=None):
        self.name = name
        self.path = path
        self.listener = listener
        self.user_dict = listener.user_dict if listener else {}
        
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 504])
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    # ============================
    # GOFILE HANDLER (AIOHTTP)
    # ============================
    def _get_gofile_server(self):
        try:
            r = self.session.get("https://api.gofile.io/servers", timeout=10)
            if r.status_code == 200:
                return r.json()['data']['servers'][0]['name']
        except: pass
        return "store1"

    def _get_gofile_account(self, token):
        try:
            r = self.session.get(f"https://api.gofile.io/accounts/getid?token={token}", timeout=10)
            if r.status_code == 200 and r.json()['status'] == 'ok':
                return r.json()['data']['id']
        except: pass
        return None

    def _gofile_create_folder(self, token, parent_id, name):
        try:
            data = {'token': token, 'parentFolderId': parent_id, 'folderName': name}
            r = self.session.post("https://api.gofile.io/contents/createFolder", data=data, timeout=15)
            if r.status_code == 200 and r.json()['status'] == 'ok':
                return r.json()['data']
        except Exception as e:
            LOGGER.error(f"Gofile Create Folder Error: {e}")
        return None

    async def gofile_get_root(self, token):
        try:
            acc_id = await asyncio.to_thread(self._get_gofile_account, token)
            if acc_id:
                r = await asyncio.to_thread(self.session.get, f"https://api.gofile.io/accounts/{acc_id}?token={token}")
                data = r.json()['data']
                return data['rootFolder']
        except: pass
        return None

    async def gofile_create_folder_async(self, token, parent_id, name):
        return await asyncio.to_thread(self._gofile_create_folder, token, parent_id, name)

    async def _upload_gofile_aiohttp(self, filepath, token, folder_id, details):
        server = await asyncio.to_thread(self._get_gofile_server)
        url = f"https://{server}.gofile.io/uploadFile"
        
        data = aiohttp.FormData()
        data.add_field('token', token)
        if folder_id:
            data.add_field('folderId', folder_id)
            
        filename = os.path.basename(filepath)
        wrapper = ProgressFileWrapper(filepath, details)
        data.add_field('file', wrapper, filename=filename)
        
        try:
            async with aiohttp.ClientSession() as session:
                # Timeout dinaikkan ke 3600 agar file besar tidak terputus
                async with session.post(url, data=data, timeout=aiohttp.ClientTimeout(total=3600)) as resp:
                    res = await resp.json()
                    wrapper.close()
                    if res.get('status') == 'ok':
                        return res['data']['downloadPage']
        except Exception as e:
            wrapper.close()
            # [FIX] Jangan jadikan Error jika itu ulah tombol Cancel
            if 'DIBATALKAN_PENGGUNA' in str(e):
                LOGGER.warning(f"Gofile Upload dibatalkan oleh pengguna: {filename}")
            else:
                LOGGER.error(f"Gofile Upload Error: {e}")
        return None

    # ============================
    # BUZZHEAVIER HANDLER (AIOHTTP)
    # ============================
    def _buzzheavier_get_root(self, token):
        try:
            headers = {"Authorization": f"Bearer {token}"}
            r = self.session.get("https://buzzheavier.com/api/fs", headers=headers, timeout=10)
            if r.json().get('code') == 200: return r.json()['data']['id']
        except: pass
        return None
    
    def _buzzheavier_create_folder(self, token, parent_id, name):
        try:
            url = f"https://buzzheavier.com/api/fs/{parent_id}"
            headers = {"Authorization": f"Bearer {token}"}
            data = {"name": name, "parentId": parent_id}
            r = self.session.post(url, headers=headers, json=data, timeout=15)
            res = r.json()
            if res.get('code') == 200: return res['data']['id']
            elif res.get('code') == 409:
                match = re.search(r"\((\d+)\)$", name)
                if match:
                    num = int(match.group(1)) + 1
                    new_name = re.sub(r"\(\d+\)$", f"({num})", name)
                else:
                    new_name = f"{name} (1)"
                return self._buzzheavier_create_folder(token, parent_id, new_name)
        except: pass
        return None

    async def buzzheavier_get_root(self, token):
         return await asyncio.to_thread(self._buzzheavier_get_root, token)

    async def buzzheavier_create_folder_async(self, token, parent_id, name):
         return await asyncio.to_thread(self._buzzheavier_create_folder, token, parent_id, name)

    async def _upload_buzzheavier_aiohttp(self, filepath, token, folder_id, details):
        filename = os.path.basename(filepath)
        url = f"https://w.buzzheavier.com/{folder_id}/{quote(filename)}" if folder_id else f"https://w.buzzheavier.com/{quote(filename)}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Length": str(os.path.getsize(filepath))
        }
        
        wrapper = ProgressFileWrapper(filepath, details)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(url, headers=headers, data=wrapper, timeout=aiohttp.ClientTimeout(total=3600)) as resp:
                    res = await resp.json()
                    wrapper.close()
                    if res.get('code') == 201:
                        return f"https://buzzheavier.com/{res['data']['id']}"
        except Exception as e:
            wrapper.close()
            # [FIX] Filter Log Cancel
            if 'DIBATALKAN_PENGGUNA' in str(e):
                LOGGER.warning(f"Buzzheavier Upload dibatalkan oleh pengguna: {filename}")
            else:
                LOGGER.error(f"Buzzheavier Upload Error: {e}")
        return None

    # ============================
    # VIKINGFILES HANDLER (AIOHTTP)
    # ============================
    async def _upload_viking_aiohttp(self, filepath, token, details):
        def get_srv():
            try: return self.session.get("https://vikingfile.com/api/get-server", timeout=10).json()['server']
            except: return None
        srv = await asyncio.to_thread(get_srv)
        if not srv: return None

        data = aiohttp.FormData()
        data.add_field('user', token)
        
        filename = os.path.basename(filepath)
        wrapper = ProgressFileWrapper(filepath, details)
        data.add_field('file', wrapper, filename=filename)
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(srv, data=data, timeout=aiohttp.ClientTimeout(total=3600)) as resp:
                    # [FIX] Jangan gunakan resp.json() karena server Viking melempar HTML!
                    # Kita baca sebagai teks biasa, lalu gali JSON-nya secara manual.
                    raw_text = await resp.text()
                    wrapper.close()
                    
                    try:
                        res = json.loads(raw_text)
                        if res.get('url'): return res['url']
                    except:
                        # Fallback: Gunakan mesin bor Regex jika bentuknya berantakan
                        match = re.search(r'(\{.*\})', raw_text)
                        if match:
                            res = json.loads(match.group(1))
                            if res.get('url'): return res['url']
                            
        except Exception as e:
            wrapper.close()
            # [FIX] Filter Log Cancel
            if 'DIBATALKAN_PENGGUNA' in str(e):
                LOGGER.warning(f"Vikingfiles Upload dibatalkan oleh pengguna: {filename}")
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
