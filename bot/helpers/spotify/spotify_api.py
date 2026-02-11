import json
import traceback
import os
import requests
import argparse
import logging
import time
import tempfile
import re
import sys
import io
import contextlib
import webbrowser
import secrets
import base64
import hashlib
import weakref

# --- [WAJIB] Import Dataclass ---
from config import Config
from dataclasses import dataclass
from typing import List, Optional, Tuple

from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import urlencode, urlparse, parse_qs

# Librespot imports
from librespot.core import Session as LibrespotSession
from librespot.proto import Authentication_pb2
import librespot.core
from librespot.metadata import TrackId, EpisodeId
from librespot.audio.decoders import AudioQuality as LibrespotAudioQualityEnum, VorbisOnlyAudioQuality
from librespot.core import TokenProvider as LibrespotTokenProvider 
from librespot.mercury import MercuryClient

# Store reference to original LibrespotTokenProvider before any patching
_OriginalLibrespotTokenProvider = librespot.core.TokenProvider

# --- [PERBAIKAN FINAL] KONEKSI MONGODB (ANTI-ERROR NO DEFAULT DB) ---
try:
    from pymongo import MongoClient
except ImportError:
    MongoClient = None

# [FIX] AMBIL DARI CONFIG, BUKAN OS.ENVIRON
# Agar sesuai dengan mongo_async.py kamu
MONGODB_URI = getattr(Config, "DATABASE_URL", None) 
mongo_collection = None

if MONGODB_URI and MongoClient:
    try:
        # Cek apakah URL valid untuk MongoDB
        if "mongodb" in MONGODB_URI:
            client = MongoClient(MONGODB_URI)
            
            # [FIX UTAMA] Paksa nama database agar konsisten
            # Gunakan nama DB yang sama dengan variable BOT_USERNAME di config kamu (biar rapi)
            db_name = getattr(Config, "BOT_USERNAME", "spotify_bot_db")
            db = client[db_name]
            
            mongo_collection = db["spotify_credentials"] # Koleksi khusus credential
            logging.getLogger(__name__).info(f"✅ MongoDB Sync Terhubung ke Database: '{db_name}'")
        else:
            logging.getLogger(__name__).warning("⚠️ DATABASE_URL bukan format MongoDB. Auto-Save dimatikan.")
    except Exception as e:
        logging.getLogger(__name__).error(f"❌ Gagal koneksi MongoDB Sync: {e}")
else:
    if not MongoClient:
        logging.getLogger(__name__).warning("⚠️ Module 'pymongo' tidak terinstall.")
    elif not MONGODB_URI:
        logging.getLogger(__name__).warning("⚠️ Config.DATABASE_URL kosong/tidak ditemukan.")

# --- MANUAL CLASS: STORED TOKEN (VERSI PINTAR) ---
class StoredToken:
    def __init__(self, access_token_or_dict, expires_in=None, refresh_token=None, expires_at=None, spotify_username=None, scope=None, **kwargs):
        # 1. Logika Pintar: Cek apakah input pertama adalah Dictionary
        if isinstance(access_token_or_dict, dict):
            data = access_token_or_dict
            self.access_token = data.get("access_token")
            # Default expires_in ke 3600 jika tidak ada
            self.expires_in = int(data.get("expires_in", 3600))
            self.refresh_token = data.get("refresh_token")
            self.spotify_username = data.get("spotify_username")
            
            # Handle Scope
            scope_val = data.get("scope")
            if isinstance(scope_val, str):
                self.scopes = scope_val.split()
            else:
                self.scopes = scope_val or []
            
            # Hitung expires_at otomatis
            if data.get("expires_at"):
                self.expires_at = int(data["expires_at"])
            else:
                self.expires_at = int(time.time()) + self.expires_in
        else:
            # 2. Logika Biasa: Input argumen terpisah
            self.access_token = access_token_or_dict
            self.expires_in = int(expires_in) if expires_in else 3600
            self.refresh_token = refresh_token
            self.spotify_username = spotify_username
            self.scopes = scope.split() if isinstance(scope, str) else (scope or [])
            
            if expires_at:
                self.expires_at = int(expires_at)
            else:
                self.expires_at = int(time.time()) + self.expires_in

    def expired(self):
        return int(time.time()) > (self.expires_at - 30)

    @classmethod
    def from_dict(cls, data):
        return cls(data)
        
    def to_dict(self):
        return {
            "access_token": self.access_token,
            "expires_in": self.expires_in,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "spotify_username": self.spotify_username,
            "scope": " ".join(self.scopes)
        }

# --- DATA STRUCTURES (LENGKAP DENGAN DOWNLOADTYPEENUM) ---

@dataclass
class Tags:
    album_artist: str = None
    track_number: int = None
    total_tracks: int = None
    disc_number: int = None
    release_date: str = None
    year: str = None

@dataclass
class CodecOptions:
    format: str = "OGG"

class QualityEnum:
    HIGH = "HIGH"

class CodecEnum:
    VORBIS = "VORBIS"

# [PERBAIKAN UTAMA] Menambahkan class ini agar tidak Error NameError
class DownloadTypeEnum:
    track = "track"
    album = "album"
    playlist = "playlist"
    artist = "artist"
    episode = "episode"
    show = "show"

@dataclass
class TrackInfo:
    name: str
    id: str
    artists: List[str]
    album: str
    duration: int
    cover_url: str
    release_year: str = ""
    explicit: bool = False
    tags: Tags = None
    codec: str = None
    artist_id: str = None
    album_id: str = None
    gid_hex: str = None
    # Field Tambahan untuk Caption & Handler
    quality: str = None
    provider: str = None
    release_date: str = None
    total_tracks: str = None
    total_volumes: int = 1
    explicit_str: str = "No"

@dataclass
class TrackDownloadInfo:
    download_type: str
    temp_file_path: str
    file_url: str

class DownloadEnum:
    TEMP_FILE_PATH = "TEMP_FILE_PATH"

@dataclass
class AlbumInfo:
    name: str
    artist: str
    tracks: List[TrackInfo]
    all_track_cover_jpg_url: str
    release_year: str
    id: str
    small_cover_url: str = None  # <--- [FIX ZIP] Field Baru untuk Thumbnail

@dataclass
class PlaylistInfo:
    name: str
    creator: str
    tracks: List[TrackInfo]
    cover_url: str
    id: str
    small_cover_url: str = None  # <--- [FIX ZIP] Field Baru untuk Thumbnail

@dataclass
class ArtistInfo:
    name: str
    albums: List[AlbumInfo] = None
    id: str = None
    
# OAuth constants
API_URL = "https://api.spotify.com/v1/"
AUTH_URL = "https://accounts.spotify.com/"
REDIRECT_URI = "http://127.0.0.1:4381/login"
CLIENT_ID = "65b708073fc0480ea92a077233ca87bd"
OAUTH_SCOPES = [
    "streaming",
    "user-read-email",
    "user-read-private",
    "playlist-read",
    "playlist-read-collaborative",
    "playlist-read-private",
    "user-library-read",
    "user-read-playback-state",
    "user-read-currently-playing",
    "user-read-recently-played",
    "user-read-playback-position",
    "user-top-read"
]
DEFAULT_REQUEST_TIMEOUT = 15 # seconds
DESKTOP_CLIENT_ID = "65b708073fc0480ea92a077233ca87bd" 
SPOTIFY_TOKEN_URL = "https://api.spotify.com/api/token" 
CREDENTIALS_FILE_NAME = "credentials.json"



# --- PKCE Helper Functions ---
def generate_code_verifier(length=64) -> str:
    # KITA PAKSA KUNCI STATIS AGAR TIDAK BERUBAH SAAT RESTART
    return "MonomarsxBot_Static_Verifier_Secret_Key_2026_Fixed" 

