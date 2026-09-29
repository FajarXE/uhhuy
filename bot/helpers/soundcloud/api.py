# [GANTI SELURUH FILE: bot/helpers/soundcloud/api.py]

import aiohttp
import asyncio
import aiolimiter
from bot.logger import LOGGER

# --- KONTROL RATE LIMIT (ANTI-BAN SOUNDCLOUD) ---
# Membatasi maksimal 15 request dalam 5 detik
SC_LIMITER = aiolimiter.AsyncLimiter(15, 5)
# ------------------------------------------------

# Ini adalah kelas Error kustom kita, mirip BeatportError
class SoundcloudError(Exception):
    def __init__(self, message):
        self.message = message
        super(SoundcloudError, self).__init__(message)

class SoundcloudAPI:
    """
    Kelas asinkron untuk berinteraksi dengan API internal Soundcloud (api-v2).
    Menggunakan aiohttp agar sesuai dengan arsitektur bot.
    """
    
    def __init__(self, access_token: str):
        """
        Inisialisasi klien dengan access_token (client_id) dari config.
        """
        self.api_base = "https://api-v2.soundcloud.com/"
        self.access_token = access_token
        self.session = None
        
        # Header ini ditiru dari file soundcloud_api.py yang Anda unggah
        self.headers = {
            'Authorization': f'OAuth {self.access_token}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.132 Safari/537.36'
        }

    async def _init_session(self):
        """Membuat sesi aiohttp jika belum ada."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers=self.headers)

    async def close_session(self):
        """Menutup sesi aiohttp."""
        if self.session and not self.session.closed:
            await self.session.close()

    async def _get(self, endpoint: str, params: dict = None):
        """Fungsi pembantu GET yang aman untuk API."""
        await self._init_session()
        if not params:
            params = {}

        try:
            # Menggunakan api_base untuk endpoint internal
            url = f'{self.api_base}{endpoint}'
            
            # --- BUNGKUS REQUEST DENGAN LIMITER DI SINI ---
            async with SC_LIMITER:
                async with self.session.get(url, params=params) as r:
                    if r.status != 200:
                        error_text = await r.text()
                        raise SoundcloudError(f"Soundcloud API Error {r.status} di {endpoint}: {error_text}")
                    
                    # content_type=None untuk menangani mimetype yang terkadang salah
                    return await r.json(content_type=None)
                
        except aiohttp.ClientError as e:
            LOGGER.error(f"Soundcloud request gagal: {e}")
            raise SoundcloudError(f"Gagal menghubungi Soundcloud: {e}")

    # --- Endpoint Publik (diterjemahkan dari soundcloud_api.py) ---

    async def resolve_url(self, url: str):
        """
        Mengambil ID dan tipe media dari URL Soundcloud.
        Contoh: https://soundcloud.com/artist/track-name -> data JSON track
        """
        LOGGER.debug(f"Soundcloud: Resolving URL: {url}")
        return await self._get('resolve', params={'url': url})

    async def get_track(self, track_id: str):
        """Mengambil data satu track berdasarkan ID."""
        return await self._get(f'tracks/{track_id}')

    async def get_track_download(self, track_id: str):
        """
        Mendapatkan URL unduhan 'asli' (jika diizinkan oleh artis).
        Ini BUKAN stream HLS, tapi file download langsung.
        """
        try:
            data = await self._get(f'tracks/{track_id}/download')
            return data.get('redirectUri')
        except SoundcloudError as e:
            LOGGER.warning(f"Soundcloud: Gagal mendapatkan link download asli untuk {track_id}: {e}")
            return None # Gagal (mungkin tidak downloadble)

    async def get_track_stream_link(self, file_url: str, track_authorization: str):
        """
        Mengambil URL stream HLS (m3u8) dari URL 'progresif'
        yang didapat dari metadata track.
        """
        try:
            # Logika dari file Anda: 'file_url' adalah URL lengkap, 
            # kita hanya perlu endpoint-nya.
            endpoint = file_url.split(self.api_base)[1]
        except IndexError:
            raise SoundcloudError(f"Format URL stream tidak dikenal: {file_url}")
            
        params = {'track_authorization': track_authorization}
        data = await self._get(endpoint, params=params)
        return data.get('url') # Ini harusnya URL ke file .m3u8

    async def search(self, query_type: str, query: str, limit: int = 10):
        """Mencari track, album, playlist, atau user."""
        params = {'limit': limit, 'top_results': 'v2', 'q': query}
        return await self._get(f'search/{query_type}', params=params)

    async def get_user_albums_tracks(self, user_id: str):
        """
        Mengambil semua album dan track dari seorang artis secara paralel.
        """
        LOGGER.debug(f"Soundcloud: Mengambil album & track untuk user {user_id}")
        
        # Menjalankan kedua request secara bersamaan
        albums_task = self._get(f'users/{user_id}/albums', params={'limit': 1000})
        tracks_task = self._get(f'users/{user_id}/tracks', params={'limit': 1000})
        
        try:
            albums_result, tracks_result = await asyncio.gather(albums_task, tracks_task)
            
            # Mengubah list menjadi dict berdasarkan ID untuk pencarian cepat
            album_data = {i['id']: i for i in albums_result.get('collection', [])}
            track_data = {i['id']: i for i in tracks_result.get('collection', [])}
            
            return album_data, track_data
        except Exception as e:
            LOGGER.error(f"Soundcloud: Gagal mengambil data artis {user_id}: {e}")
            return {}, {}

    async def get_tracks_from_tracklist(self, track_data: list):
        """
        API Soundcloud (anehnya) tidak menyertakan data lengkap
        untuk semua lagu dalam playlist. Fungsi ini mengambil data
        track yang 'hilang' tersebut.
        """
        
        # 1. Filter lagu yang datanya tidak lengkap
        tracks_to_get_ids = [str(i['id']) for i in track_data if 'streamable' not in i]
        
        if not tracks_to_get_ids:
            LOGGER.debug("Soundcloud: Semua track di playlist sudah lengkap.")
            return {i['id']: i for i in track_data}

        LOGGER.debug(f"Soundcloud: Mengambil {len(tracks_to_get_ids)} track yang hilang dari playlist...")

        # 2. Bagi ID menjadi chunk (potongan) berukuran 50 (dari file contoh Anda)
        chunk_size = 50
        chunks = [
            tracks_to_get_ids[i:i + chunk_size] 
            for i in range(0, len(tracks_to_get_ids), chunk_size)
        ]

        # 3. Buat daftar task untuk dieksekusi secara paralel
        tasks = []
        for chunk in chunks:
            params = {'ids': ','.join(chunk)}
            tasks.append(self._get('tracks', params=params))
        
        # 4. Eksekusi semua task
        new_track_data_list = await asyncio.gather(*tasks)
        
        # 5. Gabungkan hasil (list dari list) dan buat kamus pencarian
        new_track_lookup = {}
        for track_list in new_track_data_list:
            for track in track_list:
                new_track_lookup[track['id']] = track
        
        # 6. Bangun kembali data tracklist akhir
        final_data = {}
        for i in track_data:
            track_id = i['id']
            if 'streamable' in i:
                # Data ini sudah lengkap
                final_data[track_id] = i
            elif track_id in new_track_lookup:
                # Data ini baru saja kita ambil
                final_data[track_id] = new_track_lookup[track_id]
            else:
                # Gagal diambil, mungkin track dihapus
                LOGGER.warning(f"Soundcloud: Track {track_id} tidak ditemukan saat mengambil data playlist.")
        
        return final_data
