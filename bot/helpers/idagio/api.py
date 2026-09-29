# [GANTI SELURUH FILE: bot/helpers/idagio/api.py]

import requests
import asyncio
from datetime import timedelta, datetime
from os import urandom
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bot.logger import LOGGER

class IdagioError(Exception):
    pass

class IdagioApi:
    def __init__(self, exception, proxy: str = None):
        self.API_URL = 'https://api.idagio.com/'
        self.exception = exception
        self.device_id = None
        self.access_token = None
        self.expires = None
        self.premium = False
        self.proxy = proxy

        self.s = requests.Session()
        
        if self.proxy:
            self.s.proxies = {
                'http': self.proxy,
                'https': self.proxy
            }

        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.s.mount("https://", adapter)
        self.s.mount("http://", adapter)

    def headers(self, use_access_token: bool = False):
        return {
            'User-Agent': 'Android 3.3.0 (Build 3030000) [release]',
            'Authorization': f'Bearer {self.access_token}' if use_access_token else None,
            'X-Client': 'android',
            'X-Client-Version': '3.3.0',
            'X-Device-ID': self.device_id,
            'X-Device-Class': 'PHONE'
        }

    def auth(self, username: str, password: str) -> dict:
        self.device_id = urandom(8).hex()

        try:
            r = self.s.post(f'{self.API_URL}v2.1/oauth', data={
                'client_id': 'com.idagio.app.android',
                'client_secret': 'adbisIGrocsUckWyodUj2knedpyepubGurlyeawosShyufJishleseanreBlogIbCefHodCigNafweegyeebraft'
                                 'EdnooshDeavolirdoppEcIassyet9CirIrnofmaj',
                'username': username,
                'password': password,
                'grant_type': 'password',
            }, timeout=30)
        except requests.exceptions.RequestException as e:
            raise self.exception(f"Koneksi login Idagio gagal: {e}")

        if r.status_code != 200:
            raise self.exception(r.json().get('error_description', 'Login gagal'))

        r = r.json()
        self.access_token = r['access_token']
        self.expires = datetime.now() + timedelta(seconds=r['expires_in'])
        
        self.valid_account()
        if not self.premium:
            raise self.exception('Akun tidak memiliki langganan Premium/Premium+ aktif.')

        LOGGER.info(f"Idagio: Login berhasil untuk {username}")
        return r
    
    def valid_account(self):
        try:
            account_data = self.get_account()
            self.premium = account_data.get('premium', False)
            return self.premium
        except Exception as e:
            LOGGER.error(f"Idagio: Gagal memvalidasi akun: {e}")
            return False

    def set_session(self, session: dict):
        self.access_token = session.get('access_token')
        self.device_id = session.get('device_id')
        self.expires = session.get('expires')

    def get_session(self):
        return {
            'access_token': self.access_token,
            'device_id': self.device_id,
            'expires': self.expires
        }

    def _get(self, endpoint: str, params: dict = None):
        if not params:
            params = {}

        try:
            r = self.s.get(f'{self.API_URL}{endpoint}', params=params, headers=self.headers(use_access_token=True), timeout=30)
        except requests.exceptions.RequestException as e:
            raise self.exception(f"Permintaan Idagio gagal ({endpoint}): {e}")

        if r.status_code == 401:
            raise self.exception(f"Token akses Idagio kedaluwarsa. ({r.text})")

        if r.status_code not in {200, 201, 202}:
            raise self.exception(f"Error API Idagio {r.status_code}: {r.text}")

        return r.json()

    def get_account(self):
        return self._get('v2.1/user')

    def get_search(self, query: str):
        return self._get('v1.8/lucene/search', params={'term': query, 'full': True})

    def get_recording(self, recording_id: str):
        return self._get(f'v2.0/metadata/recordings/{recording_id}').get('result')

    def get_album(self, album_id: str):
        return self._get(f'v2.0/metadata/albums/{album_id}').get('result')

    def get_playlist(self, playlist_id: str):
        return self._get(f'v2.0/playlists/{playlist_id}').get('result')

    def get_artist(self, artist_id: str):
        return self._get(f'artists.v3/{artist_id}').get('result')

    def get_artist_albums(self, artist_id: str, cursor: str = None, limit: int = 100):
        return self._get('v2.0/metadata/albums/filter', params={'artist': artist_id, 'sort': 'copyrightYear', 'limit': limit, 'cursor': cursor})

    def get_artist_recordings(self, artist_id: str, cursor: str = None, limit: int = 100):
        return self._get('v2.0/metadata/recordings/filter', params={'artist': artist_id, 'sort': 'chronological', 'limit': limit, 'cursor': cursor})

    def get_artist_works(self, artist_id: str, cursor: str = None, limit: int = 100):
        return self._get('v2.0/metadata/works/filter', params={'artist': artist_id, 'limit': limit, 'cursor': cursor})

    def get_track_stream_2(self, track_id: str, quality: int = 90):
        try:
            r = self.s.get(f'{self.API_URL}v1.8/content/track/{track_id}', params={
                'quality': quality, 'format': 2, 'client_type': 'sonos-2', 'client_version': '17.2.4', 'device_id': 'web'
            }, headers=self.headers(use_access_token=True), timeout=30)
        except requests.exceptions.RequestException as e:
            raise self.exception(f"Sonos stream error: {e}")

        if r.status_code != 200:
            raise self.exception(r.text)

        return [r.json()]

    def get_track_stream(self, track_id: str, quality: int = 90):
        try:
            r = self.s.post(f'{self.API_URL}v2.0/streams/bulk', params={
                'quality': quality, 'client_type': 'android-3', 'client_version': '3.3.0', 'device_id': self.device_id
            }, json={"ids": [track_id]}, headers=self.headers(use_access_token=True), timeout=30)
        except requests.exceptions.RequestException as e:
            raise self.exception(f"Bulk stream error: {e}")

        if r.status_code != 200:
            raise self.exception(r.text)

        return r.json().get('results')

    def close_session(self):
        if self.s:
            self.s.close()
