# [GANTI FILE: bot/helpers/tidal/tidal_api.py]

import aiohttp
import asyncio
import aiolimiter
import logging
import time

from datetime import datetime, timedelta
from traceback import format_exc

from config import Config
from bot.logger import LOGGER


class TidalApi:
    def __init__(self):
        self.TIDAL_API_BASE = 'https://api.tidal.com/v1/'
        
        self.ratelimit = aiolimiter.AsyncLimiter(30, 60)
        self.session: aiohttp.ClientSession | None = None

        self.tv_session: TvSession | None = None
        self.mobile_hires: MobileSession | None = None
        self.mobile_atmos: MobileSession | None = None

        self.quality = 'LOW'
        self.spatial = 'OFF'
        self.sub_type: str | None = None
        self.user_data = {}
        
        self.saved = []

        self.user_id: str | None = None
        self.country_code: str | None = None

    def _ensure_http_session(self):
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            connector = aiohttp.TCPConnector(limit=50, keepalive_timeout=30, enable_cleanup_closed=True)
            self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            if self.tv_session:
                self.tv_session.session = self.session
            if self.mobile_hires:
                self.mobile_hires.session = self.session
            if self.mobile_atmos:
                self.mobile_atmos.session = self.session

    async def _get(self, url: str, params: dict | None = None, session=None, refresh=False):
        if self.session is None or self.session.closed:
            LOGGER.warning("TidalApi: Session is closed! Membuka ulang sesi aiohttp on-the-fly...")
            self._ensure_http_session()
        
        if session is None:
            if not self.saved:
                raise Exception("TidalApi: Tidak ada sesi (self.saved) yang tersedia untuk panggilan _get.")
            session = self.saved[0]

        params = params.copy() if params else {}
        params.setdefault("countryCode", session.country_code)
        
        if 'limit' not in params:
            params["limit"] = "9999"

        async with self.ratelimit:
            async with self.session.get(
                self.TIDAL_API_BASE + url,
                headers=session.auth_headers(),
                params=params
            ) as resp:

                if not refresh and (resp.status == 401 or resp.status == 403):
                    await session.safe_refresh()
                    return await self._get(url, params, session, True)

                resp_json = None
                try:
                    resp_json = await resp.json(content_type=None)
                except Exception:
                    raw_txt = ""
                    try:
                        raw_txt = await resp.text()
                    except Exception:
                        pass
                    raise Exception(f'TIDAL : Response was not valid JSON. HTTP status {resp.status}. {raw_txt[:300]}')

                if isinstance(resp_json, dict):
                    if resp_json.get('status') == 404 and resp_json.get('subStatus') == 2001:
                        raise Exception('TIDAL : {}. This might be region-locked.'.format(resp_json.get('userMessage')))

                    if 'status' in resp_json and resp_json['status'] != 200:
                        raise Exception('TIDAL : ' + str(resp_json))

                return resp_json

    async def get_track(self, track_id):
        return await self._get(f'tracks/{track_id}')

    async def get_track_contributors(self, track_id):
        """Mengambil daftar kontributor/kredit untuk sebuah lagu (untuk Composer)."""
        return await self._get(f'tracks/{track_id}/contributors')

    async def get_album(self, album_id):
        return await self._get('albums/' + str(album_id))

    async def get_album_tracks(self, album_id):
        return await self._get('albums/' + str(album_id) + '/tracks')

    async def get_video(self, video_id):
        return await self._get(f'videos/{video_id}')

    async def get_video_stream_url(self, video_id, session=None):
        target_session = session or self.tv_session or (self.saved[0] if self.saved else None)
        return await self._get(f'videos/{video_id}/playbackinfo', {
            'playbackmode': 'STREAM',
            'assetpresentation': 'FULL',
            'videoquality': 'HIGH',
            'prefetch': 'false'
        }, target_session)

    async def get_playlist(self, playlist_id):
        return await self._get('playlists/' + str(playlist_id))

    async def get_playlist_tracks(self, playlist_id, total_tracks: int):
        limit = 100
        offset = 0
        all_items = []
        
        if not self.saved:
            raise Exception("TidalApi: Tidak ada sesi (self.saved) yang tersedia.")
        default_session = self.saved[0]

        if total_tracks == 0:
            total_tracks = limit

        while offset < total_tracks:
            page_params = {
                'limit': str(limit),
                'offset': str(offset)
            }
            
            try:
                page_data = await self._get(
                    f'playlists/{playlist_id}/items',
                    params=page_params,
                    session=default_session
                )
                
                if 'items' in page_data and page_data['items']:
                    all_items.extend(page_data['items'])
                    offset += limit
                    if total_tracks == limit and offset == limit: 
                        total_tracks = page_data.get('totalNumberOfItems', total_tracks)
                else:
                    break
            
            except Exception as e:
                LOGGER.error(f"TidalAPI: Gagal mengambil halaman playlist (offset {offset}): {e}")
                raise e

        return {
            'items': all_items,
            'limit': total_tracks,
            'offset': 0,
            'totalNumberOfItems': len(all_items)
        }

    async def get_artist(self, artist_id):
        return await self._get('artists/' + str(artist_id))

    async def get_artist_albums(self, artist_id):
        return await self._get('artists/' + str(artist_id) + '/albums')

    async def get_artist_albums_ep_singles(self, artist_id):
        return await self._get('artists/' + str(artist_id) + '/albums', params={'filter': 'EPSANDSINGLES'})

    async def get_stream_url(self, track_id, quality, session):
        return await self._get('tracks/' + str(track_id) + '/playbackinfopostpaywall/v4', {
            'playbackmode': 'STREAM',
            'assetpresentation': 'FULL',
            'audioquality': quality,
            'prefetch': 'false'
        }, session)

    async def get_tv_login_url(self):
        self._ensure_http_session()

        if not (Config.TIDAL_TV_TOKEN and Config.TIDAL_TV_SECRET):
            return False, "No Token/Secret added"

        self.tv_session = TvSession(
            Config.TIDAL_TV_TOKEN,
            Config.TIDAL_TV_SECRET,
            self.session
        )

        try:
            auth_url = await self.tv_session.get_device()
            return auth_url, None
        except Exception as e:
            logging.error(format_exc())
            return False, e

    async def login_tv(self):
        try:
            await self.tv_session.auth()
            self.saved.append(self.tv_session)
            self.user_id = self.tv_session.user_id
            
            self.sub_type = await self.get_subscription()
            LOGGER.info(f"TIDAL : Loaded account - {self.sub_type}")

            await self.refresh_mobile()
            return self.sub_type, None
        except Exception as e:
            logging.error(format_exc())
            return False, e
        finally:
            if self.session and not self.session.closed:
                await self.session.close()
                LOGGER.debug("TidalApi: Sesi login TV sementara ditutup.")

    async def login_from_saved(self, data):
        self._ensure_http_session()

        self.tv_session = TvSession(
            Config.TIDAL_TV_TOKEN,
            Config.TIDAL_TV_SECRET,
            self.session
        )

        self.tv_session.refresh_token = data['refresh_token']
        self.tv_session.country_code = data['country_code']
        self.tv_session.user_id = data['user_id']
        
        self.user_id = data['user_id']
        self.country_code = data['country_code']

        try:
            await self.tv_session.refresh()
            self.saved.append(self.tv_session)
        except Exception as e:
            logging.error(format_exc())
            self.tv_session = None
            LOGGER.error("TIDAL : Couldn't load TV/Auto - " + str(e))

        await self.refresh_mobile(data)

        if not self.saved:
            await self.close()
            raise Exception("Semua sesi (TV & Mobile) gagal diperbarui. Token kedaluwarsa atau metode login tidak valid.")

        if any([self.tv_session, self.mobile_hires, self.mobile_atmos]):
            self.sub_type = await self.get_subscription()
        else:
            self.sub_type = 'UNKNOWN'

        LOGGER.info(f"TIDAL : Loaded account - {self.sub_type}")

    async def refresh_mobile(self, data=None):
        if not Config.TIDAL_MOBILE:
            return

        if Config.TIDAL_MOBILE_TOKEN:
            self.mobile_hires = await self._init_mobile_session(Config.TIDAL_MOBILE_TOKEN, 'Hires', data)

        if Config.TIDAL_ATMOS_MOBILE_TOKEN:
            self.mobile_atmos = await self._init_mobile_session(Config.TIDAL_ATMOS_MOBILE_TOKEN, 'Atmos', data)

    async def _init_mobile_session(self, token: str, device: str, data: dict = None) -> "MobileSession | None":
        session = MobileSession(token, self.session)
        
        if data:
            session.refresh_token = data['refresh_token']
            session.country_code = data['country_code']
            session.user_id = data['user_id']
        elif self.tv_session:
            session.copy_from(self.tv_session)
            
        try:
            await session.refresh()
            self.saved.append(session)
            return session
        except Exception as e:
            LOGGER.error(f"TIDAL: Couldn't load Mobile {device} session - {e}")
            return None

    async def get_subscription(self) -> str:
        if self.saved:
            usersess = self.saved[0]
            async with self.session.get(
                f'https://api.tidal.com/v1/users/{usersess.user_id}/subscription',
                params={'countryCode': usersess.country_code},
                headers=usersess.auth_headers()
            ) as r:
                json_resp = await r.json(content_type=None)
                if r.status != 200:
                    raise Exception(f"TIDAL : {json_resp.get('userMessage', json_resp)}")
                return json_resp['subscription']['type']
        return 'UNKNOWN'

    async def close(self):
        """Menutup aiohttp.ClientSession internal."""
        if self.session and not self.session.closed:
            await self.session.close()
            LOGGER.debug(f"TidalApi (User {self.user_id}): Sesi aiohttp ditutup.")


