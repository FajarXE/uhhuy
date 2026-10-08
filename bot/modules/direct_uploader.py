# [GANTI TOTAL ISI FILE: bot/modules/direct_uploader.py]

import os
import asyncio
import requests
import json
import re
import io
import time
import aiohttp
import hashlib
import base64
import unicodedata
import uuid
from urllib.parse import quote
from urllib.parse import unquote
from zlib import crc32
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from aiohttp.client_exceptions import ServerDisconnectedError, ClientConnectorError
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

def get_upload_session(force_refresh=False):
    global _GLOBAL_UPLOAD_SESSION
    if force_refresh:
        if _GLOBAL_UPLOAD_SESSION and not _GLOBAL_UPLOAD_SESSION.closed:
            # Jadwalkan penutupan di background agar tidak membekukan IO
            asyncio.create_task(_GLOBAL_UPLOAD_SESSION.close())
        _GLOBAL_UPLOAD_SESSION = None

    if _GLOBAL_UPLOAD_SESSION is None or _GLOBAL_UPLOAD_SESSION.closed:
        # limit=0 mematikan limitasi TCP bawaan aiohttp (100) 
        # agar unggahan paralel file raksasa tidak mengalami bottleneck.
        conn = aiohttp.TCPConnector(limit=0, keepalive_timeout=60, enable_cleanup_closed=True)
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
                
                # --- [FIX ANTI ZOMBIE CONNECTION] ---
                if isinstance(e, (ServerDisconnectedError, ClientConnectorError, asyncio.TimeoutError)):
                    get_upload_session(force_refresh=True)
                    LOGGER.info("Cloud Uploader: Sesi aiohttp Gofile dibuang karena terdeteksi mati.")
                # ------------------------------------
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
                
                # --- [FIX ANTI ZOMBIE CONNECTION] ---
                if isinstance(e, (ServerDisconnectedError, ClientConnectorError, asyncio.TimeoutError)):
                    get_upload_session(force_refresh=True)
                    LOGGER.info("Cloud Uploader: Sesi aiohttp Buzzheavier dibuang karena terdeteksi mati.")
                # ------------------------------------
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
                
                # --- [FIX ANTI ZOMBIE CONNECTION] ---
                if isinstance(e, (ServerDisconnectedError, ClientConnectorError, asyncio.TimeoutError)):
                    get_upload_session(force_refresh=True)
                    LOGGER.info("Cloud Uploader: Sesi aiohttp Viking dibuang karena terdeteksi mati.")
                # ------------------------------------
        return None

    # ============================
    # PIXELDRAIN HANDLER (AIOHTTP)
    # ============================
    async def pixeldrain_create_list(self, token, title, file_ids):
        url = "https://pixeldrain.com/api/list"
        headers = {}
        if token:
            auth_str = base64.b64encode(f":{token}".encode()).decode()
            headers["Authorization"] = f"Basic {auth_str}"
        
        payload = {
            "title": title,
            "anonymous": False if token else True,
            "files": [{"id": fid} for fid in file_ids]
        }
        try:
            session = get_upload_session()
            async with session.post(url, json=payload, headers=headers, timeout=15) as r:
                res = await r.json()
                if res.get('success') or res.get('id'):
                    return f"https://pixeldrain.com/l/{res.get('id')}"
        except Exception as e:
            LOGGER.error(f"Pixeldrain Create List Error: {e}")
        return None

    async def _upload_pixeldrain_aiohttp(self, filepath, token, details):
        url = "https://pixeldrain.com/api/file"
        filename = os.path.basename(filepath)

        headers = {}
        if token:
            auth_str = base64.b64encode(f":{token}".encode()).decode()
            headers["Authorization"] = f"Basic {auth_str}"

        data = aiohttp.FormData(quote_fields=False)
        data.add_field("name", filename)
        data.add_field("anonymous", "False" if token else "True")

        wrapper = ProgressFileWrapper(filepath, details)
        data.add_field("file", wrapper, filename=filename)

        try:
            session = get_upload_session()
            async with session.post(url, data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=3600)) as resp:
                res = await resp.json()
                wrapper.close()
                if res.get('id'):
                    return f"https://pixeldrain.com/u/{res.get('id')}"
                else:
                    LOGGER.error(f"Pixeldrain Response Error: {res}")
        except Exception as e:
            wrapper.close()
            if 'DIBATALKAN_PENGGUNA' in str(e):
                LOGGER.warning(f"Pixeldrain Upload dibatalkan oleh pengguna: {filename}")
                try:
                    from bot.helpers.message import edit_message
                    if details and 'msg' in details:
                        await edit_message(details['msg'], "🛑 **Proses Dibatalkan oleh Pengguna.**", None, False)
                except Exception:
                    pass
                raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
            else:
                LOGGER.error(f"Pixeldrain Upload Error: {e}")
                if isinstance(e, (ServerDisconnectedError, ClientConnectorError, asyncio.TimeoutError)):
                    get_upload_session(force_refresh=True)
                    LOGGER.info("Cloud Uploader: Sesi aiohttp Pixeldrain dibuang karena terdeteksi mati.")
        return None

    # ============================
    # TERABOX HANDLER (AIOHTTP)
    # ============================
    @staticmethod
    def _parse_tb_cookies(raw_text: str) -> dict:
        cookies = {}
        if not raw_text:
            return cookies
        if "\t" in raw_text:
            # Format Netscape cookies.txt
            for line in raw_text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("//"):
                    continue
                fields = line.split("\t")
                if len(fields) >= 7:
                    cookies[fields[5].strip()] = fields[6].strip()
        else:
            # Format string semicolon (k=v; k=v)
            for part in raw_text.split(";"):
                part = part.strip()
                if "=" in part:
                    k, v = part.split("=", 1)
                    cookies[k.strip()] = v.strip()

        if "browserid" not in cookies:
            cookies["browserid"] = str(uuid.uuid4())
        if "lang" not in cookies:
            cookies["lang"] = "en"
        return cookies

    def _terabox_hash_file(self, filepath: str, size: int) -> dict:
        MiB = 1024 * 1024
        chunk_size = 4 * MiB if size < 1024 * MiB else (8 * MiB if size < 3 * 1024 * MiB else 12 * MiB)
        slice_size = 256 * 1024

        file_hash = hashlib.md5()
        slice_hash = hashlib.md5()
        chunk_hashes = []
        crc_val = 0
        processed = 0

        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                file_hash.update(chunk)
                crc_val = crc32(chunk, crc_val)
                chunk_hashes.append(hashlib.md5(chunk).hexdigest())
                if processed == 0:
                    slice_hash.update(chunk[:slice_size])
                processed += len(chunk)

        return {
            "file": file_hash.hexdigest(),
            "slice": slice_hash.hexdigest(),
            "crc32": crc_val & 0xFFFFFFFF,
            "chunks": chunk_hashes,
            "chunk_size": chunk_size
        }

    async def _terabox_get_js_token(self, session, cookie_header: str, api_url: str):
        endpoints = [
            f"{api_url}/wap/home",
            f"{api_url}/main",
            "https://www.terabox.com/wap/home",
            "https://www.terabox.com/main"
        ]
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Cookie": cookie_header,
            "Referer": "https://www.terabox.com/"
        }
        for ep in endpoints:
            try:
                async with session.get(ep, headers=headers, timeout=10) as resp:
                    text = await resp.text()
                    yy_match = re.search(r"window\.yyData\s*=\s*(\{.*?\});", text)
                    if yy_match:
                        try:
                            d = json.loads(yy_match.group(1))
                            if "jstoken" in d:
                                token = d["jstoken"]
                                if "%" in token:
                                    token = unquote(token)
                                in_m = re.search(r'fn\("(.*?)"\)', token)
                                return in_m.group(1) if in_m else token
                        except Exception:
                            pass

                    tdata_match = re.search(r"<script>var templateData = (\{.*?\});</script>", text)
                    if tdata_match:
                        try:
                            d = json.loads(tdata_match.group(1))
                            if "jsToken" in d:
                                token = d["jsToken"]
                                if "%" in token:
                                    token = unquote(token)
                                in_m = re.search(r'fn\("(.*?)"\)', token)
                                return in_m.group(1) if in_m else token
                        except Exception:
                            pass

                    for pat in [r'window\.jsToken\s*=\s*.*?;fn\("(.*?)"\)', r'fn\("(.+?)"\)', r'"jsToken"\s*:\s*"([^"]+)"']:
                        m = re.search(pat, text)
                        if m and len(m.group(1)) > 20:
                            tok = m.group(1)
                            return unquote(tok) if "%" in tok else tok
            except Exception:
                pass
        return None

    async def terabox_create_dir(self, remote_dir: str, cookie_raw: str):
        cookie_dict = self._parse_tb_cookies(cookie_raw)
        cookie_header = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
        api_url = "https://dm.terabox.com"
        url = f"{api_url}/api/create"
        data = {"path": remote_dir, "isdir": "1", "block_list": "[]", "size": "0"}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Cookie": cookie_header,
            "Referer": f"{api_url}/main"
        }
        try:
            session = get_upload_session()
            async with session.post(url, data=data, headers=headers, timeout=15) as resp:
                await resp.json(content_type=None)
        except Exception as e:
            LOGGER.debug(f"Terabox create dir warning: {e}")

    async def terabox_share(self, remote_path: str, cookie_raw: str):
        cookie_dict = self._parse_tb_cookies(cookie_raw)
        cookie_header = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
        api_url = "https://dm.terabox.com"
        url = f"{api_url}/share/pset"
        data = {
            "schannel": "0",
            "channel_list": "[]",
            "period": "0",
            "path_list": json.dumps([remote_path])
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Cookie": cookie_header,
            "Referer": api_url
        }
        try:
            session = get_upload_session()
            async with session.post(url, data=data, headers=headers, timeout=20) as resp:
                res = await resp.json(content_type=None)
                if res.get("errno") == 0 and "shorturl" in res:
                    shorturl = res["shorturl"]
                    if shorturl.startswith("http"):
                        return shorturl
                    return f"https://terabox.com/s/{shorturl}"
                elif "link" in res:
                    return res["link"]
                else:
                    LOGGER.error(f"Terabox share failed: {res}")
        except Exception as e:
            LOGGER.error(f"Terabox share error: {e}")
        return None

    async def _upload_terabox_aiohttp(self, filepath: str, cookie_raw: str, remote_dir: str = "/", details=None):
        if not cookie_raw:
            LOGGER.error("Terabox: Cookies tidak ditemukan!")
            return None

        cookie_dict = self._parse_tb_cookies(cookie_raw)
        cookie_header = "; ".join(f"{k}={v}" for k, v in cookie_dict.items())
        api_url = "https://dm.terabox.com"

        session = get_upload_session()
        base_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Cookie": cookie_header,
            "Referer": f"{api_url}/main"
        }

        size = os.path.getsize(filepath)
        filename = unicodedata.normalize("NFKD", os.path.basename(filepath)).encode("ascii", "ignore").decode()
        if not filename:
            filename = f"file_{int(time.time())}"

        hashes = await asyncio.to_thread(self._terabox_hash_file, filepath, size)
        chunk_size = hashes["chunk_size"]
        js_token = await self._terabox_get_js_token(session, cookie_header, api_url)

        # 1. Precreate
        remote_file_path = f"{remote_dir}/{filename}".replace("//", "/")
        precreate_url = f"{api_url}/api/precreate"
        pre_params = {
            "app_id": "250528",
            "web": "1",
            "channel": "dubox",
            "clienttype": "0",
        }
        if js_token:
            pre_params["jsToken"] = js_token

        pre_data = {
            "path": remote_file_path,
            "autoinit": "1",
            "size": str(size),
            "file_limit_switch_v34": "true",
            "block_list": json.dumps(hashes["chunks"]),
            "rtype": "2",
            "content-md5": hashes["file"],
            "slice-md5": hashes["slice"],
            "content-crc32": str(hashes["crc32"])
        }

        try:
            async with session.post(precreate_url, params=pre_params, data=pre_data, headers=base_headers, timeout=30) as resp:
                pre_res = await resp.json(content_type=None)
        except Exception as e:
            LOGGER.error(f"Terabox Precreate HTTP error: {e}")
            return None

        if pre_res.get("errno") != 0:
            LOGGER.error(f"Terabox Precreate error: {pre_res}")
            return None

        upload_id = pre_res.get("uploadid")

        # 2. Locate Upload Host
        locate_url = f"{api_url}/rest/2.0/pcs/file?method=locateupload"
        try:
            async with session.get(locate_url, headers=base_headers, timeout=15) as resp:
                loc_res = await resp.json(content_type=None)
                upload_host = f"https://{loc_res['host']}"
        except Exception as e:
            LOGGER.error(f"Terabox Locate Upload Host error: {e}")
            return None

        # 3. Upload Chunks
        total_chunks = len(hashes["chunks"])
        bytes_uploaded = 0
        upload_chunk_url = f"{upload_host}/rest/2.0/pcs/superfile2"

        from bot.helpers.ui_manager import progress_message, GLOBAL_CANCEL_DICT

        with open(filepath, "rb") as f:
            for i in range(total_chunks):
                if details and details.get('task_id') in GLOBAL_CANCEL_DICT:
                    LOGGER.warning(f"Terabox Upload dibatalkan oleh pengguna: {filename}")
                    try:
                        from bot.helpers.message import edit_message
                        if 'msg' in details:
                            await edit_message(details['msg'], "🛑 **Proses Dibatalkan oleh Pengguna.**", None, False)
                    except Exception:
                        pass
                    raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")

                chunk_bytes = f.read(chunk_size)
                chunk_len = len(chunk_bytes)

                chunk_params = {
                    "method": "upload",
                    "app_id": "250528",
                    "path": remote_file_path,
                    "uploadid": upload_id,
                    "partseq": str(i)
                }

                chunk_form = aiohttp.FormData()
                chunk_form.add_field("file", chunk_bytes, filename="blob", content_type="application/octet-stream")

                chunk_uploaded = False
                for attempt in range(4):
                    try:
                        async with session.post(upload_chunk_url, params=chunk_params, data=chunk_form, headers=base_headers, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                            res = await resp.json(content_type=None)
                            if res.get("md5"):
                                chunk_uploaded = True
                                break
                    except Exception as e:
                        if attempt == 3:
                            LOGGER.error(f"Terabox chunk {i} upload error: {e}")
                        await asyncio.sleep(2)

                if not chunk_uploaded:
                    LOGGER.error(f"Terabox gagal mengunggah chunk {i}/{total_chunks}")
                    return None

                bytes_uploaded += chunk_len
                if details:
                    await progress_message(bytes_uploaded, size, details)

        # 4. Create File
        create_url = f"{api_url}/api/create"
        create_data = {
            "path": remote_file_path,
            "size": str(size),
            "isdir": "0",
            "content-md5": hashes["file"],
            "slice-md5": hashes["slice"],
            "content-crc32": str(hashes["crc32"]),
            "block_list": json.dumps(hashes["chunks"]),
            "uploadid": upload_id,
            "rtype": "2"
        }
        try:
            async with session.post(create_url, data=create_data, headers=base_headers, timeout=30) as resp:
                create_res = await resp.json(content_type=None)
                if create_res.get("errno") != 0:
                    LOGGER.error(f"Terabox create file failed: {create_res}")
                    return None
        except Exception as e:
            LOGGER.error(f"Terabox create file error: {e}")
            return None

        # 5. Share File
        return await self.terabox_share(remote_file_path, cookie_raw)

    # Tambahkan ini di dalam kelas DirectUpload (di bawah metode _upload_viking_aiohttp)
    async def _upload_transferit_subprocess(self, filepath, details):
        import sys, tempfile, re
        
        filename = os.path.basename(filepath)
        state_file = os.path.join(tempfile.gettempdir(), f"tf_{os.urandom(4).hex()}.json")
        script_path = os.path.join(os.getcwd(), "transferit_upload.py")
        
        # Mengeksekusi script headless uploader bawaan
        cmd = [sys.executable, script_path, "-v", "--state", state_file, str(filepath)]
        
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Membaca stderr untuk Radar UI Progress
            async def parse_stderr():
                try:
                    from bot.helpers.ui_manager import GLOBAL_CANCEL_DICT, GLOBAL_TASKS
                    import time
                    
                    while True:
                        line = await process.stderr.readline()
                        if not line:
                            break
                            
                        if details and 'task_id' in details:
                            if details['task_id'] in GLOBAL_CANCEL_DICT:
                                process.terminate()
                                raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")
                                
                        line_str = line.decode().strip()
                        
                        # Menangkap log: "POST namafile: 10/50 MiB (5.00 MiB/s)"
                        if "POST" in line_str and "MiB" in line_str:
                            task_id = details.get('task_id') if details else None
                            if task_id and task_id in GLOBAL_TASKS:
                                GLOBAL_TASKS[task_id]['timestamp'] = time.time()
                                GLOBAL_TASKS[task_id]['action'] = 'Uploading'
                                GLOBAL_TASKS[task_id]['machine'] = 'Transfer.it CLI'
                                
                                match = re.search(r'(\d+)/(\d+)\s+MiB', line_str)
                                if match:
                                    sent = int(match.group(1)) * 1024 * 1024
                                    total = int(match.group(2)) * 1024 * 1024
                                    GLOBAL_TASKS[task_id]['processed'] = f"{match.group(1)} MiB of {match.group(2)} MiB"
                                    
                                    if total > 0:
                                        pct = (sent / total) * 100
                                        filled = int((pct / 100) * 12)
                                        GLOBAL_TASKS[task_id]['progress_bar'] = "■" * filled + "□" * (12 - filled)
                                        GLOBAL_TASKS[task_id]['percentage'] = f"{pct:.2f}%"
                except Exception as e:
                    LOGGER.debug(f"Transfer.it stderr parser error: {e}")

            # Jalankan pembacaan stderr di background
            stderr_task = asyncio.create_task(parse_stderr())
            
            # Baca stdout secara manual agar tidak mencoba membaca stderr yang memicu error
            stdout_data = await process.stdout.read()
            
            # Tunggu proses script selesai
            await process.wait()
            
            # Batalkan task stderr jika masih menggantung
            if not stderr_task.done():
                stderr_task.cancel()
            
            if os.path.exists(state_file):
                os.remove(state_file)
                
            if process.returncode == 0:
                output = stdout_data.decode().strip().split('\n')
                for line in output:
                    if "https://transfer.it/t/" in line:
                        return line.strip()
            
            return None
            
        except asyncio.CancelledError:
            if 'process' in locals() and process.returncode is None:
                process.terminate()
            if os.path.exists(state_file):
                os.remove(state_file)
            raise
        except Exception as e:
            LOGGER.error(f"Transfer.it Subprocess Error: {e}")
            if os.path.exists(state_file):
                os.remove(state_file)
            return None

    # ============================
    # PUBLIC METHODS (Perbarui metode upload ini)
    # ============================
    async def upload(self, file_name, size, upload_type, specific_folder_id=None, details=None):
        # Pengecekan baru: Jika file_name kosong, eksekusi seluruh isi folder
        if file_name:
            filepath = os.path.join(self.path, file_name)
        else:
            filepath = self.path
            
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

        elif upload_type in ['pd', 'pixeldrain']:
            token = self.user_dict.get("pixeldrain", {}).get("api")
            LOGGER.info(f"Uploading Pixeldrain (Aiohttp): {file_name}")
            link = await self._upload_pixeldrain_aiohttp(filepath, token, details)
            return {'Pixeldrain': link} if link else None

        elif upload_type in ['tb', 'terabox']:
            cookie = self.user_dict.get("terabox", {}).get("cookie")
            if cookie:
                remote_dir = specific_folder_id or "/"
                LOGGER.info(f"Uploading Terabox (Aiohttp): {file_name}")
                link = await self._upload_terabox_aiohttp(filepath, cookie, remote_dir=remote_dir, details=details)
                return {'Terabox': link} if link else None

        # Tambahan baru untuk Transfer.it
        elif upload_type in ['tf', 'transferit']:
            LOGGER.info(f"Uploading Transfer.it: {file_name}")
            link = await self._upload_transferit_subprocess(filepath, details)
            return {'Transfer.it': link} if link else None

        return None
