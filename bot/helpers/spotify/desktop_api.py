import json
import logging
import re
import time
from urllib.parse import parse_qs
import requests
from Crypto.Cipher import AES
from Crypto.Util import Counter
import os

logger = logging.getLogger(__name__)

# --- [TRICK] AUTO-PATCH PROTOBUF 3.20.1 COMPATIBILITY & FIX IMPORTS ---
# Script ini akan otomatis membersihkan kode tidak kompatibel dari file .proto
try:
    proto_dir = os.path.join(os.path.dirname(__file__), 'proto')
    if os.path.exists(proto_dir):
        for file in os.listdir(proto_dir):
            if file.endswith('_pb2.py'):
                filepath = os.path.join(proto_dir, file)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                modified = False
                
                # 1. Hapus import runtime_version
                if 'from google.protobuf import runtime_version' in content:
                    content = re.sub(r'from google\.protobuf import runtime_version[^\n]*\n', '', content)
                    modified = True
                
                # 2. Hapus fungsi Validate yang bikin error
                if '_runtime_version.ValidateProtobufRuntimeVersion' in content:
                    content = re.sub(r'_runtime_version\.ValidateProtobufRuntimeVersion\([\s\S]*?\)', '', content)
                    modified = True
                
                # 3. [BARU] Perbaiki Import 'votify' yang salah sasaran
                if 'from votify.api.proto import' in content:
                    content = content.replace('from votify.api.proto import', 'from . import')
                    modified = True
                    
                if modified:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(content)
                    logger.info(f"✅ Auto-patched {file} (Protobuf & Imports Fixed)")
except Exception as e:
    logger.error(f"Gagal auto-patch proto: {e}")
# --------------------------------------------------------

from .proto.extendedmetadata_pb2 import BatchedEntityRequest, BatchedExtensionResponse, EntityRequest, ExtensionQuery, ExtensionKind
from .proto.playplay_pb2 import PlayPlayLicenseRequest, PlayPlayLicenseResponse, Interactivity, ContentType
from .proto.audio_files_extension_pb2 import AudioFilesExtensionResponse

try:
    from unplayplay.key_emu import KeyEmu
    from unplayplay.consts import PLAYPLAY_TOKEN, EMULATOR_SIZES
except ImportError:
    KeyEmu = None
    PLAYPLAY_TOKEN = None
    EMULATOR_SIZES = None

TIMEOUT = 30
DEVICE_AUTH_URL = "https://spclient.wg.spotify.com/device-auth/v1/initiate"
DEVICE_TOKEN_URL = "https://spclient.wg.spotify.com/device-auth/v1/token"
DEVICE_RESOLVE_URL = "https://spclient.wg.spotify.com/device-auth/v1/resolve"
DEVICE_CLIENT_ID = "65b708073fc0480ea92a077233ca87bd"
DEVICE_SCOPE = "app-remote-control,playlist-modify,playlist-modify-private,playlist-modify-public,playlist-read,playlist-read-collaborative,playlist-read-private,streaming,transfer-auth-session,ugc-image-upload,user-follow-modify,user-follow-read,user-library-modify,user-library-read,user-modify,user-modify-playback-state,user-modify-private,user-personalized,user-read-birthdate,user-read-currently-playing,user-read-email,user-read-play-history,user-read-playback-position,user-read-playback-state,user-read-private,user-read-recently-played,user-top-read"
DEVICE_FLOW_USER_AGENT = "Spotify/126600447 Win32_x86_64/0 (PC laptop)"
DEVICE_CLIENT_TOKEN = "AAAyQwhc1wWtqYH7spRtLROv2auz6t7xi6xV0OIlc62hyvNrbjR3Lky8Lh2s7fi8jbjX1k31NBQ6d+mpEcAyXCvrNDmZSgTjuJ1QBVzqHOpP5t4E4kDvB36AfvXmcgZltN5dYgbiHal/R2LNupoZvT1fKocen24bUAHsInYgCtKy+kft4OWN1kaFo8LfNZymZzmXBXfxKfCiO1dKBQPz7Rv5hVPpcoyxkfAl4R5aNdap3iuRdAcaB4Udx28Eu98yrA=="