class BaseSession:
    AUTH_BASE = "https://auth.tidal.com/v1/"

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.user_id: str | None = None
        self.country_code: str | None = None
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.expires: datetime | None = None
        self._refresh_lock = asyncio.Lock()
        self._last_refresh_ts = 0.0

    def copy_from(self, other: "BaseSession"):
        if other:
            self.country_code = other.country_code
            self.refresh_token = other.refresh_token
            self.user_id = other.user_id

    def auth_headers(self) -> dict:
        raise NotImplementedError

    async def refresh(self):
        raise NotImplementedError

    async def safe_refresh(self):
        """Mencegah banyak worker me-refresh token secara bersamaan (Race Condition)."""
        async with self._refresh_lock:
            now = time.time()
            if now - self._last_refresh_ts < 10.0 and self.access_token:
                return
            await self.refresh()
            self._last_refresh_ts = time.time()


class MobileSession(BaseSession):
    def __init__(self, token: str, session: aiohttp.ClientSession):
        super().__init__(session)
        self.client_id = token

    async def refresh(self):
        if not self.refresh_token:
            raise Exception("TIDAL: Missing refresh token for MobileSession")

        async with self.session.post(
            self.AUTH_BASE + 'oauth2/token', 
            data={
                'refresh_token': self.refresh_token,
                'client_id': self.client_id,
                'grant_type': 'refresh_token'
            }
        ) as r:
            json_resp = await r.json(content_type=None)
            if r.status == 200:
                self.user_id = self.user_id or json_resp.get("user_id")
                self.access_token = json_resp['access_token']
                self.expires = datetime.now() + timedelta(seconds=json_resp['expires_in'])
                self.refresh_token = json_resp.get("refresh_token", self.refresh_token)
                self._last_refresh_ts = time.time()
            else:
                error_msg = json_resp.get('userMessage') or json_resp.get('error_description') or str(json_resp)
                raise Exception(f"TIDAL : {error_msg}")

    def auth_headers(self):
        return {
            'Host': 'api.tidal.com',
            'X-Tidal-Token': self.client_id,
            'Authorization': 'Bearer {}'.format(self.access_token),
            'Connection': 'Keep-Alive',
            'Accept-Encoding': 'gzip',
            'User-Agent': 'TIDAL_ANDROID/1039 okhttp/3.14.9'
        }