def get_code_challenge(verifier: str) -> str:
    """Create a PKCE code challenge from a code verifier."""
    digest = hashlib.sha256(verifier.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('utf-8')

# --- OAuth Classes ---
class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handles the OAuth callback from Spotify."""
    def __init__(self, *args, **kwargs):
        self.access_code_payload = None
        self.error_payload = None
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        if "code=" in format % args or "error=" in format % args:
            logging.info(f"OAuthCallbackHandler: {format % args}")
        pass # Suppress other logs

    def do_GET(self):
        query_components = parse_qs(urlparse(self.path).query)
        if 'code' in query_components:
            self.access_code_payload = query_components["code"][0]
            message = "<html><body><h1>Authentication Successful!</h1><p>You can close this window.</p></body></html>"
        elif 'error' in query_components:
            self.error_payload = query_components["error"][0]
            message = f"<html><body><h1>Authentication Failed</h1><p>Error: {self.error_payload}. You can close this window.</p></body></html>"
        else:
            message = "<html><body><h1>Waiting for Spotify...</h1><p>Please complete the authorization in your browser.</p></body></html>"
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))
        if self.access_code_payload:
            self.server.access_code_payload = self.access_code_payload
        if self.error_payload:
            self.server.error_payload = self.error_payload

class OAuth:
    """Handles the PKCE OAuth flow for Spotify."""
    def __init__(self, client_id: str, redirect_uri: str, scopes: List[str], logger_instance=None, client_secret: Optional[str] = None):
        self.client_id = client_id
        self.client_secret = client_secret  # Optional: needed for token refresh with custom client_id
        self.redirect_uri = redirect_uri
        self.scopes_list = scopes
        self.logger = logger_instance if logger_instance else logging.getLogger(__name__ + ".OAuth")
        parsed_uri = urlparse(redirect_uri)
        self.server_address = (parsed_uri.hostname, parsed_uri.port)
        self.http_server: Optional[HTTPServer] = None
        self.server_thread: Optional[Thread] = None
        self.code_verifier: Optional[str] = None
        self.access_code: Optional[str] = None
        self.error_message: Optional[str] = None

    def _start_http_server(self):
        # --- PERBAIKAN: Bikin class sementara biar bisa reuse port ---
        class ReusableHTTPServer(HTTPServer):
            allow_reuse_address = True
        # -------------------------------------------------------------

        self.http_server = ReusableHTTPServer(self.server_address, OAuthCallbackHandler)
        self.http_server.access_code_payload = None 
        self.http_server.error_payload = None
        
        self.http_server.oauth_handler = self

        self.server_thread = Thread(target=self.http_server.serve_forever, daemon=True)
        self.server_thread.start()
        self.logger.info(f"OAuth callback server started at {self.redirect_uri}")

    def _stop_http_server(self):
        if self.http_server:
            self.http_server.shutdown()
            self.http_server.server_close() 
            self.logger.info("OAuth callback server stopped.")
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2)
            if self.server_thread.is_alive():
                self.logger.warning("OAuth server thread did not shut down cleanly.")

    def get_authorization_url(self) -> str:
        self.code_verifier = generate_code_verifier()
        code_challenge = get_code_challenge(self.code_verifier)
        params = {
            'client_id': self.client_id,
            'response_type': 'code',
            'redirect_uri': self.redirect_uri,
            'scope': ' '.join(self.scopes_list),
            'code_challenge_method': 'S256',
            'code_challenge': code_challenge,
        }
        return AUTH_URL + "authorize?" + urlencode(params)

    def exchange_code_for_token(self, code: str) -> Optional[dict]:
        if not self.code_verifier:
            self.logger.error("Code verifier is not set. Cannot exchange code.")
            return None
        payload = {
            'client_id': self.client_id,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': self.redirect_uri,
            'code_verifier': self.code_verifier,
        }
        try:
            response = requests.post(AUTH_URL + "api/token", data=payload, timeout=DEFAULT_REQUEST_TIMEOUT)
            response.raise_for_status()
            token_data = response.json()
            self.logger.info("Successfully exchanged authorization code for token.")
            return token_data
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"HTTP error exchanging code for token: {e.response.status_code} - {e.response.text}")
            if e.response.status_code == 400:
                try:
                    error_details = e.response.json()
                    self.logger.error(f"Spotify API error: {error_details.get('error')}, Description: {error_details.get('error_description')}")
                    self.error_message = f"{error_details.get('error')}: {error_details.get('error_description')}" 
                except json.JSONDecodeError:
                    self.error_message = e.response.text
            else:
                 self.error_message = e.response.text
            return None
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Request exception exchanging code for token: {e}")
            self.error_message = str(e)
            return None

    def refresh_access_token(self, refresh_token_str: str) -> Optional[dict]:
        payload = {
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token_str,
            'client_id': self.client_id,
        }
        # Add client_secret if available (needed for custom client_id token refresh)
        if self.client_secret:
            payload['client_secret'] = self.client_secret
        try:
            response = requests.post(AUTH_URL + "api/token", data=payload, timeout=DEFAULT_REQUEST_TIMEOUT)
            response.raise_for_status()
            new_token_data = response.json()
            if 'refresh_token' not in new_token_data and refresh_token_str:
                new_token_data['refresh_token'] = refresh_token_str 
            self.logger.info("Successfully refreshed access token.")
            return new_token_data
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"HTTP error refreshing token: {e.response.status_code} - {e.response.text}")
            self.error_message = e.response.text
            return None
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Request exception refreshing token: {e}")
            self.error_message = str(e)
            return None

    def perform_full_oauth_flow(self) -> Optional[dict]: # Returns token data
        self._start_http_server()
        auth_url = self.get_authorization_url()
        self.logger.info(f"Please authorize in your browser: {auth_url}")
        print(f"\nOpening browser for Spotify authorization...\nURL: {auth_url}")
        print(f"If the browser does not open, please copy the URL above and paste it manually.")
        print()  # Add empty line after authorization messages
        try:
            webbrowser.open(auth_url)
        except Exception as e_wb:
            self.logger.error(f"Could not open browser automatically: {e_wb}. Please open manually.")

        try:
            self.logger.info("Waiting for user authorization in browser...")
            timeout_seconds = 180 
            start_time = time.time()
            while self.http_server and not self.http_server.access_code_payload and not self.http_server.error_payload:
                if time.time() - start_time > timeout_seconds:
                    self.logger.warning("Timeout waiting for OAuth callback.")
                    self.error_message = "Timeout waiting for Spotify authorization."
                    break
                time.sleep(0.5) 
            
            self.access_code = self.http_server.access_code_payload if self.http_server else None
            self.error_message = self.http_server.error_payload if self.http_server else self.error_message 

        except KeyboardInterrupt:
            self.logger.warning("OAuth flow interrupted by user.")
            self.error_message = "User cancelled authorization."
            return None 
        finally:
            self._stop_http_server()

        if self.error_message:
            self.logger.error(f"OAuth flow failed: {self.error_message}")
            return None

        if self.access_code:
            self.logger.info(f"Received authorization code: {self.access_code[:20]}...")
            return self.exchange_code_for_token(self.access_code)
        else:
            self.logger.error("Did not receive an authorization code.")
            return None

# --- Exception Classes ---
class SpotifyApiError(Exception):
    """Custom exception for Spotify API errors."""
    pass

class SpotifyAuthError(SpotifyApiError):
    """Exception for authentication failures."""
    pass

class SpotifyConfigError(SpotifyApiError):
    """Exception for configuration errors."""
    pass

class SpotifyNeedsUserRedirectError(SpotifyAuthError):
    """Custom exception raised when user needs to authorize via URL."""
    def __init__(self, auth_url):
        self.auth_url = auth_url
        super().__init__(f"Spotify requires authorization. Please visit: {auth_url}")

class SpotifyLibrespotError(SpotifyAuthError):
    """Exception for errors during librespot interaction."""
    pass

class SpotifyTrackUnavailableError(SpotifyLibrespotError):
    """Raised when a track is unavailable."""
    pass

class SpotifyRateLimitDetectedError(SpotifyLibrespotError):
    """Raised when rate limit is detected."""
    pass

class SpotifyItemNotFoundError(SpotifyApiError):
    """Exception for when a specific item is not found."""
    pass

class SpotifyContentUnavailableError(SpotifyApiError):
    """Exception for content unavailable due to region restrictions."""
    pass

# Helper class (can be expanded if full PKCE flow is re-implemented elsewhere)
class PkceTokenDetails: # Simplified for current use if only access_token is managed by this script
    def __init__(self, access_token: str, expires_in: int = 3600, issued_at: Optional[int] = None):
        self.access_token = access_token
        self.expires_in = expires_in
        self.issued_at = issued_at if issued_at is not None else int(time.time())

    def is_expired(self, margin_seconds=60) -> bool:
        if not self.access_token or self.issued_at is None or self.expires_in is None:
            return True
        return (self.issued_at + self.expires_in - margin_seconds) < time.time()

# --- Custom Token Provider for Librespot (REINSTATING THIS SECTION) --- 
class LibrespotStoredTokenAdapter(LibrespotTokenProvider.StoredToken):
    """Adapts our StoredToken to what LibrespotTokenProvider.StoredToken expects."""
    def __init__(self, our_stored_token: StoredToken, logger_instance=None):
        self.logger = logger_instance if logger_instance else logging.getLogger(__name__ + ".LibrespotStoredTokenAdapter")
        if not our_stored_token:
            self.logger.error("CRITICAL_ADAPTER: our_stored_token is None during LibrespotStoredTokenAdapter init!")
            raise ValueError("our_stored_token cannot be None for LibrespotStoredTokenAdapter")
        
        self.timestamp = int(our_stored_token.timestamp / 1000) # Librespot expects seconds
        self.expires_in = our_stored_token.expires_in
        self.access_token = our_stored_token.access_token
        self.scopes = our_stored_token.scopes
        self.logger.debug(f"CRITICAL_ADAPTER: LibrespotStoredTokenAdapter initialized. AccessToken: {self.access_token[:20]}..., Timestamp (s): {self.timestamp}, ExpiresIn: {self.expires_in}")        

class SpotifyApiTokenProvider(LibrespotTokenProvider):
    """Custom TokenProvider that uses the OAuth token managed by SpotifyAPI."""
    _instance_counter = 0 # Class variable to count instances

    def __init__(self, session, spotify_api_instance: 'SpotifyAPI'):
        super().__init__(session) # Calls LibrespotTokenProvider.__init__(session)
        SpotifyApiTokenProvider._instance_counter += 1
        self.instance_id = SpotifyApiTokenProvider._instance_counter
        self._spotify_api_ref = weakref.ref(spotify_api_instance) 
        
        self.logger = spotify_api_instance.logger if spotify_api_instance else logging.getLogger(__name__ + ".SpotifyApiTokenProvider")
        self.logger.info(f"CUSTOM_TP_DEBUG (Instance {self.instance_id}): SpotifyApiTokenProvider initialized. Bound to SpotifyAPI ID: {id(spotify_api_instance)}, Librespot Session ID: {id(session)}")
        if spotify_api_instance: # ensure instance exists before trying to set attribute
            spotify_api_instance.last_custom_provider_id_created = self.instance_id

    def get_token(self, *scopes: str) -> _OriginalLibrespotTokenProvider.StoredToken:
        """
        Dipanggil oleh Librespot saat token habis (biasanya per 1 jam).
        [FIX] Menambahkan AUTO-REFRESH jika token di memori sudah expired.
        """
        # [FIX] Tambahkan TRY di sini untuk menangkap error
        try:
            spotify_api = self._spotify_api_ref()
            self.logger.info(f"CUSTOM_TP_DEBUG (Instance {self.instance_id}): get_token DIPANGGIL.")

            if not spotify_api or not hasattr(spotify_api, 'stored_token') or not spotify_api.stored_token:
                self.logger.error("SpotifyAPI instance atau stored_token tidak tersedia.")
                raise Exception("SpotifyAPI instance or stored_token not available")

            # --- LOGIKA AUTO REFRESH ---
            # Cek apakah token yang kita pegang sekarang sudah expired?
            if spotify_api.stored_token.expired():
                self.logger.warning("♻️ Token di Memory EXPIRED saat diminta Librespot. Melakukan Refresh...")
                
                # Panggil fungsi refresh internal
                if spotify_api.perform_token_refresh():
                    self.logger.info("✅ Token berhasil direfresh otomatis!")
                else:
                    self.logger.error("❌ Gagal refresh token otomatis. Koneksi mungkin akan putus.")
            
            # Ambil token (sekarang seharusnya sudah fresh)
            pkce_token_info = spotify_api.stored_token
            
            if not pkce_token_info.access_token:
                raise Exception("PKCE access_token is missing")

            # Gunakan scope aktual
            actual_scopes = pkce_token_info.scopes
            
            oauth_token_response = {
                "accessToken": pkce_token_info.access_token,
                "expiresIn": pkce_token_info.expires_in,
                "scope": actual_scopes
            }
            
            return _OriginalLibrespotTokenProvider.StoredToken(oauth_token_response)

        # [FIX] Pasangan except harus sejajar dengan try
        except Exception as e:
            self.logger.error(f"CUSTOM_TP_DEBUG (Instance {self.instance_id}): Gagal membuat StoredToken: {e}", exc_info=True)
            raise


    
class LibrespotAudioKeyFilter(logging.Filter):
    """Filter to suppress noisy librespot audio key error messages and rate limit warnings"""
    def filter(self, record):
        try:
            message = record.getMessage()
            message_lower = message.lower()
            logger_name_lower = record.name.lower()
            
            # Comprehensive suppression of audio key error messages
            suppress_patterns = [
                'audio key error',
                'failed fetching audio key',
                'audiokeymanager',
                'spotify rate limit detected during track download',
                'rate limit suspected: failed fetching audio key'
            ]
            
            # Check if any suppress pattern matches the message
            for pattern in suppress_patterns:
                if pattern in message_lower:
                    return False
            
            # Additional check for CRITICAL level messages with specific content
            if record.levelno >= logging.CRITICAL:
                critical_suppress_patterns = [
                    'audio key error',
                    'failed fetching audio key',
                    'code: 2'
                ]
                for pattern in critical_suppress_patterns:
                    if pattern in message_lower:
                        return False
            
            # Check logger name patterns
            logger_suppress_patterns = [
                'librespot',
                'audiokeymanager'
            ]
            
            for pattern in logger_suppress_patterns:
                if pattern in logger_name_lower:
                    # If it's from a librespot logger, check for audio key content
                    if ('audio key' in message_lower or 
                        'failed fetching' in message_lower or
                        'code: 2' in message_lower):
                        return False
            
            return True
            
        except Exception:
            # If there's any error in filtering, allow the message through
            return True

class SpotifyAPI:
    logger = logging.getLogger(__name__)

    _spotify_url_pattern = re.compile(r"^(?:https?://open\.spotify\.com/(?:(?:(track|album|artist|playlist|show|episode)/([a-zA-Z0-9]{22}))|(?:user/[^/]+/playlist/([a-zA-Z0-9]{22})))|spotify:(track|album|artist|playlist|show|episode):([a-zA-Z0-9]{22})|http://127\.0\.0\.1:4381/login\?code=.*)(?:\?.*)?$")

    def __init__(self, config=None, module_controller=None):
        self.config = config if config else {}
        self.module_controller = module_controller
        self.librespot_session: Optional[LibrespotSession] = None        
        self.user_market: Optional[str] = None
        
        # --- KONFIGURASI HYBRID (FIXED 403) ---
        
        # 1. Setup Public Client ID (WAJIB untuk Download)
        public_client_id = CLIENT_ID 
        
        # 2. Setup Custom Client ID (Opsional untuk Metadata agar hemat limit)
        custom_client_id = self.config.get("client_id")
        custom_client_secret = self.config.get("client_secret")
        
        if custom_client_id and custom_client_secret:
            self.logger.info(f"Web API: Menggunakan Custom ID ({custom_client_id[:10]}...) untuk Metadata.")
            web_api_oauth_client_id = custom_client_id
            web_api_oauth_client_secret = custom_client_secret
        else:
            web_api_oauth_client_id = public_client_id
            web_api_oauth_client_secret = None
            
        librespot_oauth_client_id = public_client_id
        librespot_oauth_client_secret = None
        
        # Scope Lengkap
        premium_scopes = [
            "user-read-email",
            "user-read-private",
            "playlist-read-private",
            "playlist-read-collaborative",
            "playlist-modify-private",
            "playlist-modify-public",
            "user-library-read",
            "user-library-modify",
            "user-read-playback-state",
            "user-modify-playback-state",
            "user-read-currently-playing",
            "user-read-recently-played",
            "user-read-playback-position",
            "user-top-read",
            "streaming", 
            "ugc-image-upload"
        ]
        
        # Handler 1: Custom ID (Untuk Info Lagu)
        self.web_api_oauth_handler: Optional[OAuth] = OAuth(web_api_oauth_client_id, REDIRECT_URI, premium_scopes, self.logger, client_secret=web_api_oauth_client_secret)
        
        # Handler 2: Public ID (Untuk Download)
        self.librespot_oauth_handler: Optional[OAuth] = OAuth(librespot_oauth_client_id, REDIRECT_URI, premium_scopes, self.logger, client_secret=librespot_oauth_client_secret)
        
        # --- PERBAIKAN UTAMA DI SINI ---
        # Saat user ketik /spotify_login, kita HARUS menggunakan handler LIBRESPOT (Public ID).
        # Agar token yang dihasilkan adalah token Public, yang diizinkan untuk download.
        self.oauth_handler: Optional[OAuth] = self.librespot_oauth_handler
        
        # Token Storage
        self.web_api_stored_token: Optional[StoredToken] = None
        self.librespot_stored_token: Optional[StoredToken] = None
        
        self.stored_token: Optional[StoredToken] = None
        self.last_custom_provider_id_created: Optional[int] = None

        # --- Setup Logging Filter ---
        audio_key_filter = LibrespotAudioKeyFilter()
        root_logger = logging.getLogger()
        root_logger.addFilter(audio_key_filter)
        for handler in root_logger.handlers:
            handler.addFilter(audio_key_filter)
        
        potential_logger_names = [
            'librespot', 'Librespot', 'LIBRESPOT',
            'librespot.core', 'Librespot.Core', 
            'librespot.audio', 'Librespot.Audio',
            'AudioKeyManager', 'audiokeymanager',
            'spotify', 'Spotify', 'modules.spotify',
            '__main__', 'root', '', 
        ]
        
        for logger_name in potential_logger_names:
            logger = logging.getLogger(logger_name)
            logger.addFilter(audio_key_filter)
            for handler in logger.handlers:
                handler.addFilter(audio_key_filter)
        
        self._audio_key_filter = audio_key_filter
        
        # Directory Config
        self.credentials_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "config", "spotify"))
        os.makedirs(self.credentials_dir, exist_ok=True) 
        self.credentials_file_path = os.path.join(self.credentials_dir, CREDENTIALS_FILE_NAME)       
        self.logger.info(f"Credentials will be stored/loaded from: {self.credentials_file_path}")

    def perform_token_refresh(self) -> bool:
        """
        Memaksa refresh token menggunakan Refresh Token yang ada dan menyimpannya.
        """
        # 1. Cek apakah kita punya Refresh Token
        if not self.stored_token or not self.stored_token.refresh_token:
            self.logger.error("Tidak bisa refresh: Refresh Token tidak ditemukan di memori.")
            return False

        try:
            # 2. Siapkan Data
            PUBLIC_ID = "65b708073fc0480ea92a077233ca87bd"
            
            payload = {
                "grant_type": "refresh_token", 
                "refresh_token": self.stored_token.refresh_token, 
                "client_id": PUBLIC_ID
            }
            
            # URL Token Resmi
            TOKEN_URL = "https://accounts.spotify.com/api/token" 
            
            self.logger.info("♻️ Mengirim permintaan Refresh Token ke Spotify...")
            
            # 3. Kirim Request
            resp = requests.post(TOKEN_URL, data=payload, timeout=10)
            
            # 4. Cek Hasil
            if resp.status_code == 200:
                new_data = resp.json()
                
                # Update data token
                self.stored_token.access_token = new_data['access_token']
                self.stored_token.expires_in = int(new_data['expires_in'])
                self.stored_token.expires_at = int(time.time()) + int(new_data['expires_in'])
                
                if 'refresh_token' in new_data:
                    self.stored_token.refresh_token = new_data['refresh_token']
                
                # Simpan agar sinkron
                username = self.stored_token.spotify_username or "SpotifyUser"
                self._save_credentials(self.stored_token, username)
                
                self.logger.info("✅ Refresh Token Sukses & Disimpan.")
                return True
            else:
                self.logger.error(f"❌ Gagal Refresh Token. Status: {resp.status_code}, Resp: {resp.text}")
                
                # [PERBAIKAN UTAMA DISINI]
                # Jika token REVOKED/INVALID, Hapus dari MongoDB juga agar tidak di-restore lagi
                if "invalid_grant" in resp.text or "revoked" in resp.text:
                    self.logger.critical("💀 Token Mati Total (Revoked). Membersihkan Database & File...")
                    
                    # 1. Hapus File Lokal
                    self._clear_credentials()
                    
                    # 2. HAPUS JUGA DARI MONGODB (PENTING!)
                    # Pastikan variabel mongo_collection bisa diakses (global scope file ini)
                    if mongo_collection is not None:
                        try:
                            mongo_collection.delete_one({"type": "spotify_auth"})
                            self.logger.info("🗑️ Data sampah di MongoDB berhasil dihapus.")
                        except Exception as e:
                            self.logger.error(f"Gagal hapus DB: {e}")

                return False
                
        except Exception as e:
            self.logger.error(f"❌ Exception saat perform_token_refresh: {e}")
            return False

    def _save_credentials(self, token_obj: StoredToken, username: Optional[str] = "PKCE_USER"):
        """Saves OAuth token data to JSON File AND MONGODB."""        
        if not token_obj or not token_obj.access_token:
            self.logger.error("Cannot save credentials, token object or access token is missing.")
            return

        # Siapkan Data Lengkap
        full_token_details_for_storage = token_obj.to_dict()
        full_token_details_for_storage['spotify_username'] = username 
        # Simpan client_id juga untuk validasi
        full_token_details_for_storage['client_id'] = self.oauth_handler.client_id if self.oauth_handler else None

        # 1. Simpan ke File Lokal (Agar bot bisa baca sekarang)
        try:
            with open(self.credentials_file_path, 'w') as f:
                json.dump(full_token_details_for_storage, f, indent=4)
            self.logger.info(f"Successfully saved full OAuth token details to {self.credentials_file_path}")
        except IOError as e:
            self.logger.error(f"IOError saving credentials to {self.credentials_file_path}: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error saving credentials to file: {e}", exc_info=True)

        # 2. [BARU] Simpan ke MongoDB (Agar aman dari Restart/Deploy)
        # Pastikan variabel mongo_collection sudah didefinisikan di bagian atas file
        if mongo_collection is not None:
            try:
                # Upsert: Update jika ada, Insert jika belum (berdasarkan "type": "spotify_auth")
                mongo_collection.update_one(
                    {"type": "spotify_auth"}, 
                    {"$set": {"data": full_token_details_for_storage}}, 
                    upsert=True
                )
                self.logger.info("✅ Kredensial berhasil disimpan ke MongoDB (Anti-Reset).")
            except Exception as e:
                self.logger.error(f"Gagal simpan ke DB: {e}")

    def _load_existing_credentials(self) -> bool:
        """
        Loads credentials from JSON file OR MONGODB.
        Jika file lokal hilang (efek restart), bot akan mencoba mengambil backup dari MongoDB.
        [UPDATED] URL Refresh Token diperbaiki ke Official API agar tidak gagal refresh.
        """
        
        token_data = None
        
        # 1. Cek File Lokal Terlebih Dahulu
        if os.path.exists(self.credentials_file_path):
            try:
                with open(self.credentials_file_path, 'r') as f: 
                    token_data = json.load(f)
            except Exception: 
                pass
        
        # 2. [FITUR ANTI-RESET] Jika File Gagal/Hilang, Coba Load dari MongoDB
        # Pastikan variabel mongo_collection sudah didefinisikan di bagian atas file
        if not token_data and mongo_collection is not None:
            self.logger.info("File kredensial hilang (efek restart). Mencoba memuat dari MongoDB...")
            try:
                # Cari dokumen dengan tipe 'spotify_auth'
                record = mongo_collection.find_one({"type": "spotify_auth"})
                if record and "data" in record:
                    token_data = record["data"]
                    self.logger.info("✅ Kredensial berhasil dipulihkan dari MongoDB!")
                    
                    # Tulis ulang ke file lokal agar library lain (librespot) bisa membacanya
                    try:
                        with open(self.credentials_file_path, 'w') as f:
                            json.dump(token_data, f, indent=4)
                    except Exception as e:
                        self.logger.warning(f"Gagal menulis ulang file kredensial: {e}")
            except Exception as e:
                self.logger.error(f"Error saat membaca database: {e}")

        # 3. Validasi & Load Token
        if token_data:
            try:
                # Validasi kelengkapan data
                if "access_token" not in token_data or "refresh_token" not in token_data:
                    self.logger.warning("Data kredensial tidak lengkap.")
                    return False

                # Gunakan .from_dict() sesuai perbaikan sebelumnya
                self.stored_token = StoredToken.from_dict(token_data)
                
                # Auto Refresh jika expired
                if self.stored_token.expired():
                    self.logger.info("⚠️ Token expired saat startup. Mencoba Refresh...")
                    
                    # Payload Refresh Token Standar (Public Client ID)
                    PUBLIC_ID = "65b708073fc0480ea92a077233ca87bd"
                    payload = {
                        "grant_type": "refresh_token", 
                        "refresh_token": self.stored_token.refresh_token, 
                        "client_id": PUBLIC_ID
                    }
                    
                    try:
                        # [FIX UTAMA DI SINI]
                        # Ganti URL Proxy lama dengan URL Resmi Spotify Account API
                        TOKEN_URL = "https://accounts.spotify.com/api/token"
                        
                        resp = requests.post(TOKEN_URL, data=payload, timeout=10)
                        
                        if resp.status_code == 200:
                            new_data = resp.json()
                            self.stored_token.access_token = new_data['access_token']
                            self.stored_token.expires_in = int(new_data['expires_in'])
                            self.stored_token.expires_at = int(time.time()) + int(new_data['expires_in'])
                            
                            # Jika Spotify memberikan refresh token baru (rotasi), simpan juga
                            if 'refresh_token' in new_data:
                                self.stored_token.refresh_token = new_data['refresh_token']
                            
                            # Simpan update token baru ke DB & File
                            username = token_data.get('spotify_username') or self.config.get('username')
                            self._save_credentials(self.stored_token, username)
                            
                            self.logger.info("✅ Token berhasil disegarkan & disimpan!")
                            return True
                        else:
                            self.logger.warning(f"❌ Gagal refresh token saat startup. Status: {resp.status_code} - {resp.text}")
                            return False
                    except Exception as e:
                        self.logger.error(f"❌ Error koneksi saat refresh token: {e}")
                        return False

                return True

            except Exception as e:
                self.logger.error(f"Error parsing token data: {e}")
                return False

        return False

    def _perform_oauth_flow(self):
        """
        Melakukan login OAuth PKCE Baru.
        """
        # 1. Update Scope
        scope = "user-read-email user-read-private playlist-read-private playlist-modify-private playlist-modify-public user-library-read user-library-modify user-read-playback-state user-modify-playback-state streaming ugc-image-upload"
        self.logger.info(f"Mengupdate Scope OAuth menjadi: {scope}")
        self.oauth_handler.scope = scope
        
        self.logger.info("Starting PKCE OAuth flow...")
        
        # 2. Setup Server Callback
        auth_url = self.oauth_handler.get_auth_url()
        self.auth_code = None
        self.server = HTTPServer(('0.0.0.0', 4381), self.RequestHandler)
        self.server.oauth_handler = self
        
        server_thread = Thread(target=self.server.serve_forever)
        server_thread.daemon = True
        server_thread.start()
        
        self.logger.info(f"OAuth callback server started at http://127.0.0.1:4381/login")
        
        # 3. Tampilkan Link Login (Public Gateway)
        # Gunakan Gateway Google agar bisa diakses dari mana saja (HP/PC)
        public_auth_url = f"https://accounts.spotify.com/authorize?client_id=65b708073fc0480ea92a077233ca87bd&response_type=code&redirect_uri=http%3A%2F%2F127.0.0.1%3A4381%2Flogin&scope=user-read-email+user-read-private+playlist-read-private+playlist-read-collaborative+playlist-modify-private+playlist-modify-public+user-library-read+user-library-modify+user-read-playback-state+user-modify-playback-state+user-read-currently-playing+user-read-recently-played+user-read-playback-position+user-top-read+streaming+ugc-image-upload&code_challenge_method=S256&code_challenge=4pHCIx61Po0MTFi0aciAkOQiPcVsz_7crg5eX2d9Nx4"
        print(f"\nPlease authorize in your browser: {public_auth_url}\n")
        self.logger.info(f"Please authorize in your browser: {public_auth_url}")

        # 4. Tunggu User Login
        self.logger.info("Waiting for user authorization in browser...")
        
        # Timeout 5 menit
        max_wait = 300 
        start_wait = time.time()
        
        while self.auth_code is None:
            if time.time() - start_wait > max_wait:
                self.logger.error("OAuth flow timed out waiting for user input.")
                self.server.shutdown()
                return False
            time.sleep(1)
            
        # 5. Tukar Code dengan Token
        self.server.shutdown()
        self.logger.info("Authorization code received. Exchanging for token...")
        
        try:
            token_data = self.oauth_handler.get_access_token(self.auth_code)
            
            # Ambil Info User (Username)
            sp_user_info = requests.get(
                "https://api.spotify.com/v1/me", 
                headers={"Authorization": f"Bearer {token_data['access_token']}"}
            ).json()
            
            token_data['spotify_username'] = sp_user_info.get('id')
            
            # [FIX PENTING] Gunakan .from_dict()
            self.stored_token = StoredToken.from_dict(token_data)
            
            self._save_credentials(self.stored_token, token_data['spotify_username'])
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to exchange code for token: {e}")
            return False

    def _fetch_spotify_user_details(self, access_token: str) -> Optional[dict]:
        """Fetches user details (like username/ID and market) from Spotify API."""
        if not access_token:
            self.logger.warning("Cannot fetch user details without an access token.")
            return None
        headers = {'Authorization': f'Bearer {access_token}'}
        try:
            response = requests.get(API_URL + "me", headers=headers, timeout=DEFAULT_REQUEST_TIMEOUT)
            response.raise_for_status()
            user_data = response.json()
            self.logger.info(f"Successfully fetched user details: ID={user_data.get('id')}, Market={user_data.get('country')}")
            return user_data
        except requests.RequestException as e:
            self.logger.error(f"Error fetching user details: {e}")
            return None

    def _create_librespot_session_from_oauth(self) -> bool:
        """
        Membuat sesi Librespot dengan penanganan Token Mati (Revoked).
        """
        if not self.stored_token or not self.stored_token.access_token:
            self.logger.error("No valid OAuth token available.")
            return False

        spotify_username = self.stored_token.spotify_username or "PKCE_LibrespotUser"
        
        # Setup Patching
        current_api_ref = weakref.ref(self)
        def token_provider_patch(session, *args, **kwargs):
            api = current_api_ref()
            if api: return SpotifyApiTokenProvider(session, api)
            return _OriginalLibrespotTokenProvider(session, *args, **kwargs)

        if not hasattr(librespot.core, '_truly_original_token_provider_for_restore'):
            librespot.core._truly_original_token_provider_for_restore = librespot.core.TokenProvider
        librespot.core.TokenProvider = token_provider_patch

        try:
            # Config Builder
            conf_builder = LibrespotSession.Configuration.Builder()
            conf_builder.set_store_credentials(False) 
            cache_path = os.path.join(self.credentials_dir, ".librespot_cache")
            os.makedirs(cache_path, exist_ok=True)
            conf_builder.set_cache_dir(cache_path)
            conf_builder.set_cache_enabled(True)
            conf = conf_builder.build()

            builder = LibrespotSession.Builder(conf)
            auth_type = Authentication_pb2.AuthenticationType.values()[3]

            # --- RETRY LOOP (FIXED) ---
            max_retries = 3
            for attempt in range(max_retries):
                # Update kredensial di setiap putaran (penting jika token berubah)
                builder.login_credentials = Authentication_pb2.LoginCredentials(
                    username=spotify_username,
                    typ=auth_type,
                    auth_data=self.stored_token.access_token.encode('utf-8')
                )

                try:
                    self.logger.info(f"Mencoba login Librespot (Percobaan {attempt + 1})...")
                    self.librespot_session = builder.create() 
                    break 

                except Exception as e:
                    err_msg = str(e)
                    
                    # KASUS 1: Token ENV Basi (BadCredentials)
                    if "BadCredentials" in err_msg:
                        self.logger.warning("⚠️ Token Kadaluarsa (BadCredentials). Melakukan Refresh Darurat...")
                        try:
                            PUBLIC_ID = "65b708073fc0480ea92a077233ca87bd"
                            payload = {
                                "grant_type": "refresh_token",
                                "refresh_token": self.stored_token.refresh_token,
                                "client_id": PUBLIC_ID
                            }
                            resp = requests.post("https://accounts.spotify.com/api/token", data=payload, timeout=10)
                            
                            if resp.status_code == 200:
                                new_data = resp.json()
                                self.stored_token.access_token = new_data['access_token']
                                self.stored_token.expires_in = int(new_data['expires_in'])
                                self.stored_token.expires_at = int(time.time()) + int(new_data['expires_in'])
                                
                                # Simpan token baru agar sinkron
                                self._save_credentials(self.stored_token, spotify_username)
                                self.logger.info("✅ Token berhasil disegarkan! Mencoba login lagi...")
                                continue 
                            else:
                                # [FIX] Jika Refresh Gagal Total (Revoked), Hapus File & Menyerah
                                self.logger.error(f"❌ Refresh Gagal: {resp.text}")
                                if "revoked" in resp.text or "invalid_grant" in resp.text:
                                    self.logger.error("💀 Token Mati Total (Revoked). Menghapus kredensial...")
                                    self._clear_credentials()
                                    return False # Kembalikan False agar _load_credentials bisa trigger Re-Auth
                        except Exception as refresh_err:
                            self.logger.error(f"Error saat refresh: {refresh_err}")

                    # KASUS 2: Koneksi
                    if "Connection refused" in err_msg or "111" in err_msg:
                        self.logger.warning("⚠️ Koneksi ditolak. Menunggu 3 detik...")
                        time.sleep(3)
                        continue
                    
                    if attempt == max_retries - 1: 
                        self.logger.error(f"❌ Gagal login setelah retry: {e}")
                        return False

            if self.librespot_session:
                self.logger.info(f"✅ Sesi Librespot Aktif: {self.librespot_session.username()}")
                return True
            return False

        except Exception as e:
            self.logger.error(f"❌ Exception Fatal Sesi: {e}")
            self.librespot_session = None
            return False
        finally:
            if hasattr(librespot.core, '_truly_original_token_provider_for_restore'):
                librespot.core.TokenProvider = librespot.core._truly_original_token_provider_for_restore

    def _get_web_api_token(self) -> Optional[str]:
        """
        Mendapatkan token untuk Metadata (Web API).
        [FIX STRICT] ISOLASI TOTAL:
        1. Jangan pernah gunakan token dari ENV/User (self.stored_token).
        2. Selalu generate baru dari Client ID & Secret jika cache memori kosong.
        """
        # 1. Cek Cache Memori (RAM) saja. Jangan percaya file/env lama.
        if self.web_api_stored_token and not self.web_api_stored_token.expired():
            # Pastikan token ini BUKAN token user (cek scope)
            # Token metadata murni biasanya tidak punya scope user-read-email dsb.
            if not self.web_api_stored_token.scopes or "user-read-email" not in self.web_api_stored_token.scopes:
                return self.web_api_stored_token.access_token

        self.logger.info("🔄 Metadata: Membuat Token Client Credentials BARU...")
        
        try:
            # 2. Validasi Config
            client_id = self.config.get('client_id')
            client_secret = self.config.get('client_secret')
            
            # [PENTING] Cek apakah ID-nya adalah ID Public (bfba...) yang sering limit
            if client_id and str(client_id).startswith("bfba46d69c"):
                self.logger.warning("⚠️ PERINGATAN: Anda menggunakan Client ID Publik/Shared (bfba...).")
                self.logger.warning("⚠️ Ini penyebab utama Rate Limit 429. Mohon buat Client ID sendiri di developer.spotify.com")

            if not client_id or not client_secret:
                self.logger.error("❌ Client ID / Secret Kosong! Tidak bisa ambil metadata.")
                return None

            import base64
            auth_str = f"{client_id}:{client_secret}"
            b64_auth = base64.b64encode(auth_str.encode()).decode()
            
            # 3. Request Token Baru ke Spotify
            resp = requests.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                headers={"Authorization": f"Basic {b64_auth}"},
                timeout=10
            )
            
            if resp.status_code == 200:
                token_data = resp.json()
                # Simpan ke Memori sebagai StoredToken
                self.web_api_stored_token = StoredToken.from_dict(token_data)
                self.logger.info("✅ Token Metadata Baru Berhasil Dibuat (Mode Isolasi).")
                return self.web_api_stored_token.access_token
            
            elif resp.status_code == 429:
                self.logger.error("❌ CLIENT ID ANDA TERKENA LIMIT (429).")
                self.logger.error("👉 Solusi: Ganti Client ID & Secret di Config dengan yang baru.")
                return None
            else:
                self.logger.error(f"❌ Gagal Client Credentials: {resp.status_code} - {resp.text}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ Error Fatal Metadata: {e}")
            return None

    def _clear_credentials(self):
        """Clear all Spotify credentials files to force re-authentication."""
        credentials_files = [
            self.credentials_file_path,
            self.credentials_file_path.replace('.json', '_webapi.json')
        ]
        for cred_file in credentials_files:
            if os.path.exists(cred_file):
                try:
                    os.remove(cred_file)
                    self.logger.info(f"Removed credentials file: {cred_file}")
                except OSError as e:
                    self.logger.warning(f"Could not remove credentials file {cred_file}: {e}")

    def _load_credentials_and_init_session(self) -> bool:
        """
        Memuat kredensial dan inisialisasi sesi.
        Fungsi ini aman dari restart karena mengandalkan _load_existing_credentials 
        yang sudah terintegrasi dengan MongoDB.
        """
        self.logger.info("Attempting to authenticate and initialize session...")
        
        username = self.config.get('username', '') if self.config else ''
        if not username:
            self.logger.error("Spotify credentials missing in config.")
            return False
        
        # Simpan handler asli (karena kita akan switch sementara ke librespot handler)
        original_oauth_handler = self.oauth_handler
        self.oauth_handler = self.librespot_oauth_handler
        
        # --- STEP 1: LOAD KREDENSIAL DARI FILE / MONGODB ---
        credentials_loaded = False
        try:
            # _load_existing_credentials sekarang sudah CANGGIH (Cek File -> Cek DB -> Restore File)
            if self._load_existing_credentials():
                self.librespot_stored_token = self.stored_token
                credentials_loaded = True
            else:
                self.logger.info("No valid existing credentials found (or load failed).")
        except Exception as e: 
            self.logger.error(f"Error loading credentials: {e}")

        # --- STEP 2: COBA BUAT SESI LIBRESPOT ---
        session_active = False
        try:
            if credentials_loaded:
                self.logger.info("Creating Librespot session (Attempt 1)...")
                # Gunakan fungsi create yang sudah diperbaiki (Anti-BadCredentials)
                if self._create_librespot_session_from_oauth() and self.librespot_session:
                    self.logger.info("✅ Login Sukses dengan token yang ada.")
                    session_active = True
                else:
                    self.logger.warning("⚠️ Login awal gagal. Token mungkin expired atau revoked.")
        except Exception as e:
            self.logger.error(f"Error during initial session init: {e}")

        # --- STEP 3: LOAD WEB API (Metadata) ---
        # Bagian ini mencoba memuat token Metadata khusus jika ada filenya.
        # Jika tidak ada (efek restart), nanti _get_web_api_token akan otomatis membuatnya baru.
        self.oauth_handler = original_oauth_handler 
        
        if self.web_api_oauth_handler != self.librespot_oauth_handler:
            self.oauth_handler = self.web_api_oauth_handler
            web_api_credentials_path = self.credentials_file_path.replace('.json', '_webapi.json')
            
            if os.path.exists(web_api_credentials_path):
                try:
                    with open(web_api_credentials_path, 'r') as f:
                        token_data = json.load(f)
                    
                    if all(k in token_data for k in ["access_token", "refresh_token"]):
                        # [PENTING] Gunakan from_dict agar tidak error
                        loaded_token = StoredToken.from_dict(token_data)
                        
                        if loaded_token.expired():
                            self.logger.info("Web API token expired, refreshing...")
                            refreshed = self.oauth_handler.refresh_access_token(loaded_token.refresh_token)
                            
                            if refreshed:
                                self.web_api_stored_token = StoredToken.from_dict(refreshed)
                                
                                # Simpan hasil refresh ke file
                                t_dict = self.web_api_stored_token.to_dict()
                                t_dict['client_id'] = self.oauth_handler.client_id
                                with open(web_api_credentials_path, 'w') as f: 
                                    json.dump(t_dict, f, indent=4)
                        else:
                            self.web_api_stored_token = loaded_token
                except Exception as e:
                    self.logger.warning(f"Web API load error: {e}")

            # Fallback: Jika Web API token belum ada, gunakan token user sementara
            if not self.web_api_stored_token:
                 self.web_api_stored_token = self.librespot_stored_token

        # Restore handler utama ke Librespot
        self.oauth_handler = self.librespot_oauth_handler
        self.stored_token = self.librespot_stored_token
        
        if session_active:
            return True

        # --- STEP 4: FAIL GRACEFULLY ---
        # Jika semua gagal, hapus kredensial (agar tidak loop error) dan beri log jelas
        self.logger.error("❌ Login Gagal Total (Token Mati/Revoked/Hilang).")
        self.logger.error("👉 Bot akan tetap start. Silakan kirim '/spotify_login' di Telegram.")
        
        self._clear_credentials()
        return False

    def _is_session_valid(self, session_obj: Optional[LibrespotSession]) -> bool:
        """Checks if the provided librespot session object is considered valid."""
        self.logger.debug(f"_is_session_valid invoked. Type of session_obj: {type(session_obj)}")
        if hasattr(self, 'librespot_session'): # Check if self.librespot_session is initialized
            self.logger.debug(f"Is session_obj the same instance as self.librespot_session? {session_obj is self.librespot_session}")
            if self.librespot_session is not None:
                # Safely try to get username from self.librespot_session for comparison/debug
                try:
                    s_username = self.librespot_session.username()
                    self.logger.debug(f"Username from self.librespot_session (internal): '{s_username}'")
                except AttributeError:
                    self.logger.debug("self.librespot_session does not have username() attribute internally at this point.")
        else:
            self.logger.debug("self.librespot_session attribute not yet initialized in SpotifyAPI instance.")

        if session_obj is None:
            self.logger.debug("_is_session_valid: session_obj argument is None.")
            return False
        try:
            # Try a very basic check: if the session object exists and has a callable username method that returns a non-empty string.
            username = session_obj.username()
            is_logged_in_internal = session_obj.is_logged_in() if hasattr(session_obj, 'is_logged_in') else True
            is_valid = username is not None and username != "" and is_logged_in_internal
            self.logger.debug(f"_is_session_valid: username='{username}', is_logged_in_internal={is_logged_in_internal}, result={is_valid}")
            return is_valid
        except AttributeError as ae:
            self.logger.warning(f"_is_session_valid: AttributeError encountered (session might be None or malformed): {ae}")
            return False
        except Exception as e:
            self.logger.error(f"_is_session_valid: Unexpected error checking session validity: {e}", exc_info=True)
            return False
        
    def _fetch_user_market(self, _retry_attempted: bool = False) -> Optional[str]:
        """Fetches user market using the access token. Retries once on 401.
           Returns the market string or None if fetching fails.
        """
        self.logger.debug(f"SpotifyAPI._fetch_user_market called{' (retry)' if _retry_attempted else ''}")
        
        # Get Web API token (uses custom credentials if available, otherwise librespot token)
        web_api_token = self._get_web_api_token()
        if not web_api_token:
            self.logger.info("SpotifyAPI._fetch_user_market: Token missing. Attempting to load/refresh session.")
            if not self._load_credentials_and_init_session():
                self.logger.warning("SpotifyAPI._fetch_user_market: Session initialization failed. Cannot fetch market.")
                return None
            web_api_token = self._get_web_api_token()
            if not web_api_token:
                self.logger.warning("SpotifyAPI._fetch_user_market: Still no valid access token after attempt. Cannot fetch market.")
                return None

        headers = {'Authorization': f'Bearer {web_api_token}'}
        web_api_me_url = "https://api.spotify.com/v1/me"
        try:
            response = requests.get(web_api_me_url, headers=headers, timeout=DEFAULT_REQUEST_TIMEOUT)
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            user_data = response.json()
            self.user_market = user_data.get("country")
            if self.user_market:
                self.logger.info(f"User market/country determined: {self.user_market}")
            else:
                self.logger.warning("Could not determine user market from /v1/me endpoint (no 'country' field in response).")
            return self.user_market
        except requests.exceptions.HTTPError as http_err:
            if http_err.response.status_code == 401:
                self.logger.warning(f"SpotifyAPI._fetch_user_market: Auth error (401). Token might be invalid.")
                if not _retry_attempted:
                    self.logger.info("SpotifyAPI._fetch_user_market: Attempting re-auth and retry for 401.")
                    # Invalidate Web API token and re-initialize session
                    self.web_api_stored_token = None
                    if self._load_credentials_and_init_session():
                        self.logger.info("SpotifyAPI._fetch_user_market: Re-auth successful. Retrying call.")
                        return self._fetch_user_market(_retry_attempted=True)
                    else:
                        self.logger.error("SpotifyAPI._fetch_user_market: Re-auth failed after 401.")                        
                        return None 
                else:
                    self.logger.error("SpotifyAPI._fetch_user_market: Auth error (401) even after retry.")
                    return None
            else:
                self.logger.error(f"SpotifyAPI._fetch_user_market: HTTP error: {http_err.response.status_code} - {http_err.response.text[:200]}", exc_info=False)
                return None
        except requests.exceptions.RequestException as e:
            self.logger.error(f"SpotifyAPI._fetch_user_market: RequestException: {e}", exc_info=False)
            return None
        except Exception as e:
            self.logger.error(f"SpotifyAPI._fetch_user_market: Unexpected error: {e}", exc_info=True)
            return None

    def _convert_base62_to_gid_hex(self, base62_id: str) -> Optional[str]:
        if not base62_id:
            self.logger.warning("Attempted to convert an empty base62_id to GID hex.")
            return None
        try:
            if not isinstance(base62_id, str):
                self.logger.error(f"base62_id must be a string, got {type(base62_id)}: {base62_id}")
                return None
            gid_obj = TrackId.from_base62(base62_id)
            hex_id = gid_obj.hex_id()
            self.logger.info(f"Converted base62 ID '{base62_id}' to GID hex '{hex_id}'")
            return hex_id
        except Exception as e:
            self.logger.error(f"Failed to convert base62 ID '{base62_id}' to GID hex: {e}", exc_info=True)
            return None

    def search(self, query_type_enum_or_str, query_str: str, track_info=None, market: Optional[str] = None, limit: int = 20, _retry_attempted: bool = False) -> List[dict]:
        self.logger.info(f"SpotifyAPI.search: type='{query_type_enum_or_str}', query='{query_str}', limit={limit}{', retry' if _retry_attempted else ''}")
        
        # Validate and adjust limit - Spotify API has a maximum of 50 per request
        SPOTIFY_MAX_LIMIT_PER_REQUEST = 50
        total_requested = limit
        if limit > SPOTIFY_MAX_LIMIT_PER_REQUEST:
            self.logger.info(f"SpotifyAPI.search: Requested limit {limit} exceeds Spotify's max of {SPOTIFY_MAX_LIMIT_PER_REQUEST}. Will use pagination to fetch all requested results.")
        
        # Get Web API token (uses custom credentials if available, otherwise librespot token)
        web_api_token = self._get_web_api_token()
        if not web_api_token:
            self.logger.info("SpotifyAPI.search: Token missing. Attempting to load/refresh session.")
            if not self._load_credentials_and_init_session():
                self.logger.error("SpotifyAPI.search: Session initialization failed.")
                raise SpotifyAuthError("Authentication required/failed for search. Session could not be initialized.")
            web_api_token = self._get_web_api_token()
            if not web_api_token:
                self.logger.error("SpotifyAPI.search: Still no access token after session initialization attempt.")
                raise SpotifyAuthError("Authentication failed for search. No valid token.")

        # Determine market if not provided
        effective_market = market
        if not effective_market:
            effective_market = self._fetch_user_market() # This method will also handle its own 401s with retry
            if not effective_market:
                self.logger.warning("SpotifyAPI.search: No market provided and could not determine user market. Results may be inconsistent.")
        
        query_type_str = query_type_enum_or_str.name.lower() if hasattr(query_type_enum_or_str, 'name') else str(query_type_enum_or_str).lower()
        
        search_url = "https://api.spotify.com/v1/search"
        headers = {'Authorization': f'Bearer {web_api_token}'}
        
        # Collect all results across multiple requests if needed
        all_items = []
        offset = 0
        
        while len(all_items) < total_requested:
            # Calculate how many items to request in this batch
            remaining_needed = total_requested - len(all_items)
            current_limit = min(remaining_needed, SPOTIFY_MAX_LIMIT_PER_REQUEST)
            
            params = {
                'q': query_str, 
                'type': query_type_str, 
                'limit': current_limit,
                'offset': offset
            }
            if effective_market:
                params['market'] = effective_market
                
            self.logger.debug(f"SpotifyAPI.search: Making request with limit={current_limit}, offset={offset}")

            try:
                response = requests.get(search_url, headers=headers, params=params, timeout=DEFAULT_REQUEST_TIMEOUT)
                response.raise_for_status()
                search_results = response.json()
                
                plural_type = query_type_str + "s"
                if plural_type in search_results and "items" in search_results[plural_type]:
                    items = search_results[plural_type]["items"]
                    if not items:
                        # No more results available
                        self.logger.info(f"No more {plural_type} found for '{query_str}' at offset {offset}.")
                        break
                    
                    all_items.extend(items)
                    offset += len(items)
                    
                    # Check if we got fewer items than requested - indicates end of results
                    if len(items) < current_limit:
                        self.logger.info(f"Received {len(items)} items (less than requested {current_limit}), indicating end of results.")
                        break
                        
                else:
                    self.logger.warning(f"'{plural_type}' or '{plural_type}.items' not in search response for query '{query_str}'. Response keys: {list(search_results.keys())}")
                    if query_type_str in search_results and isinstance(search_results[query_type_str], dict) and "id" in search_results[query_type_str]:
                        self.logger.info(f"Found a single item matching type '{query_type_str}' directly in response.")
                        return [search_results[query_type_str]]
                    # Handle API error messages if present
                    if "error" in search_results:
                        error_details = search_results["error"]
                        msg = error_details.get("message", "Unknown Spotify API error during search")
                        status = error_details.get("status", 0)
                        self.logger.error(f"Spotify API error during search: {status} - {msg}")
                        if status == 401: # This should ideally be caught by HTTPError, but as a fallback
                            raise SpotifyAuthError(f"Search failed due to authorization issue (API Error: {msg}). Token may be invalid or scopes insufficient.")
                        elif status == 404:
                             raise SpotifyItemNotFoundError(f"Search query '{query_str}' of type '{query_type_str}' not found (API Error: {msg}).")
                        else: 
                            raise SpotifyApiError(f"Spotify API error during search: {status} - {msg}")
                    break

            except requests.exceptions.HTTPError as http_err:
                if http_err.response.status_code == 401:
                    self.logger.warning(f"SpotifyAPI.search: Auth error (401) for query '{query_str}'. Token might be invalid.")
                    if not _retry_attempted:
                        self.logger.info("SpotifyAPI.search: Attempting re-auth and retry for 401.")
                        # Invalidate Web API token and re-initialize session
                        self.web_api_stored_token = None
                        if self._load_credentials_and_init_session():
                            self.logger.info("SpotifyAPI.search: Re-auth successful. Retrying call.")
                            return self.search(query_type_enum_or_str, query_str, track_info, market, limit, _retry_attempted=True)
                        else:
                            self.logger.error("SpotifyAPI.search: Re-auth failed after 401.")
                            raise SpotifyAuthError(f"Re-authentication failed for search '{query_str}' after 401.")
                    else:
                        self.logger.error(f"SpotifyAPI.search: Auth error (401) for '{query_str}' after retry.")
                        raise SpotifyAuthError(f"Auth failed for search '{query_str}' (401) after retry.")
                elif http_err.response.status_code == 404:
                    self.logger.warning(f"SpotifyAPI.search: Query '{query_str}' (type {query_type_str}) resulted in 404.")
                    raise SpotifyItemNotFoundError(f"Search query '{query_str}' (type {query_type_str}) not found (HTTP 404).")
                elif http_err.response.status_code == 429:
                    self.logger.warning(f"Spotify API rate limit hit (429) during search for '{query_str}'. Raw: {http_err.response.text[:200]}")
                    raise SpotifyRateLimitDetectedError(f"Spotify API rate limit hit during search for '{query_str}'.")
                else:
                    self.logger.error(f"SpotifyAPI.search: HTTP error for '{query_str}': {http_err.response.status_code} - {http_err.response.text[:200]}", exc_info=False)
                    raise SpotifyApiError(f"HTTP error during search for '{query_str}': {http_err.response.status_code} - {http_err.response.text[:200]}") from http_err
            except requests.exceptions.RequestException as req_err:
                self.logger.error(f"SpotifyAPI.search: RequestException for '{query_str}': {req_err}", exc_info=False)
                raise SpotifyApiError(f"Network or request error during search for '{query_str}': {req_err}")
            except SpotifyAuthError:
                raise
            except Exception as e:
                self.logger.error(f"SpotifyAPI.search: Unexpected error for '{query_str}': {e}", exc_info=True)
                if isinstance(e, SpotifyApiError): raise
                raise SpotifyApiError(f"An unexpected error occurred during search for '{query_str}': {e}")
        
        self.logger.info(f"SpotifyAPI.search: Successfully retrieved {len(all_items)} items for '{query_str}' (requested: {total_requested})")
        return all_items

    def _save_stream_to_temp_file(self, stream_object, determined_codec_enum: CodecEnum) -> Optional[str]:
        temp_file_path = None
        try:
            project_root_for_temp = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            target_temp_dir = os.path.join(project_root_for_temp, 'temp')
            os.makedirs(target_temp_dir, exist_ok=True)
            file_suffix = ".ogg"
            try:
                from utils.models import codec_data as core_codec_data
                if determined_codec_enum in core_codec_data and hasattr(core_codec_data[determined_codec_enum].container, 'name'):
                    file_suffix = f".{core_codec_data[determined_codec_enum].container.name}"
            except ImportError:
                self.logger.warning("_save_stream_to_temp_file: Could not import core_codec_data, using default .ogg suffix.")
            except KeyError:
                self.logger.warning(f"_save_stream_to_temp_file: Codec {determined_codec_enum} not in core_codec_data, using default .ogg suffix.")
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_suffix, dir=target_temp_dir) as temp_file:
                temp_file_path = temp_file.name
                self.logger.info(f"Attempting to save stream to {temp_file_path}...")
                bytes_written = 0
                if hasattr(stream_object, 'read') and callable(stream_object.read):
                    while True:
                        chunk = stream_object.read(8192)
                        if not chunk:
                            break
                        temp_file.write(chunk)
                        bytes_written += len(chunk)
                    self.logger.info(f"Finished writing stream to {temp_file_path} ({bytes_written} bytes).")
                else: 
                    self.logger.error(f"Stream object for {temp_file_path} does not have a callable .read() method. Trying iteration as fallback.")
                    for chunk_iter in stream_object: 
                        temp_file.write(chunk_iter)
                        bytes_written += len(chunk_iter)
                    self.logger.info(f"Finished writing stream (iteration fallback) to {temp_file_path} ({bytes_written} bytes).")
            self.logger.info(f"Temporary file size for {temp_file_path}: {bytes_written} bytes.")
            if bytes_written == 0:
                self.logger.error(f"Temporary file {temp_file_path} is empty after saving!")
                if os.path.exists(temp_file_path): os.unlink(temp_file_path)
                return None
            return temp_file_path
        except Exception as save_err:
            self.logger.error(f"Failed during stream saving to temp file: {save_err}", exc_info=True)
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except OSError as e_unlink:
                    self.logger.error(f"Error removing temp file {temp_file_path} after save error: {e_unlink}")
            return None
        finally:
            if stream_object and hasattr(stream_object, 'close') and callable(stream_object.close):
                try:
                    stream_object.close()
                except Exception as close_err:
                    self.logger.warning(f"Error closing original stream object after saving: {close_err}")

    def get_track_download(self, track_id, quality_tier=None, **kwargs):
        """
        [UPDATED FIX 104] Mendownload track dengan penanganan Connection Reset yang lebih kuat.
        """
        # 1. Parsing Input
        if not track_id and 'track_id' in kwargs:
            track_id = kwargs.get('track_id')
        if not quality_tier and 'quality_tier' in kwargs:
            quality_tier = kwargs.get('quality_tier')

        # 2. Mapping Kualitas Audio
        quality_map = {
            "LOW": LibrespotAudioQualityEnum.NORMAL,
            "NORMAL": LibrespotAudioQualityEnum.HIGH,
            "HIGH": LibrespotAudioQualityEnum.VERY_HIGH,
            "HIFI": LibrespotAudioQualityEnum.VERY_HIGH,
            "VERY_HIGH": LibrespotAudioQualityEnum.VERY_HIGH
        }
        
        qt_str = str(quality_tier).upper() if quality_tier else "HIGH"
        selected_quality = quality_map.get(qt_str, LibrespotAudioQualityEnum.VERY_HIGH)
        has_downgraded = False
        
        self.logger.info(f"⬇️ Start Download: ID={track_id}, Quality={qt_str}")

        # 3. Konversi ID
        try:
            if isinstance(track_id, str):
                if len(track_id) == 32 and all(c in '0123456789abcdefABCDEF' for c in track_id):
                    tid = TrackId.from_hex(track_id)
                else:
                    tid = TrackId.from_base62(track_id)
            else:
                tid = track_id
        except Exception as e:
            self.logger.error(f"Gagal memparsing Track ID: {e}")
            raise SpotifyApiError(f"Track ID tidak valid: {e}")

        # --- LOOP RETRY (Ditingkatkan menjadi 5x) ---
        max_retries = 5 
        last_error = None

        for attempt in range(1, max_retries + 1):
            temp_file = None
            try:
                # A. Cek Sesi (Wajib Login Ulang jika None)
                if not self.librespot_session:
                    self.logger.warning(f"⚠️ [Percobaan {attempt}] Sesi mati. Login ulang...")
                    # Force Refresh Token dulu agar sesi baru fresh
                    if self.stored_token: 
                        self.perform_token_refresh()
                    
                    if not self._load_credentials_and_init_session():
                        time.sleep(3) # Beri jeda jika login gagal
                        raise Exception("Gagal inisialisasi sesi baru.")

                # B. Siapkan Feeder
                try:
                    feeder = self.librespot_session.content_feeder()
                except Exception as feeder_err:
                    raise Exception(f"Session Dead/Feeder Error: {feeder_err}")

                # C. Load Stream
                stream_loader = feeder.load(
                    tid, 
                    VorbisOnlyAudioQuality(selected_quality), 
                    False, 
                    None
                )
                
                if not stream_loader:
                    raise Exception("Stream Loader kosong (Lagu tidak tersedia/Region lock?)")

                # D. Download ke File Temp
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".ogg")
                
                input_stream = stream_loader.input_stream
                total_size = input_stream.size
                downloaded = 0
                buffer_size = 65536 
                
                # Loop baca stream
                while downloaded < total_size:
                    chunk = input_stream.stream().read(buffer_size)
                    if not chunk:
                        break
                    temp_file.write(chunk)
                    downloaded += len(chunk)
                
                temp_file.close()
                
                # Validasi ukuran file (minimal 1KB)
                if downloaded < 1024:
                    raise Exception("File terdownload terlalu kecil (0KB), mungkin corrupt.")

                self.logger.info(f"✅ Download Berhasil: {temp_file.name}")
                return TrackDownloadInfo(
                    download_type=DownloadEnum.TEMP_FILE_PATH,
                    temp_file_path=temp_file.name,
                    file_url=None
                )

            except Exception as e:
                error_msg = str(e)
                last_error = e
                self.logger.warning(f"⚠️ Gagal Download (Percobaan {attempt}/{max_retries}): {error_msg}")
                
                # Bersihkan file sampah
                if temp_file and os.path.exists(temp_file.name):
                    try: os.unlink(temp_file.name)
                    except: pass

                # --- PENANGANAN ERROR KRITIS (Errno 104) ---
                critical_errors = [
                    "104", "Connection reset", "Broken pipe", "Session Dead", 
                    "unpack requires a buffer", "Errno 9", "Bad file descriptor",
                    "code: 2", "channel closed"
                ]

                if (any(x in error_msg for x in critical_errors) or not error_msg):
                    
                    self.logger.critical(f"♻️ KONEKSI RUSAK ({error_msg}). RESTART SESI & COOLDOWN...")
                    
                    # 1. Matikan sesi lama
                    self.close_session()
                    
                    # 2. Jeda Wajib (Cooldown) - PENTING!
                    # Tambah waktu tunggu agar server tidak menolak koneksi lagi (Anti-Stuck)
                    wait_time = 5 + (attempt * 2) 
                    self.logger.info(f"⏳ Menunggu {wait_time} detik sebelum reconnect...")
                    time.sleep(wait_time)
                    
                    # 3. Coba Login Ulang di putaran loop berikutnya
                    continue 

                # Handling Error 403 (Limit/Premium)
                if "403" in error_msg:
                    if not has_downgraded and selected_quality != LibrespotAudioQualityEnum.NORMAL:
                        self.logger.info("📉 Error 403. Downgrade ke NORMAL (96kbps)...")
                        selected_quality = LibrespotAudioQualityEnum.NORMAL
                        has_downgraded = True
                        time.sleep(2)
                        continue
                    else:
                        # Jika sudah low quality tapi masih 403, berarti region lock
                        raise SpotifyApiError("Gagal Download: Izin Streaming ditolak (403).")

                if "404" in error_msg:
                    raise SpotifyApiError("Lagu tidak ditemukan (404).")
                
                time.sleep(2)
                continue

        # Jika loop selesai tanpa hasil
        raise last_error if last_error else Exception("Gagal download setelah semua percobaan.")


    def close_session(self):
        """Placeholder for closing librespot session if needed by OrpheusDL's lifecycle."""
        if self.librespot_session:
            try:
                self.logger.info("Simulating librespot session closure (clearing reference).")
                if hasattr(self.librespot_session, 'close') and callable(self.librespot_session.close):
                    self.librespot_session.close()
                    self.logger.info("Called self.librespot_session.close()")
            except Exception as e:
                self.logger.error(f"Error during librespot session close() method: {e}", exc_info=True)
            finally:
                self.librespot_session = None
                self.stored_token = None 
                self.oauth_handler = None 
                self.user_market = None 
                self.logger.info("Cleared librespot_session, stored_token, oauth_handler, and user_market.")
        else: 
            self.logger.info("No active librespot session to close. Ensuring other related attributes are cleared.")
            self.stored_token = None
            self.oauth_handler = None
            self.user_market = None

    def authenticate_stream_api(self, is_initial_setup_check: bool = False) -> bool:
        """Alias for _load_credentials_and_init_session to maintain compatibility with interface.py."""
        self.logger.debug(f"authenticate_stream_api called (aliased to _load_credentials_and_init_session). is_initial_setup_check={is_initial_setup_check}")
        try:
            result = self._load_credentials_and_init_session()
            if not result:
                # If authentication failed, check if OAuth flow was attempted
                if self.oauth_handler and hasattr(self.oauth_handler, 'error_message') and self.oauth_handler.error_message:
                    self.logger.error(f"Authentication failed: {self.oauth_handler.error_message}")
                else:
                    self.logger.error("Authentication failed: Unknown error during credential loading or OAuth flow")
            return result
        except SpotifyApiError as e:
            self.logger.error(f"authenticate_stream_api failed: {e}")
            if isinstance(e, (SpotifyAuthError, SpotifyConfigError, SpotifyLibrespotError)):
                 return False 
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in authenticate_stream_api: {e}", exc_info=True)
            return False 

    def get_track_by_id(self, track_id: str, market: Optional[str] = None, _retry_attempted: bool = False) -> Optional[dict]:
        """Get track details by its Spotify ID using the Web API."""
        self.logger.debug(f"SpotifyAPI.get_track_by_id entered for track_id: {track_id}, market: {market}{', retry' if _retry_attempted else ''}")

        # Get Web API token (uses custom credentials if available, otherwise librespot token)
        web_api_token = self._get_web_api_token()
        if not web_api_token:
            self.logger.info("SpotifyAPI.get_track_by_id: Token missing. Attempting to load/refresh session.")
            if not self._load_credentials_and_init_session(): 
                self.logger.error("SpotifyAPI.get_track_by_id: Session initialization failed.")
                raise SpotifyAuthError("Authentication required/failed for get_track_by_id. Session could not be initialized.")
            web_api_token = self._get_web_api_token()
            if not web_api_token:
                self.logger.error("SpotifyAPI.get_track_by_id: Still no access token after session initialization attempt.")
                raise SpotifyAuthError("Authentication failed for get_track_by_id. No valid token.")

        headers = {"Authorization": f"Bearer {web_api_token}"}
        params = {}
        if market:
            params["market"] = market
        elif self.user_market: 
            params["market"] = self.user_market
        
        api_url = f"https://api.spotify.com/v1/tracks/{track_id}"
        self.logger.debug(f"Calling Spotify Web API: GET {api_url} with params: {params}")
        try:
            response = requests.get(api_url, headers=headers, params=params, timeout=DEFAULT_REQUEST_TIMEOUT)
            response.raise_for_status() # Will raise HTTPError for 4xx/5xx status codes
            track_data = response.json()
            self.logger.debug(f"get_track_by_id SUCCEEDED for track_id: {track_id}. Data (truncated): {str(track_data)[:200]}...")
            return track_data
        except requests.exceptions.HTTPError as http_err:
            if http_err.response.status_code == 401:
                self.logger.warning(f"SpotifyAPI.get_track_by_id: Auth error (401) for track {track_id}. Token might be invalid.")
                if not _retry_attempted:
                    self.logger.info("SpotifyAPI.get_track_by_id: Attempting re-auth and retry for 401.")
                    # Invalidate Web API token
                    self.web_api_stored_token = None
                    if self._load_credentials_and_init_session():
                        self.logger.info("SpotifyAPI.get_track_by_id: Re-auth successful. Retrying call.")
                        return self.get_track_by_id(track_id, market, _retry_attempted=True)
                    else:
                        self.logger.error("SpotifyAPI.get_track_by_id: Re-auth failed after 401.")
                        raise SpotifyAuthError(f"Re-authentication failed for track {track_id} after 401.")
                else:
                    self.logger.error(f"SpotifyAPI.get_track_by_id: Auth error (401) for track {track_id} after retry.")
                    raise SpotifyAuthError(f"Auth failed for track {track_id} (401) after retry.")
            elif http_err.response.status_code == 404:
                self.logger.warning(f"Track {track_id} not found via Spotify API (404).")
                raise SpotifyItemNotFoundError(f"Track {track_id} not found.") from http_err
            else:
                self.logger.error(f"HTTP error fetching track {track_id}: {http_err.response.status_code} - {http_err.response.text[:200]}", exc_info=False)
                raise SpotifyApiError(f"Spotify API request failed for track {track_id}: {http_err.response.status_code} - {http_err.response.text[:200]}") from http_err
        except requests.exceptions.RequestException as req_err:
            self.logger.error(f"Request exception fetching track {track_id}: {req_err}", exc_info=False)
            raise SpotifyApiError(f"Network error fetching track {track_id}: {req_err}")
        except json.JSONDecodeError as json_err:
            self.logger.error(f"Failed to decode JSON response for track {track_id}: {json_err.msg}. Response text: {response.text[:200]}...", exc_info=False)
            raise SpotifyApiError(f"Invalid JSON response for track {track_id}: {json_err.msg}") from json_err
        except SpotifyAuthError: # Re-raise
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error in get_track_by_id for {track_id}: {e}", exc_info=True)
            if isinstance(e, SpotifyApiError): raise
            raise SpotifyApiError(f"An unexpected error occurred while fetching track {track_id}: {e}")

    def get_preview_url_from_embed(self, track_id: str) -> Optional[str]:
        """
        Fetch preview URL by scraping Spotify's embed page.
        This is a fallback when the API returns null for preview_url.
        
        The embed page at https://open.spotify.com/embed/track/{id} contains
        embedded JSON data with the preview URL (audioPreview field).
        
        See: https://community.spotify.com/t5/Spotify-for-Developers/Preview-URLs-Deprecated/td-p/6791368
        """
        embed_url = f"https://open.spotify.com/embed/track/{track_id}"
        self.logger.debug(f"Fetching preview URL from embed page: {embed_url}")
        
        try:
            # Use a browser-like User-Agent to avoid being blocked
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            response = requests.get(embed_url, headers=headers, timeout=10)
            response.raise_for_status()
            html_content = response.text
            
            # Look for preview URL in the HTML - it's usually in a script tag with JSON data
            # Pattern 1: Look for audioPreview in JSON data (handles escaped URLs in JSON)
            audio_preview_pattern = re.compile(r'"audioPreview"\s*:\s*\{\s*"url"\s*:\s*"(https:\\?/\\?/p\.scdn\.co\\?/mp3-preview\\?/[^"]+)"')
            match = audio_preview_pattern.search(html_content)
            if match:
                preview_url = match.group(1)
                # Unescape JSON escaped slashes
                preview_url = preview_url.replace('\\/', '/').replace('\\u0026', '&')
                self.logger.info(f"Found preview URL from embed page for track {track_id}: {preview_url[:80]}...")
                return preview_url
            
            # Pattern 2: Direct p.scdn.co URL pattern (unescaped)
            scdn_pattern = re.compile(r'(https://p\.scdn\.co/mp3-preview/[a-zA-Z0-9]+(?:\?[^"\'<>\s]*)?)')
            match = scdn_pattern.search(html_content)
            if match:
                preview_url = match.group(1)
                self.logger.info(f"Found preview URL (scdn pattern) from embed page for track {track_id}: {preview_url[:80]}...")
                return preview_url
            
            # Pattern 3: Look for any mp3-preview URL with escaped slashes
            escaped_pattern = re.compile(r'(https:\\?/\\?/p\.scdn\.co\\?/mp3-preview\\?/[a-zA-Z0-9]+(?:\\?[^"\'<>\s]*)?)')
            match = escaped_pattern.search(html_content)
            if match:
                preview_url = match.group(1)
                # Unescape JSON escaped slashes
                preview_url = preview_url.replace('\\/', '/').replace('\\u0026', '&')
                self.logger.info(f"Found preview URL (escaped pattern) from embed page for track {track_id}: {preview_url[:80]}...")
                return preview_url
            
            # Log more details about what we found in the HTML to debug
            self.logger.info(f"[Spotify Preview] No preview URL found in embed page for track {track_id}")
            # Check if the page indicates no preview is available
            if 'preview' not in html_content.lower():
                self.logger.debug(f"[Spotify Preview] The word 'preview' not found in embed page - track likely has no preview")
            return None
            
        except requests.exceptions.RequestException as e:
            self.logger.warning(f"Failed to fetch embed page for track {track_id}: {e}")
            return None
        except Exception as e:
            self.logger.warning(f"Error parsing embed page for track {track_id}: {e}")
            return None

    @staticmethod
    def is_spotify_url(url_string: str) -> bool:
        """
        Cek apakah string adalah URL Spotify atau LINK LOGIN 127.0.0.1.
        """
        if not isinstance(url_string, str):
            return False
            
        # --- [BYPASS KHUSUS] ---
        # Jika link mengandung 127.0.0.1 dan code=, kita paksa TRUE (Valid).
        # Ini agar Handler bot tidak menolak link login Anda.
        if "127.0.0.1" in url_string and "code=" in url_string:
            return True
            
        # --- [CEK NORMAL] ---
        # Gunakan .search() (bukan .match) agar lebih aman mendeteksi link
        return bool(SpotifyAPI._spotify_url_pattern.search(url_string))
    
    def _manual_login_exchange(self, code):
        self.logger.info("Menukar Kode dengan Token ke Spotify (Official)...")
        
        # ID Public (Sama dengan generate_code_verifier)
        CLIENT_ID = "65b708073fc0480ea92a077233ca87bd" 
        REDIRECT_URI = "http://127.0.0.1:4381/login"
        
        try:
            payload = {
                "client_id": CLIENT_ID,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": "MonomarsxBot_Static_Verifier_Secret_Key_2026_Fixed"
            }
            
            # [FIX] URL RESMI SPOTIFY (JANGAN PAKAI PROXY)
            TOKEN_URL = "https://accounts.spotify.com/api/token"
            
            # Kirim Request
            r = requests.post(TOKEN_URL, data=payload)
            
            if r.status_code == 200:
                data = r.json()
                
                # Coba ambil info user (Username)
                try:
                    user_r = requests.get(
                        "https://api.spotify.com/v1/me", 
                        headers={"Authorization": f"Bearer {data['access_token']}"}
                    )
                    username = user_r.json().get('id') if user_r.status_code == 200 else "SpotifyUser"
                except:
                    username = "SpotifyUser"
                
                # Buat Object StoredToken
                self.stored_token = StoredToken(data)
                self.stored_token.spotify_username = username
                
                # [FIX] SIMPAN KE MONGODB & FILE (PERMANEN)
                self._save_credentials(self.stored_token, username)
                
                # Inisialisasi Sesi Librespot
                self._create_librespot_session()
                
                print(f"\n\n{'='*30}\n✅ LOGIN SUKSES! TOKEN DISIMPAN KE MONGODB.\nBot sekarang AMAN dari Restart.\n{'='*30}\n\n")
                self.logger.info(f"✅ Login sukses & tersimpan sebagai: {username}")
            else:
                self.logger.error(f"❌ Gagal tukar token. Status: {r.status_code}. Response: {r.text}")
                
        except Exception as e:
            self.logger.error(f"❌ Error Login Manual: {e}", exc_info=True)

    def parse_url(self, url: str):
        if not url or not isinstance(url, str):
            return None

        clean_input = url.strip()

        # 1. DETEKSI LINK LOGIN (Prioritas Utama)
        if "127.0.0.1" in clean_input and "code=" in clean_input:
            self.logger.info("🚀 MENDETEKSI LINK LOGIN! SEDANG MEMPROSES...")
            try:
                parsed = urlparse(clean_input)
                query = parse_qs(parsed.query)
                if 'code' in query:
                    self._manual_login_exchange(query['code'][0])
                    return None 
            except Exception as e:
                self.logger.error(f"Gagal parse link login: {e}")
                return None

        # -----------------------------------------------------------
        # [RESOLVER V6 - LOGIC FIX]
        # 1. Buka Link -> 2. Cek apakah domainnya 'open.spotify.com'
        # -----------------------------------------------------------
        should_resolve = False
        
        # Trigger jika link mengandung googleusercontent ATAU pendek (<100 char) dan bukan spotify resmi
        if "googleusercontent.com" in clean_input:
            should_resolve = True
        elif len(clean_input) < 100 and "open.spotify.com" not in clean_input and "spotify:" not in clean_input:
            should_resolve = True

        if should_resolve:
            self.logger.info(f"🕵️ Link Redirect Terdeteksi: {clean_input} | Mencari link asli...")
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
                
                # Request HEAD/GET (Follow Redirects)
                try:
                    resp = requests.head(clean_input, headers=headers, allow_redirects=True, timeout=10)
                    if resp.status_code not in [200, 301, 302]:
                         resp = requests.get(clean_input, headers=headers, allow_redirects=True, timeout=10)
                except:
                    resp = requests.get(clean_input, headers=headers, allow_redirects=True, timeout=10)
                
                final_url = resp.url
                
                # Bersihkan URL dari tambahan regional (misal: /intl-id/)
                final_url = re.sub(r'/intl-[a-zA-Z0-9]+/', '/', final_url)
                
                self.logger.info(f"🔗 URL Akhir ditemukan: {final_url}")

                # [FIXED] Cek apakah domain akhirnya adalah open.spotify.com
                if "open.spotify.com" in final_url or "spotify:" in final_url:
                    clean_input = final_url # GANTI input dengan link asli
                    self.logger.info("✅ SUCCESS: Input diganti ke Link Asli Spotify.")
                else:
                    # Jika tidak redirect, coba cari di dalam HTML (Scraping)
                    self.logger.info("⚠️ Tidak redirect ke Spotify. Mencari ID di dalam HTML...")
                    match = re.search(r'open\.spotify\.com/(track|album|artist|playlist|show|episode)/([a-zA-Z0-9]{22})', resp.text)
                    if match:
                        # KONSTRUKSI LINK STANDAR AGAR DITERIMA REGEX
                        # Jangan pakai googleusercontent lagi, langsung buat link spotify resmi
                        f_type = match.group(1)
                        f_id = match.group(2)
                        clean_input = f"https://open.spotify.com/{f_type}/{f_id}"
                        self.logger.info(f"✅ SUCCESS: Link diekstrak dari HTML: {clean_input}")

            except Exception as e:
                self.logger.warning(f"⚠️ Gagal resolve link (mencoba parse standar): {e}")

        # -----------------------------------------------------------

        # 2. PARSE STANDARD (clean_input sekarang sudah dijamin Link Spotify Asli)
        
        clean_url_spotify = clean_input.split("?")[0]
        
        match = self._spotify_url_pattern.search(clean_url_spotify)
        
        if match:
            g = match.groups()
            item_type = g[0] or g[3]
            item_id = g[1] or g[2] or g[4]
            
            if item_type and item_id:
                if len(item_id) == 22 and item_id.isalnum():
                    self.logger.info(f"Hasil Parse -> Tipe: {item_type}, ID: {item_id}")
                    return (item_type, item_id)
        
        self.logger.warning(f"URL tidak dikenali: {url}")
        return None

    def parse_spotify_url(self, url):
        return self.parse_url(url)

    def get_track_info(self, track_id: str, quality_tier: QualityEnum, codec_options: CodecOptions, **extra_kwargs) -> Optional[TrackInfo]:
        """
        Mengambil info track dan menyiapkan data untuk Handler.
        """
        self.logger.debug(f"SpotifyAPI.get_track_info entered for track_id: {track_id}")
        
        web_api_token = self._get_web_api_token()
        if not web_api_token:
            if not self._load_credentials_and_init_session(): return None
            web_api_token = self._get_web_api_token()
        
        try:
            web_api_track_data = self.get_track_by_id(track_id) 
            if not web_api_track_data: return None

            # --- PARSING DATA ---
            name = web_api_track_data.get('name')
            duration_ms = web_api_track_data.get('duration_ms')
            
            # [FIX 1] Explicit biarkan Boolean (True/False) di sini.
            # Konversi string dilakukan di Handler agar fleksibel.
            explicit_bool = web_api_track_data.get('explicit', False)
            
            track_number = web_api_track_data.get('track_number')
            disc_number = web_api_track_data.get('disc_number')
            
            artists_data = web_api_track_data.get('artists', [])
            artist_names = [artist.get('name') for artist in artists_data if artist.get('name')]
            artist_ids = [artist.get('id') for artist in artists_data if artist.get('id')]
            
            album_data = web_api_track_data.get('album', {})
            album_name = album_data.get('name')
            album_id_spotify = album_data.get('id')
            album_release_date_str = album_data.get('release_date')
            album_total_tracks = album_data.get('total_tracks')
            
            album_artist_data = album_data.get('artists', [])
            album_artist_names = [aa.get('name') for aa in album_artist_data if aa.get('name')]
            
            # Cover Art
            cover_url = None
            if album_data.get('images'):
                preferred_image = next((img for img in album_data['images'] if img.get('height') == 640), None)
                cover_url = preferred_image.get('url') if preferred_image else album_data['images'][0].get('url')
            
            # Parsing Tahun
            album_release_year_int = 0
            if album_release_date_str and len(album_release_date_str) >= 4:
                try: album_release_year_int = int(album_release_date_str[:4])
                except: pass

            gid_hex_value = self._convert_base62_to_gid_hex(track_id) 

            # --- ISI TAGS ---
            tags_obj = Tags(
                album_artist=album_artist_names if album_artist_names else artist_names,
                track_number=str(track_number) if track_number is not None else "1",
                total_tracks=str(album_total_tracks) if album_total_tracks is not None else "1",
                disc_number=str(disc_number) if disc_number is not None else "1",
                release_date=album_release_date_str,
                year=str(album_release_year_int)
            )

            # --- QUALTIY STRING ---
            quality_str = "High (320kbps)" 
            if quality_tier and hasattr(quality_tier, 'name'):
                if "HIFI" in quality_tier.name or "VERY" in quality_tier.name:
                    quality_str = "Very High (320kbps)"
                elif "NORMAL" in quality_tier.name:
                    quality_str = "Normal (160kbps)"

            # --- RETURN OBJECT ---
            track_info_instance = TrackInfo(
                id=track_id,
                name=name,
                artists=artist_names,
                artist_id=artist_ids[0] if artist_ids else None,
                album_id=album_id_spotify,
                album=album_name,
                duration=duration_ms // 1000 if duration_ms else 0,
                cover_url=cover_url,
                explicit=explicit_bool, # Boolean Murni
                tags=tags_obj,
                codec=CodecEnum.VORBIS, 
                release_year=album_release_year_int,
                gid_hex=gid_hex_value,
                
                # Field Tambahan untuk Handler
                quality=quality_str,
                provider="Spotify",
                release_date=album_release_date_str,
                total_tracks=album_total_tracks,
                total_volumes=1
            )
            
            return track_info_instance

        except Exception as e:
            self.logger.error(f"Error in get_track_info: {e}", exc_info=True)
            return None 

    def _get_valid_token(self):
        """
        Helper untuk mendapatkan token Web API yang valid.
        Jika token expired/hilang, otomatis mencoba refresh.
        """
        # Coba ambil token langsung
        token = self._get_web_api_token()
        
        if token:
            return token
            
        # Jika gagal (None), coba load ulang kredensial (Refresh)
        self.logger.warning("Token Web API hilang/expired. Mencoba refresh session...")
        if self._load_credentials_and_init_session():
            # Coba ambil lagi setelah refresh
            token = self._get_web_api_token()
            if token:
                return token
        
        # Jika masih gagal, raise Error
        raise Exception("Gagal mendapatkan Token Spotify Web API yang valid.")

    def get_album_info(self, album_id, metadata=None, _retry_attempted=False):
        """
        Mengambil info album dan mengembalikannya sebagai OBJECT AlbumInfo.
        MODIFIKASI: 
        1. Menggunakan market=US agar kompatibel dengan Client Credentials.
        2. Mengambil 'small_cover_url' untuk Thumbnail ZIP.
        """
        try:
            # 1. Autentikasi
            token = self._get_valid_token()
            headers = {"Authorization": f"Bearer {token}"}
            
            # 2. Request API ke Spotify
            url = f"https://api.spotify.com/v1/albums/{album_id}?market=US"
            
            self.logger.info(f"Mengambil info album: {album_id}")
            r = requests.get(url, headers=headers)
            
            # --- PENANGANAN ERROR ---
            
            # CASE A: Rate Limit (429)
            if r.status_code == 429:
                if not _retry_attempted:
                    wait_time = int(r.headers.get("Retry-After", 3))
                    self.logger.warning(f"⚠️ Rate Limit (429). Menunggu {wait_time} detik...")
                    time.sleep(wait_time)
                    return self.get_album_info(album_id, metadata, _retry_attempted=True)
                else:
                    self.logger.error("❌ Gagal get_album_info: 429 (Rate Limit) terus-menerus.")
                    return None

            # CASE B: Token Expired (401)
            if r.status_code == 401 and not _retry_attempted:
                self.logger.warning("Token expired. Refreshing...")
                self._load_credentials_and_init_session() 
                return self.get_album_info(album_id, metadata, _retry_attempted=True)

            # CASE C: Error Lain (termasuk 400)
            if r.status_code != 200:
                self.logger.error(f"Gagal get_album_info: {r.status_code} - {r.text}")
                return None
            
            # --- PARSING DATA ---
            data = r.json()
            
            # [LOGIKA BARU] Ambil Cover Besar & Kecil
            cover_url = ""
            small_cover_url = ""
            
            if data.get("images"):
                cover_url = data["images"][0]["url"] # Gambar Terbesar (Original)
                
                # Cari gambar yang ukurannya <= 320px untuk Thumbnail ZIP
                # Telegram butuh gambar < 320px agar muncul sebagai ikon file
                for img in data["images"]:
                    if img.get("height") and img.get("height") <= 320:
                        small_cover_url = img["url"]
                        break
                
                # Fallback: jika tidak ada yang pas, ambil yang paling kecil yang tersedia
                if not small_cover_url: 
                    small_cover_url = data["images"][-1]["url"]
            
            # Parsing Tracks (dengan Pagination)
            raw_tracks = data.get("tracks", {}).get("items", [])
            next_url = data.get("tracks", {}).get("next")
            
            while next_url:
                try:
                    time.sleep(0.5) 
                    r_next = requests.get(next_url, headers=headers)
                    if r_next.status_code == 200:
                        next_data = r_next.json()
                        raw_tracks.extend(next_data.get("items", []))
                        next_url = next_data.get("next")
                    elif r_next.status_code == 429:
                        time.sleep(3)
                        continue
                    else:
                        break
                except Exception as e:
                    break

            track_objects = []
            for t in raw_tracks:
                if not t: continue
                artist_name = t["artists"][0]["name"] if t.get("artists") else "Unknown"
                
                track_obj = TrackInfo(
                    name=t.get("name"),
                    id=t.get("id"),
                    artists=[artist_name],
                    album=data.get("name"),
                    duration=t.get("duration_ms", 0) // 1000,
                    cover_url=cover_url,
                    release_year=data.get("release_date", "")[:4],
                    explicit=t.get("explicit", False),
                    tags=Tags(
                        track_number=t.get("track_number"),
                        total_tracks=data.get("total_tracks"),
                        disc_number=t.get("disc_number"),
                        album_artist=data["artists"][0]["name"] if data.get("artists") else "Unknown",
                        release_date=data.get("release_date")
                    )
                )
                track_objects.append(track_obj)
            
            self.logger.info(f"Berhasil memproses album: {data.get('name')} ({len(track_objects)} lagu)")

            # Return Object AlbumInfo LENGKAP dengan small_cover_url
            return AlbumInfo(
                name=data.get("name"),
                artist=data["artists"][0]["name"] if data.get("artists") else "Unknown",
                tracks=track_objects,
                all_track_cover_jpg_url=cover_url,
                release_year=data.get("release_date", "")[:4],
                id=data.get("id"),
                small_cover_url=small_cover_url  # <--- INI PENTING UNTUK ZIP
            )

        except Exception as e:
            self.logger.error(f"Error fatal parsing album info: {e}", exc_info=True)
            return None

    def get_playlist_info(self, playlist_id):
        """
        Mengambil info playlist dan mengembalikannya sebagai OBJECT PlaylistInfo.
        MODIFIKASI: 
        1. market=US (Fix 400 Error).
        2. Ambil 'small_cover_url' untuk Thumbnail ZIP.
        """
        try:
            # 1. Autentikasi
            token = self._get_valid_token()
            headers = {"Authorization": f"Bearer {token}"}
            
            # 2. Request API (Market US)
            url = f"https://api.spotify.com/v1/playlists/{playlist_id}?market=US"
            
            self.logger.info(f"Mengambil info playlist: {playlist_id}")
            r = requests.get(url, headers=headers)
            
            # Handle Token Expired
            if r.status_code == 401:
                self._load_credentials_and_init_session()
                token = self._get_valid_token()
                headers = {"Authorization": f"Bearer {token}"}
                r = requests.get(url, headers=headers)

            if r.status_code != 200:
                self.logger.error(f"Gagal get_playlist_info: {r.status_code} - {r.text}")
                return None
            
            data = r.json()
            
            # --- [LOGIKA BARU] AMBIL SMALL COVER UNTUK ZIP ---
            cover_url = ""
            small_cover_url = ""
            
            if data.get("images"):
                cover_url = data["images"][0]["url"] # Gambar Terbesar (HD)
                
                # Cari gambar yang ukurannya <= 320px (Syarat Thumbnail Telegram)
                for img in data["images"]:
                    if img.get("height") and img.get("height") <= 320:
                        small_cover_url = img["url"]
                        break
                
                # Fallback: jika tidak ada yang pas, ambil yang paling kecil
                if not small_cover_url: 
                    small_cover_url = data["images"][-1]["url"]
            # -------------------------------------------------
            
            # Parsing Tracks (Pagination Loop)
            raw_items = data.get("tracks", {}).get("items", [])
            next_url = data.get("tracks", {}).get("next")
            
            while next_url:
                try:
                    time.sleep(0.5)
                    r_next = requests.get(next_url, headers=headers)
                    if r_next.status_code == 200:
                        next_data = r_next.json()
                        raw_items.extend(next_data.get("items", []))
                        next_url = next_data.get("next")
                    else:
                        break
                except Exception:
                    break
            
            track_objects = []
            for item in raw_items:
                t = item.get("track")
                # Skip jika track kosong atau Local File (tidak punya ID)
                if not t or not t.get("id"): continue 
                
                artist_name = t["artists"][0]["name"] if t.get("artists") else "Unknown"
                
                # Ambil data Album
                alb = t.get("album", {})
                album_name = alb.get("name", "Unknown")
                
                # Cover per track (jika beda)
                track_cover = alb["images"][0]["url"] if alb.get("images") else cover_url

                track_obj = TrackInfo(
                    name=t.get("name"),
                    id=t.get("id"),
                    artists=[artist_name],
                    album=album_name,
                    duration=t.get("duration_ms", 0) // 1000,
                    cover_url=track_cover,
                    release_year=alb.get("release_date", "")[:4],
                    explicit=t.get("explicit", False),
                    tags=Tags(
                        # PENTING: Ambil Track Number & Disc Number dari Album Asli
                        # Ini agar format nama file "01 - Judul" sesuai album aslinya
                        track_number=t.get("track_number"),
                        total_tracks=alb.get("total_tracks"),
                        disc_number=t.get("disc_number"),
                        album_artist=artist_name, 
                        release_date=alb.get("release_date")
                    )
                )
                track_objects.append(track_obj)
            
            self.logger.info(f"Berhasil memproses playlist: {data.get('name')} ({len(track_objects)} lagu)")

            # Return PlaylistInfo LENGKAP dengan small_cover_url
            return PlaylistInfo(
                name=data.get("name"),
                creator=data.get("owner", {}).get("display_name", "Spotify"),
                tracks=track_objects,
                cover_url=cover_url,
                id=data.get("id"),
                small_cover_url=small_cover_url  # <--- Field Baru untuk ZIP
            )
            
        except Exception as e:
            self.logger.error(f"Error fatal parsing playlist info: {e}", exc_info=True)
            return None

    def get_several_artists(self, artist_ids: list, _retry_attempted: bool = False) -> list:
        """
        Get full artist objects (including genres) for up to 50 artist IDs.
        Returns a list of artist dicts in the same order as requested; missing/invalid IDs yield None in that slot.
        """
        if not artist_ids:
            return []
        ids_to_fetch = [str(aid) for aid in artist_ids if aid][:50]
        if not ids_to_fetch:
            return []

        web_api_token = self._get_web_api_token()
        if not web_api_token:
            if not self._load_credentials_and_init_session():
                raise SpotifyAuthError("Authentication required for get_several_artists.")
            web_api_token = self._get_web_api_token()
            if not web_api_token:
                raise SpotifyAuthError("Authentication failed for get_several_artists. No valid token.")

        url = "https://api.spotify.com/v1/artists"
        headers = {"Authorization": f"Bearer {web_api_token}"}
        params = {"ids": ",".join(ids_to_fetch)}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=DEFAULT_REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            artists = data.get("artists") or []
            # API returns list aligned with requested IDs; null for invalid/missing
            return list(artists)
        except requests.exceptions.HTTPError as http_err:
            if http_err.response.status_code == 401 and not _retry_attempted:
                self.web_api_stored_token = None
                if self._load_credentials_and_init_session():
                    return self.get_several_artists(artist_ids, _retry_attempted=True)
            raise SpotifyApiError(f"get_several_artists failed: {http_err.response.status_code}") from http_err
        except requests.exceptions.RequestException as req_err:
            raise SpotifyApiError(f"get_several_artists request error: {req_err}") from req_err

    def get_artist_info(self, artist_id: str, metadata: Optional['ArtistInfo'] = None, _retry_attempted: bool = False) -> Optional['ArtistInfo']:
        self.logger.info(f"SpotifyAPI: Attempting to get artist info for ID: {artist_id}{' (retry)' if _retry_attempted else ''}")

        # Get Web API token (uses custom credentials if available, otherwise librespot token)
        web_api_token = self._get_web_api_token()
        if not web_api_token:
            self.logger.info("SpotifyAPI.get_artist_info: Token missing. Attempting to load/refresh session.")
            if not self._load_credentials_and_init_session():
                self.logger.error("SpotifyAPI.get_artist_info: Session initialization failed.")
                raise SpotifyAuthError("Authentication required/failed for get_artist_info. Session could not be initialized.")
            web_api_token = self._get_web_api_token()
            if not web_api_token:
                self.logger.error("SpotifyAPI.get_artist_info: Still no access token after session initialization attempt.")
                raise SpotifyAuthError("Authentication failed for get_artist_info. No valid token.")

        artist_api_url = f"https://api.spotify.com/v1/artists/{artist_id}"
        headers = {"Authorization": f"Bearer {web_api_token}"}
        artist_data = None

        try:
            self.logger.debug(f"SpotifyAPI.get_artist_info: Getting basic artist details from {artist_api_url}")
            response = requests.get(artist_api_url, headers=headers, timeout=DEFAULT_REQUEST_TIMEOUT)
            response.raise_for_status() # Will raise HTTPError for 4xx/5xx
            artist_data = response.json()
            self.logger.info(f"SpotifyAPI.get_artist_info: Successfully retrieved basic artist data for {artist_id}: {artist_data.get('name')}")
        
        except requests.exceptions.HTTPError as http_err:
            if http_err.response.status_code == 401:
                self.logger.warning(f"SpotifyAPI.get_artist_info (basic details): Auth error (401) for {artist_id}. Token might be invalid.")
                if not _retry_attempted:
                    self.logger.info("SpotifyAPI.get_artist_info (basic details): Attempting re-auth and retry for 401.")
                    # Invalidate Web API token and re-initialize session
                    self.web_api_stored_token = None
                    if self._load_credentials_and_init_session():
                        self.logger.info("SpotifyAPI.get_artist_info (basic details): Re-auth successful. Retrying call.")
                        return self.get_artist_info(artist_id, metadata, _retry_attempted=True)
                    else:
                        self.logger.error("SpotifyAPI.get_artist_info (basic details): Re-auth failed after 401.")
                        raise SpotifyAuthError(f"Re-authentication failed for artist {artist_id} (basic details) after 401.")
                else:
                    self.logger.error(f"SpotifyAPI.get_artist_info (basic details): Auth error (401) for {artist_id} after retry.")
                    raise SpotifyAuthError(f"Auth failed for artist {artist_id} (basic details) (401) after retry.")
            elif http_err.response.status_code == 404:
                self.logger.warning(f"SpotifyAPI.get_artist_info: Artist {artist_id} not found (404).")
                raise SpotifyItemNotFoundError(f"Artist with ID {artist_id} not found.") from http_err
            else:
                self.logger.error(f"SpotifyAPI.get_artist_info: HTTP error fetching basic artist data for {artist_id}: {http_err.response.status_code} - {http_err.response.text[:200]}", exc_info=False)
                raise SpotifyApiError(f"Failed to get basic artist data for {artist_id}. Status: {http_err.response.status_code}, Text: {http_err.response.text[:200]}") from http_err
        except requests.exceptions.RequestException as req_err:
            self.logger.error(f"SpotifyAPI.get_artist_info: RequestException for basic artist data {artist_id}: {req_err}", exc_info=False)
            raise SpotifyApiError(f"Network error while fetching basic artist data for {artist_id}: {req_err}")
        except SpotifyAuthError: # Re-raise if it's already our specific auth error from session init
             raise
        except Exception as e: # Catch other initial errors like JSONDecodeError, etc.
            self.logger.error(f"SpotifyAPI.get_artist_info: Unexpected error for basic artist data {artist_id}: {e}", exc_info=True)
            if isinstance(e, SpotifyApiError): raise
            raise SpotifyApiError(f"An unexpected error occurred while fetching basic artist data for {artist_id}: {e}")

        if not artist_data:
            return None # Should have been raised as an error above if call failed

        # Fetch albums for the artist
        artist_albums_api_url = f"https://api.spotify.com/v1/artists/{artist_id}/albums"
        album_params = {'include_groups': 'album,single', 'limit': 50}
        if self.user_market:
            album_params['market'] = self.user_market
        
        all_album_items_from_api = []
        current_albums_url = artist_albums_api_url
        # Use Web API token for album calls (same as initial request)
        current_headers_for_albums = {"Authorization": f"Bearer {web_api_token}"}

        try:
            while current_albums_url:
                self.logger.debug(f"SpotifyAPI.get_artist_info: Fetching artist albums from {current_albums_url} with params {album_params if current_albums_url == artist_albums_api_url else 'implicit'}")
                paginated_response = requests.get(current_albums_url, headers=current_headers_for_albums, params=album_params if current_albums_url == artist_albums_api_url else None, timeout=DEFAULT_REQUEST_TIMEOUT)
                
                if paginated_response.status_code == 200:
                    albums_page_data = paginated_response.json()
                    all_album_items_from_api.extend(albums_page_data.get('items', []))
                    current_albums_url = albums_page_data.get('next')
                    album_params = {} # Clear params for subsequent `next` calls as they are full URLs
                elif paginated_response.status_code == 401 and not _retry_attempted:
                    self.logger.warning(f"SpotifyAPI.get_artist_info (albums pagination): Auth error (401) for artist {artist_id}. Invalidating token, attempting re-auth.")
                    # Invalidate Web API token and re-initialize session
                    self.web_api_stored_token = None
                    if self._load_credentials_and_init_session():
                        self.logger.info("SpotifyAPI.get_artist_info (albums pagination): Re-auth successful. Retrying the entire get_artist_info call.")
                        # Retry the whole get_artist_info, as base artist info might also need re-fetch with new token
                        return self.get_artist_info(artist_id, metadata, _retry_attempted=True)
                    else:
                        self.logger.error("SpotifyAPI.get_artist_info (albums pagination): Re-auth failed.")
                        raise SpotifyAuthError(f"Re-authentication failed for artist {artist_id} albums pagination.")
                else:
                    paginated_response.raise_for_status() # Raise HTTPError for other bad statuses on album fetch
                    # Should not be reached if raise_for_status() works, but as a fallback:
                    self.logger.warning(f"SpotifyAPI.get_artist_info: Breaking album pagination for artist {artist_id} due to status {paginated_response.status_code}.")
                    break
            self.logger.info(f"SpotifyAPI.get_artist_info: Fetched {len(all_album_items_from_api)} album items for artist {artist_id}")

        except requests.exceptions.HTTPError as http_err_albums:
            # This will catch non-401 HTTP errors from album pagination raised by raise_for_status()            
            self.logger.error(f"SpotifyAPI.get_artist_info: HTTP error fetching albums for artist {artist_id}: {http_err_albums.response.status_code} - {http_err_albums.response.text[:200]}", exc_info=False)            
        except requests.exceptions.RequestException as req_err_albums:
            self.logger.error(f"SpotifyAPI.get_artist_info: RequestException for artist albums {artist_id}: {req_err_albums}", exc_info=False)
        except SpotifyAuthError: # Re-raise if it's already our specific auth error
             raise
        except Exception as e_albums: # Other errors during album fetching
            self.logger.error(f"SpotifyAPI.get_artist_info: Unexpected error fetching albums for artist {artist_id}: {e_albums}", exc_info=True)

        simplified_albums_for_artist_info = []
        for album_item in all_album_items_from_api:
            if isinstance(album_item, dict):
                album_cover_url = None
                if album_item.get('images') and len(album_item['images']) > 0:
                    album_cover_url = album_item['images'][0].get('url')
                release_year = 0
                release_date_str = album_item.get('release_date')
                if release_date_str and isinstance(release_date_str, str) and len(release_date_str) >= 4:
                    try: release_year = int(release_date_str[:4])
                    except ValueError: pass
                simplified_albums_for_artist_info.append({
                    'id': album_item.get('id'),
                    'name': album_item.get('name'),
                    'album_type': album_item.get('album_type'),
                    'release_year': release_year,
                    'cover_url': album_cover_url,
                    'total_tracks': album_item.get('total_tracks')
                })
        artist_name = artist_data.get('name', "Unknown Artist")
        artist_image_url = None
        if artist_data.get('images') and len(artist_data['images']) > 0:
            artist_image_url = artist_data['images'][0].get('url')
        try:
            artist_info_obj = ArtistInfo(
                name=artist_name,
                albums=simplified_albums_for_artist_info,
            )
            self.logger.info(f"SpotifyAPI.get_artist_info: Successfully created ArtistInfo object for {artist_name} ({artist_id}) with {len(simplified_albums_for_artist_info)} albums.")
            return artist_info_obj
        except Exception as e_artist_info_create:
            self.logger.error(f"SpotifyAPI.get_artist_info: Error creating ArtistInfo object for {artist_name} ({artist_id}): {e_artist_info_create}", exc_info=True)
            return None

    def get_show_info(self, show_id: str, metadata: Optional['AlbumInfo'] = None, _retry_attempted: bool = False) -> Optional[dict]:
        """Get show information from Spotify API. Returns show data in album-like format for compatibility."""
        self.logger.info(f"SpotifyAPI: Attempting to get show info for ID: {show_id}{' (retry)' if _retry_attempted else ''}")

        # Get Web API token (uses custom credentials if available, otherwise librespot token)
        web_api_token = self._get_web_api_token()
        if not web_api_token:
            self.logger.info("SpotifyAPI.get_show_info: Token missing. Attempting to load/refresh session.")
            if not self._load_credentials_and_init_session():
                self.logger.error("SpotifyAPI.get_show_info: Session initialization failed.")
                raise SpotifyAuthError("Authentication required/failed for get_show_info. Session could not be initialized.")
            web_api_token = self._get_web_api_token()
            if not web_api_token:
                self.logger.error("SpotifyAPI.get_show_info: Still no access token after session initialization attempt.")
                raise SpotifyAuthError("Authentication failed for get_show_info. No valid token.")

        # First get basic show information
        api_url = f"https://api.spotify.com/v1/shows/{show_id}"
        headers = {"Authorization": f"Bearer {web_api_token}"}
        params = {}
        if self.user_market:
            params['market'] = self.user_market

        try:
            self.logger.debug(f"SpotifyAPI.get_show_info: Making GET request to {api_url} with params {params}")
            response = requests.get(api_url, headers=headers, params=params, timeout=DEFAULT_REQUEST_TIMEOUT)

            if response.status_code == 200:
                show_data = response.json()
                self.logger.info(f"SpotifyAPI.get_show_info: Successfully retrieved show data for {show_id}")
                
                # Now get all episodes for the show using separate endpoint
                episodes_list = []
                episodes_api_url = f"https://api.spotify.com/v1/shows/{show_id}/episodes"
                episodes_params = {'limit': 50}  # Maximum limit per request
                if self.user_market:
                    episodes_params['market'] = self.user_market
                
                current_episodes_url = episodes_api_url
                
                while current_episodes_url:
                    self.logger.debug(f"SpotifyAPI.get_show_info: Fetching episodes from {current_episodes_url}")
                    # Use Web API token for paginated calls (same as initial request)
                    current_headers = {"Authorization": f"Bearer {web_api_token}"}
                    
                    try:
                        episodes_response = requests.get(current_episodes_url, headers=current_headers, params=episodes_params, timeout=DEFAULT_REQUEST_TIMEOUT)
                        episodes_response.raise_for_status()
                        episodes_data = episodes_response.json()
                        
                        episodes_items = episodes_data.get('items', [])
                        
                        for episode in episodes_items:
                            episode_id = episode.get('id')
                            if episode_id:
                                episodes_list.append(episode_id)
                        
                        # Check for next page
                        current_episodes_url = episodes_data.get('next')
                        if current_episodes_url:
                            episodes_params = {}  # URL already contains the parameters for next page
                        
                    except requests.exceptions.HTTPError as http_err:
                        self.logger.error(f"HTTP error fetching episodes for show {show_id}: {http_err.response.status_code} - {http_err.response.text[:200]}")
                        break
                    except Exception as e:
                        self.logger.error(f"Error fetching episodes for show {show_id}: {e}")
                        break
                
                # Convert to album-like format
                album_data = {
                    'id': show_id,
                    'name': show_data.get('name', 'Unknown Show'),
                    'publisher': show_data.get('publisher', 'Unknown Publisher'),
                    'description': show_data.get('description', ''),
                    'total_tracks': len(episodes_list),
                    'tracks': episodes_list,  # List of episode IDs
                    'images': show_data.get('images', []),
                    'type': 'show'
                }
                
                return album_data
            elif response.status_code == 401:
                self.logger.warning(f"SpotifyAPI.get_show_info: Authorization error (401) for {show_id}. Token might be invalid.")
                if not _retry_attempted:
                    self.logger.info("SpotifyAPI.get_show_info: Attempting re-authentication and retry for 401.")
                    # Invalidate Web API token and re-initialize session
                    self.web_api_stored_token = None
                    if self._load_credentials_and_init_session():
                        self.logger.info("SpotifyAPI.get_show_info: Re-authentication successful. Retrying original call.")
                        return self.get_show_info(show_id, metadata, _retry_attempted=True)
                    else:
                        self.logger.error("SpotifyAPI.get_show_info: Re-authentication failed after 401.")
                        raise SpotifyAuthError(f"Re-authentication failed for show {show_id} after 401.")
                else:
                    self.logger.error(f"SpotifyAPI.get_show_info: Authorization error (401) for {show_id} even after retry.")
                    raise SpotifyAuthError(f"Authorization failed for show {show_id} (401) after retry.")
            elif response.status_code == 404:
                self.logger.warning(f"SpotifyAPI.get_show_info: Show {show_id} not found (404).")
                raise SpotifyItemNotFoundError(f"Show with ID {show_id} not found.")
            else:
                self.logger.error(f"SpotifyAPI.get_show_info: Failed to get show data for {show_id}. Status: {response.status_code}, Response: {response.text}")
                raise SpotifyApiError(f"Failed to get show data for {show_id}. Status: {response.status_code}, Response Text: {response.text[:200]}")

        except requests.exceptions.HTTPError as http_err:
            if http_err.response.status_code == 401:
                self.logger.warning(f"SpotifyAPI.get_show_info: HTTPError 401 caught for {show_id}.")
                if not _retry_attempted:
                    self.logger.info("SpotifyAPI.get_show_info: Attempting re-authentication and retry for HTTPError 401.")
                    # Invalidate Web API token and re-initialize session
                    self.web_api_stored_token = None
                    if self._load_credentials_and_init_session():
                        self.logger.info("SpotifyAPI.get_show_info: Re-authentication successful. Retrying original call.")
                        return self.get_show_info(show_id, metadata, _retry_attempted=True)
                    else:
                        self.logger.error("SpotifyAPI.get_show_info: Re-authentication failed after HTTPError 401.")
                        raise SpotifyAuthError(f"Re-authentication failed for show {show_id} after HTTPError 401.")
                else:
                    self.logger.error(f"SpotifyAPI.get_show_info: HTTPError 401 for {show_id} even after retry.")
                    raise SpotifyAuthError(f"Authorization failed for show {show_id} (HTTPError 401) after retry.")
            else:
                self.logger.error(f"SpotifyAPI.get_show_info: HTTPError {http_err.response.status_code} for {show_id}: {http_err.response.text[:200]}")
                raise SpotifyApiError(f"HTTP error fetching show {show_id}: {http_err.response.status_code} - {http_err.response.text[:200]}") from http_err
        except requests.exceptions.RequestException as e:
            self.logger.error(f"SpotifyAPI.get_show_info: RequestException for {show_id}: {e}", exc_info=False)
            raise SpotifyApiError(f"Network error while fetching show {show_id}: {e}")
        except SpotifyAuthError:
            raise
        except Exception as e:
            self.logger.error(f"SpotifyAPI.get_show_info: Unexpected error for {show_id}: {e}", exc_info=True)
            if isinstance(e, SpotifyApiError):
                raise
            raise SpotifyApiError(f"An unexpected error occurred while fetching show {show_id}: {e}")

    def get_episode_by_id(self, episode_id: str, market: Optional[str] = None, _retry_attempted: bool = False) -> Optional[dict]:
        """Get episode details by its Spotify ID using the Web API."""
        self.logger.debug(f"SpotifyAPI.get_episode_by_id entered for episode_id: {episode_id}, market: {market}{', retry' if _retry_attempted else ''}")

        # Get Web API token (uses custom credentials if available, otherwise librespot token)
        web_api_token = self._get_web_api_token()
        if not web_api_token:
            self.logger.info("SpotifyAPI.get_episode_by_id: Token missing. Attempting to load/refresh session.")
            if not self._load_credentials_and_init_session():
                self.logger.error("SpotifyAPI.get_episode_by_id: Session initialization failed.")
                raise SpotifyAuthError("Authentication required/failed for get_episode_by_id. Session could not be initialized.")
            web_api_token = self._get_web_api_token()
            if not web_api_token:
                self.logger.error("SpotifyAPI.get_episode_by_id: Still no access token after session initialization attempt.")
                raise SpotifyAuthError("Authentication failed for get_episode_by_id. No valid token.")

        headers = {"Authorization": f"Bearer {web_api_token}"}
        params = {}
        if market:
            params["market"] = market
        elif self.user_market:
            params["market"] = self.user_market

        api_url = f"https://api.spotify.com/v1/episodes/{episode_id}"
        self.logger.debug(f"Calling Spotify Web API: GET {api_url} with params: {params}")
        try:
            response = requests.get(api_url, headers=headers, params=params, timeout=DEFAULT_REQUEST_TIMEOUT)
            self.logger.debug(f"Episode API response status: {response.status_code}")
            response.raise_for_status()  # Will raise HTTPError for 4xx/5xx status codes
            episode_data = response.json()
            self.logger.debug(f"get_episode_by_id SUCCEEDED for episode_id: {episode_id}. Data keys: {list(episode_data.keys())}")
            return episode_data
        except requests.exceptions.HTTPError as http_err:
            if http_err.response.status_code == 401:
                self.logger.warning(f"SpotifyAPI.get_episode_by_id: Auth error (401) for episode {episode_id}. Token might be invalid.")
                if not _retry_attempted:
                    self.logger.info("SpotifyAPI.get_episode_by_id: Attempting re-auth and retry for 401.")
                    # Invalidate Web API token and re-initialize session
                    self.web_api_stored_token = None
                    if self._load_credentials_and_init_session():
                        self.logger.info("SpotifyAPI.get_episode_by_id: Re-auth successful. Retrying call.")
                        return self.get_episode_by_id(episode_id, market, _retry_attempted=True)
                    else:
                        self.logger.error("SpotifyAPI.get_episode_by_id: Re-auth failed after 401.")
                        raise SpotifyAuthError(f"Re-authentication failed for episode {episode_id} after 401.")
                else:
                    self.logger.error(f"SpotifyAPI.get_episode_by_id: Auth error (401) for episode {episode_id} after retry.")
                    raise SpotifyAuthError(f"Auth failed for episode {episode_id} (401) after retry.")
            elif http_err.response.status_code == 404:
                self.logger.warning(f"Episode {episode_id} not found via Spotify API (404).")
                raise SpotifyItemNotFoundError(f"Episode {episode_id} not found.") from http_err
            elif http_err.response.status_code == 403:
                self.logger.warning(f"Episode {episode_id} access forbidden (403) - might be region locked or premium only.")
                raise SpotifyItemNotFoundError(f"Episode {episode_id} access forbidden.") from http_err
            else:
                self.logger.error(f"HTTP error fetching episode {episode_id}: {http_err.response.status_code} - {http_err.response.text[:200]}", exc_info=False)
                raise SpotifyApiError(f"Spotify API request failed for episode {episode_id}: {http_err.response.status_code} - {http_err.response.text[:200]}") from http_err
        except requests.exceptions.RequestException as req_err:
            self.logger.error(f"Request error fetching episode {episode_id}: {req_err}", exc_info=True)
            raise SpotifyApiError(f"Request failed for episode {episode_id}: {req_err}") from req_err
        except Exception as e:
            self.logger.error(f"Unexpected error fetching episode {episode_id}: {e}", exc_info=True)
            if isinstance(e, SpotifyApiError):
                raise
            raise SpotifyApiError(f"An unexpected error occurred while fetching episode {episode_id}: {e}")

    def get_episode_download(self, **kwargs) -> Optional[TrackDownloadInfo]:
        """Download episode audio using librespot. Same approach as get_track_download but for episodes."""
        episode_id_base62 = kwargs.get("track_id_str") or kwargs.get("track_id") or kwargs.get("episode_id")
        quality_tier = kwargs.get("quality_tier")
        download_options = kwargs.get("codec_options")
        track_info_obj = kwargs.get("track_info_obj")

        if not episode_id_base62:
            self.logger.error("get_episode_download: No episode_id provided in kwargs")
            raise SpotifyApiError("No episode_id provided for download")

        # Convert base62 episode ID to hex GID format required by librespot
        episode_id_hex = self._convert_base62_to_gid_hex(episode_id_base62)
        if not episode_id_hex:
            self.logger.error(f"Failed to convert episode_id '{episode_id_base62}' to hex GID format")
            raise SpotifyApiError(f"Failed to convert episode_id '{episode_id_base62}' to hex GID format")

        if not self._is_session_valid(self.librespot_session):
            self.logger.error("Librespot session is not active or not logged in for episode download.")
            if not self._load_credentials_and_init_session() or not self._is_session_valid(self.librespot_session):
                 raise SpotifyAuthError("Authentication required/failed for episode download.")
        
        # Use EpisodeId for episodes (not TrackId)
        episode_id_obj = EpisodeId.from_hex(episode_id_hex)
        temp_file_path = None
        try:
            self.logger.info(f"Fetching librespot Episode metadata for GID hex: {episode_id_hex}")
            librespot_audio_quality_mode = LibrespotAudioQualityEnum.NORMAL
            qt_str = None
            if hasattr(quality_tier, 'name'):
                qt_str = quality_tier.name.upper()
            elif isinstance(quality_tier, str):
                qt_str = quality_tier.upper()
            if qt_str == "LOSSLESS" or qt_str == "HIFI" or qt_str == "VERY_HIGH":
                librespot_audio_quality_mode = LibrespotAudioQualityEnum.VERY_HIGH
            elif qt_str == "HIGH":
                librespot_audio_quality_mode = LibrespotAudioQualityEnum.HIGH
            elif qt_str == "LOW":
                # LOW doesn't exist in librespot, map to NORMAL (lowest available quality)
                librespot_audio_quality_mode = LibrespotAudioQualityEnum.NORMAL
            self.logger.info(f"Quality tier input: '{quality_tier}', resolved to string: '{qt_str}', mapped to librespot AudioQuality mode: {librespot_audio_quality_mode}")
            
            # Ensure our audio key filter is still active before librespot operations
            if hasattr(self, '_audio_key_filter'):
                # Reapply filter to ensure it's active for this operation
                for handler in logging.getLogger().handlers:
                    if self._audio_key_filter not in handler.filters:
                        handler.addFilter(self._audio_key_filter)
            
            content_feeder = self.librespot_session.content_feeder()
            self.logger.info(f"Attempting to load episode {episode_id_hex} using content_feeder.load_episode with VorbisOnlyAudioQuality.")
            stream_loader = content_feeder.load_episode(
                episode_id_obj,
                VorbisOnlyAudioQuality(librespot_audio_quality_mode),
                False, 
                None   
            )
            if not stream_loader or not hasattr(stream_loader, 'input_stream') or not stream_loader.input_stream:
                self.logger.error(f"Librespot returned no stream_loader or input_stream for episode {episode_id_hex} (EpisodeId: {str(episode_id_obj)}).")
                try:
                    # Try to get episode metadata using the proper API method
                    episode_metadata_check = self.librespot_session.api().get_metadata_4_episode(episode_id_obj)
                    if episode_metadata_check and not episode_metadata_check.file:
                         self.logger.error(f"Additionally, episode metadata for GID {episode_id_hex} has no associated audio files.")
                         raise SpotifyTrackUnavailableError(f"No audio files listed for episode GID {episode_id_hex} and stream_loader failed.")
                    elif not episode_metadata_check:
                         self.logger.error(f"Additionally, failed to get any episode metadata from librespot for GID hex: {episode_id_hex}")
                except Exception as meta_err:
                     self.logger.error(f"Error during additional metadata check for {episode_id_hex} after stream_loader failure: {meta_err}")
                raise SpotifyTrackUnavailableError(f"Failed to load audio stream (no stream_loader or input_stream) for episode GID {episode_id_hex}")
            
            raw_audio_byte_stream = stream_loader.input_stream.stream()
            temp_file_path = self._save_stream_to_temp_file(raw_audio_byte_stream, CodecEnum.VORBIS)
            if not temp_file_path:
                self.logger.error(f"Failed to save downloaded stream for episode GID {episode_id_hex} to a temp file.")
                if hasattr(stream_loader, 'input_stream') and stream_loader.input_stream and hasattr(stream_loader.input_stream, 'close'):
                    try:
                        stream_loader.input_stream.close()
                    except Exception as close_ex:
                        self.logger.warning(f"Exception while closing input_stream after save failure for episode {episode_id_hex}: {close_ex}")
                return None
            
            self.logger.info(f"Successfully downloaded episode {episode_id_hex} to {temp_file_path}")
            if track_info_obj and hasattr(track_info_obj, 'codec'):
                self.logger.info(f"Updating track_info_obj.codec to VORBIS for episode: {track_info_obj.name if hasattr(track_info_obj, 'name') else episode_id_hex}")
                track_info_obj.codec = CodecEnum.VORBIS
            elif track_info_obj:
                self.logger.warning(f"track_info_obj for {episode_id_hex} provided but has no 'codec' attribute to update.")
            
            return TrackDownloadInfo(
                download_type=DownloadEnum.TEMP_FILE_PATH,
                temp_file_path=temp_file_path,
            )
        except SpotifyAuthError: 
            raise
        except SpotifyTrackUnavailableError as e: 
            self.logger.warning(f"Episode {episode_id_hex} is unavailable for download: {e}")
            raise 
        except SpotifyItemNotFoundError as e: 
            self.logger.warning(f"Episode metadata for {episode_id_hex} not found: {e}")
            raise 
        except RuntimeError as rt_err:
            if "Failed fetching audio key!" in str(rt_err):
                # Suppress the noisy warning message - it's handled by the rate limit detection
                clean_error_msg = "Failed fetching audio key!"
                raise SpotifyRateLimitDetectedError(f"Rate limit suspected: {clean_error_msg}") from rt_err
            elif str(rt_err) == "Cannot get alternative track":
                self.logger.warning(f"Episode {episode_id_hex} is unavailable (librespot: Cannot get alternative track).")
                raise SpotifyTrackUnavailableError(f"Episode {episode_id_hex} is unavailable (Cannot get alternative track)") from rt_err
            else:
                self.logger.error(f"Unhandled RuntimeError during get_episode_download for {episode_id_hex}: {rt_err}", exc_info=True)
                raise SpotifyApiError(f"Runtime error during episode download {episode_id_hex}: {rt_err}") from rt_err
        except Exception as e:
            self.logger.error(f"Unexpected error during get_episode_download for {episode_id_hex}: {e}", exc_info=True)
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                    self.logger.info(f"Cleaned up temp file {temp_file_path} after error in get_episode_download.")
                except OSError as unlink_e:
                    self.logger.error(f"Error unlinking temp file {temp_file_path} during error handling: {unlink_e}")
            raise SpotifyApiError(f"Failed to download episode {episode_id_hex}: {e}") from e

    def get_episode_info(self, episode_id: str, quality_tier: QualityEnum, codec_options: CodecOptions, **extra_kwargs) -> Optional[TrackInfo]:
        """Get episode information and convert to TrackInfo format for compatibility."""
        self.logger.info(f"SpotifyAPI: get_episode_info for episode_id: {episode_id}")
        
        try:
            # Get episode data from API
            self.logger.debug(f"Calling get_episode_by_id for {episode_id}")
            episode_data = self.get_episode_by_id(episode_id)
            if not episode_data:
                self.logger.error(f"No episode data returned for episode_id: {episode_id}")
                return None
            
            self.logger.debug(f"Episode data keys: {list(episode_data.keys())}")
            
            # Convert episode data to TrackInfo format
            track_name = episode_data.get('name', 'Unknown Episode')
            description = episode_data.get('description', '')
            duration_ms = episode_data.get('duration_ms', 0)
            explicit = episode_data.get('explicit', False)
            release_date = episode_data.get('release_date', '')
            
            self.logger.debug(f"Episode basic info - Name: {track_name}, Duration: {duration_ms}ms")
            
            # Get show (album) information
            show_data = episode_data.get('show', {})
            album_name = show_data.get('name', 'Unknown Show')
            album_id = show_data.get('id', None)
            publisher = show_data.get('publisher', 'Unknown Publisher')
            
            self.logger.debug(f"Show info - Name: {album_name}, Publisher: {publisher}")
            
            # Use publisher as artist
            artists = [publisher] if publisher else ['Unknown Publisher']
            artist_id = None  # Shows don't have artist IDs
            
            # Get cover art
            cover_url = None
            if show_data.get('images') and len(show_data['images']) > 0:
                cover_url = show_data['images'][0].get('url')
                self.logger.debug(f"Using show cover: {cover_url}")
            elif episode_data.get('images') and len(episode_data['images']) > 0:
                cover_url = episode_data['images'][0].get('url')
                self.logger.debug(f"Using episode cover: {cover_url}")
            
            # Parse release year
            release_year = 0
            if release_date and len(release_date) >= 4:
                try:
                    release_year = int(release_date[:4])
                except ValueError:
                    self.logger.warning(f"Could not parse year from release_date: {release_date}")
            
            # Create Tags object
            self.logger.debug("Creating Tags object")
            tags = Tags()
            tags.album_artist = publisher
            tags.release_date = release_date
            tags.disc_number = 1
            tags.track_number = 1
            
            # Create TrackInfo object with episode data
            self.logger.debug("Creating TrackInfo object")
            track_info = TrackInfo(
                name=track_name,
                id=episode_id,  # Add the episode ID so album download can access it
                album_id=album_id,
                album=album_name,
                artists=artists,
                artist_id=artist_id,
                release_year=release_year,
                explicit=explicit,
                cover_url=cover_url,
                tags=tags,
                codec=CodecEnum.VORBIS,  # Episodes will be downloaded as VORBIS
                duration=int(duration_ms / 1000) if duration_ms else 0,
                # Add episode-specific info in error field for debugging
                error=None
            )
            
            self.logger.info(f"Successfully converted episode '{track_name}' to TrackInfo format")
            return track_info
            
        except Exception as e:
            self.logger.error(f"Error getting episode info for {episode_id}: {e}", exc_info=True)
            return None

# --- Main function for testing or standalone use (Optional) ---
def main():
    parser = argparse.ArgumentParser(description="Search Spotify via its Web API using librespot for auth.")
    parser.add_argument("search_type", choices=["album", "track", "artist", "playlist", "show", "episode"], help="The type of item to search for.")
    parser.add_argument("query", help="The search query string.")
    parser.add_argument("--limit", type=int, default=5, help="Number of results to display.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    spotify_client = SpotifyAPI(config={}, module_controller=None)
    try:
        results = spotify_client.search(query_type_enum_or_str=args.search_type, query_str=args.query, limit=args.limit)
        if results:
            print(f"--- Spotify Search Results for '{args.query}' (Type: {args.search_type}) ---")
            for i, item in enumerate(results):
                item_name = item.get("name", "N/A")
                item_id = item.get("id", "N/A")
                display_line = f"  {i+1}. {item_name} [ID: {item_id}]"
                if args.search_type == "track":
                    artists = ", ".join([artist.get("name", "N/A") for artist in item.get("artists", [])])
                    album_name = item.get("album", {}).get("name", "N/A")
                    display_line += f" - Artists: {artists} (Album: {album_name})"
                elif args.search_type == "album":
                    artists = ", ".join([artist.get("name", "N/A") for artist in item.get("artists", [])])
                    display_line += f" - Artists: {artists}"
                elif args.search_type == "artist":
                    genres = ", ".join(item.get("genres", []))
                    pop = item.get("popularity")
                    display_line += f" - Genres: {genres if genres else 'N/A'} (Popularity: {pop if pop is not None else 'N/A'})"
                elif args.search_type == "playlist":
                    owner = item.get("owner", {}).get("display_name", "N/A")
                    tracks_total = item.get("tracks", {}).get("total", "N/A")
                    display_line += f" - Owner: {owner} (Tracks: {tracks_total})"
                elif args.search_type == "show":
                    publisher = item.get("publisher", "N/A")
                    episodes_total = item.get("total_episodes", "N/A")
                    display_line += f" - Publisher: {publisher} (Episodes: {episodes_total})"
                elif args.search_type == "episode":
                    show_name = item.get("show", {}).get("name", "N/A")
                    release_date = item.get("release_date", "N/A")
                    duration_ms = item.get("duration_ms", 0)
                    duration_s = duration_ms // 1000
                    duration_m = duration_s // 60
                    duration_s %= 60
                    display_line += f" - Show: {show_name} (Released: {release_date}, Duration: {duration_m}m{duration_s}s)"
                print(display_line)
            else:
                print(f"No results found for '{args.query}' (Type: {args.search_type}).")
    except SpotifyApiError as e: 
        print(f"A Spotify API error occurred: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        traceback.print_exc()
    finally:
        spotify_client.close_session()

if __name__ == "__main__":
    main()