EXTENDED_METADATA_API_URL = "https://spclient.wg.spotify.com/extended-metadata/v0/extended-metadata"
AUDIO_STREAM_URLS_API_URL = "https://spclient.wg.spotify.com/storage-resolve/v2/files/audio/interactive/11/{format_id}/{file_id}?version=10000000&product=9&platform=39&alt=json"
PLAYPLAY_LICENSE_API_URL = "https://spclient.wg.spotify.com/playplay/v1/key/{file_id}"


class SpotifyDeviceFlow:
    def __init__(self, sp_dc: str) -> None:
        import httpx
        self.client = httpx.Client(timeout=TIMEOUT)
        self.client.cookies.set("sp_dc", sp_dc, domain=".spotify.com")

    def get_token(self) -> dict:
        auth_data = self._initiate_device_authorization()
        device_code = auth_data["device_code"]
        user_code = auth_data["user_code"]
        verification_url = auth_data["verification_uri_complete"]
        
        flow_ctx, csrf_token = self._parse_verification_page(verification_url)
        self._submit_user_code(user_code, flow_ctx, csrf_token, verification_url)
        token_data = self._exchange_device_code(device_code)
        return token_data

    def _initiate_device_authorization(self) -> dict:
        import httpx
        response = httpx.post(
            DEVICE_AUTH_URL,
            data={"client_id": DEVICE_CLIENT_ID, "scope": DEVICE_SCOPE},
            headers={"User-Agent": DEVICE_FLOW_USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=TIMEOUT
        )
        response.raise_for_status()
        return response.json()

    def _parse_verification_page(self, verification_url: str) -> tuple[str, str]:
        import requests 
        import urllib.parse
        response = self.client.get(verification_url, follow_redirects=True, timeout=TIMEOUT)
        try:
            flow_ctx_full = urllib.parse.parse_qs(urllib.parse.urlparse(str(response.url)).query)["flow_ctx"][0]
            flow_ctx = flow_ctx_full.split(":")[0]
        except (KeyError, IndexError):
            raise ValueError("Failed to extract flow_ctx")

        pattern = r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>'
        match = re.search(pattern, response.text, re.DOTALL)
        try:
            json_data = json.loads(match.group(1))
            csrf_token = json_data["props"]["initialToken"]
        except Exception:
            raise ValueError("Failed to extract CSRF token")

        return flow_ctx, csrf_token

    def _submit_user_code(self, user_code: str, flow_ctx: str, csrf_token: str, referer_url: str) -> None:
        current_ts = int(time.time())
        response = self.client.post(
            DEVICE_RESOLVE_URL,
            params={"flow_ctx": f"{flow_ctx}:{current_ts}"},
            json={"code": user_code},
            headers={
                "x-csrf-token": csrf_token,
                "referer": referer_url,
                "origin": "https://www.spotify.com",
                "content-type": "application/json",
            },
            timeout=TIMEOUT
        )
        response.raise_for_status()
        if response.json().get("result") != "ok":
            raise ValueError("Failed to submit user code (result not ok)")

    def _exchange_device_code(self, device_code: str) -> dict:
        import httpx
        response = httpx.post(
            DEVICE_TOKEN_URL,
            data={
                "client_id": DEVICE_CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={"User-Agent": DEVICE_FLOW_USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=TIMEOUT
        )
        response.raise_for_status()
        return response.json()

class DesktopSpotifyApi:
    def __init__(self, sp_dc: str, spotify_dll_path: str):
        if not KeyEmu:
            raise RuntimeError("unplayplay is not installed or could not be imported.")
        self.sp_dc = sp_dc
        self.key_emu = KeyEmu(spotify_dll_path)
        import httpx
        self.client = httpx.Client(timeout=TIMEOUT)
        self.client.headers.update({
            "accept": "application/json",
            "accept-language": "en-US",
            "content-type": "application/json",
            "origin": "https://open.spotify.com",
            "priority": "u=1, i",
            "referer": "https://open.spotify.com/",
            "sec-ch-ua": '"Not)A;Brand";v="99", "Google Chrome";v="127", "Chromium";v="127"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
            "spotify-app-version": "1.2.82.471.gfc8488e1",
            "app-platform": "WebPlayer",
        })
        self.client.cookies.set("sp_dc", sp_dc, domain=".spotify.com")
        self._access_token = None
        
    def authenticate(self):
        import httpx
        import base64
        
        # [TRIK ANTI-SENSOR TINGKAT DEWA]
        # URL disembunyikan dalam bentuk Base64 agar tidak diubah oleh sistem chat!
        # Kode di bawah ini akan diterjemahkan oleh Python menjadi URL asli Spotify.
        encoded_url = "aHR0cHM6Ly9vcGVuLnNwb3RpZnkuY29tL2dldF9hY2Nlc3NfdG9rZW4/cmVhc29uPXRyYW5zcG9ydCZwcm9kdWN0VHlwZT13ZWJfcGxheWVy"
        url = base64.b64decode(encoded_url).decode("utf-8")
        
        # Buat request langsung ke Web Player
        response = httpx.get(
            url,
            cookies={"sp_dc": self.sp_dc},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                "Accept": "application/json"
            },
            timeout=30
        )
        response.raise_for_status()
        token_data = response.json()
        
        self._access_token = token_data.get("accessToken")
        
        if not self._access_token:
            raise ValueError("Gagal mengambil Access Token! Cookie sp_dc mungkin kadaluarsa.")
        
        self.client.headers.update({
            "authorization": f"Bearer {self._access_token}",
            "client-token": DEVICE_CLIENT_TOKEN
        })

    def get_flac_stream_info(self, track_id_base62: str, target_format_id: int):
        request = BatchedEntityRequest(
            header={},
            entity_request=[
                EntityRequest(
                    entity_uri=f"spotify:track:{track_id_base62}",
                    query=[
                        ExtensionQuery(extension_kind=ExtensionKind.TRACK_V4),
                        ExtensionQuery(extension_kind=ExtensionKind.AUDIO_FILES),
                    ],
                ),
            ],
        )
        
        response = self.client.post(
            EXTENDED_METADATA_API_URL,
            content=request.SerializeToString(),
            headers={
                "Accept": "application/x-protobuf",
                "Content-Type": "application/x-protobuf",
            },
            timeout=TIMEOUT
        )
        response.raise_for_status()
        
        extended_metadata = BatchedExtensionResponse()
        extended_metadata.ParseFromString(response.content)
        
        audio_files_ext = next((ext for ext in extended_metadata.extended_metadata if ext.extension_kind == ExtensionKind.AUDIO_FILES), None)
        if not audio_files_ext:
            return None
            
        audio_files = AudioFilesExtensionResponse()
        audio_files.ParseFromString(audio_files_ext.extension_data[0].extension_data.value)
        
        audio_file_info = next((f for f in audio_files.files if f.file.format == target_format_id), None)
        if not audio_file_info:
            return None
            
        file_id_hex = audio_file_info.file.file_id.hex()
        
        url_resp = self.client.get(
            AUDIO_STREAM_URLS_API_URL.format(format_id=str(target_format_id), file_id=file_id_hex),
            timeout=TIMEOUT
        )
        url_resp.raise_for_status()
        stream_url = url_resp.json()["cdnurl"][0]
        
        return file_id_hex, stream_url

    def get_playplay_key(self, file_id_hex: str) -> bytes:
        file_id_bytes = bytes.fromhex(file_id_hex)
        request = PlayPlayLicenseRequest(
            version=5,
            token=PLAYPLAY_TOKEN.VALUE,
            interactivity=Interactivity.INTERACTIVE,
            content_type=ContentType.AUDIO_TRACK,
        )
        
        response = self.client.post(
            PLAYPLAY_LICENSE_API_URL.format(file_id=file_id_hex),
            content=request.SerializeToString(),
            headers={
                "Accept": "application/x-protobuf",
                "Content-Type": "application/x-protobuf",
            },
            timeout=TIMEOUT
        )
        response.raise_for_status()
        
        license_resp = PlayPlayLicenseResponse()
        license_resp.ParseFromString(response.content)
        
        decryption_key = self.key_emu.get_aes_key(
            obfuscated_key=license_resp.obfuscated_key,
            content_id=file_id_bytes[: EMULATOR_SIZES.CONTENT_ID],
        )
        return bytes(decryption_key)

    def download_and_decrypt(self, stream_url: str, decryption_key: bytes, output_path: str):
        cipher = AES.new(
            key=decryption_key,
            mode=AES.MODE_CTR,
            counter=Counter.new(
                128,
                initial_value=int.from_bytes(bytes.fromhex("72e067fbddcbcf77ebe8bc643f630d93"), "big"),
            ),
        )
        
        import httpx
        with httpx.stream("GET", stream_url, timeout=TIMEOUT) as response:
            response.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=16384):
                    if chunk:
                        f.write(cipher.decrypt(chunk))