class TvSession(BaseSession):
    def __init__(self, token: str, secret: str, session: aiohttp.ClientSession):
        super().__init__(session)
        self.client_id = token
        self.client_secret = secret
        self.temp_data: dict | None = None

    async def get_device(self):
        async with self.session.post(
            self.AUTH_BASE + 'oauth2/device_authorization', 
            data={'client_id': self.client_id, 'scope': 'r_usr w_usr'}
        ) as r:
            if r.status != 200:
                raise Exception("TIDAL : Invalid TV Client ID or Token")

            json_resp = await r.json(content_type=None)
            auth_link = f"https://link.tidal.com/{json_resp['userCode']}"

            self.temp_data = {
                'client_id': self.client_id,
                'device_code': json_resp['deviceCode'],
                'client_secret': self.client_secret,
                'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
                'scope': 'r_usr w_usr'
            }
        
            return auth_link

    async def auth(self):
        status_code = 400
        i = 1
        json_resp = {}
        timeout = datetime.now() + timedelta(minutes=5)
        while status_code == 400 and datetime.now() < timeout:
            async with self.session.post(self.AUTH_BASE + 'oauth2/token', data=self.temp_data) as r:
                status_code = r.status
                try:
                    json_resp = await r.json(content_type=None)
                except Exception:
                    json_resp = {}
            if status_code == 200:
                break
            await asyncio.sleep(min(i, 5))
            i += 1
            
        if status_code == 400 and datetime.now() >= timeout:
            raise Exception("TIDAL: Autentikasi TV timeout setelah 5 menit.")

        if status_code != 200:
            raise Exception(f"TIDAL : Auth error - {json_resp.get('error', json_resp)}")

        self.access_token = json_resp['access_token']
        self.refresh_token = json_resp['refresh_token']
        self.expires = datetime.now() + timedelta(seconds=json_resp['expires_in'])

        async with self.session.get('https://api.tidal.com/v1/sessions', headers=self.auth_headers()) as r:
            assert (r.status == 200)
            session_resp = await r.json(content_type=None)
            self.user_id = session_resp['userId']
            self.country_code = session_resp['countryCode']

        async with self.session.get(
            f'https://api.tidal.com/v1/users/{self.user_id}?countryCode={self.country_code}',
            headers=self.auth_headers()
        ) as r:
            assert (r.status == 200)

    async def refresh(self):
        if not self.refresh_token:
            raise Exception("TIDAL: Missing refresh token for TvSession")

        async with self.session.post(
            self.AUTH_BASE + 'oauth2/token', 
            data={
                'refresh_token': self.refresh_token,
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'grant_type': 'refresh_token'
            }
        ) as r:
            json_resp = await r.json(content_type=None)
            if r.status != 200:
                raise Exception(f"TIDAL: TV refresh failed - {json_resp.get('userMessage', json_resp)}")

            self.user_id = self.user_id or json_resp.get("user_id")
            self.access_token = json_resp['access_token']
            self.expires = datetime.now() + timedelta(seconds=json_resp['expires_in'])
            self.refresh_token = json_resp.get("refresh_token", self.refresh_token)
            self._last_refresh_ts = time.time()

    def auth_headers(self):
        return {
            'X-Tidal-Token': self.client_id,
            'Authorization': 'Bearer {}'.format(self.access_token),
            'Connection': 'Keep-Alive',
            'Accept-Encoding': 'gzip',
            'User-Agent': 'TIDAL_ANDROID/1039 okhttp/3.14.9'
        }
