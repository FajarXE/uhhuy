# [BUAT FILE: bot/helpers/audiomack/api.py]
import aiohttp
from bot.logger import LOGGER

class AudiomackAPI:
    # Mengarah ke localhost karena berjalan di container Render yang sama
    def __init__(self, base_url="http://127.0.0.1:8000"):
        self.base_url = base_url
        
    async def get_song(self, url: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/song", params={"url": url}) as resp:
                if resp.status != 200:
                    err = await resp.json()
                    raise Exception(err.get('detail', 'Audiomack API Error (Song)'))
                return (await resp.json())['data']
                
    async def get_album(self, url: str, track: int = None):
        params = {"url": url}
        if track:
            params['track'] = track
            
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/album", params=params, timeout=120) as resp:
                if resp.status != 200:
                    err = await resp.json()
                    raise Exception(err.get('detail', 'Audiomack API Error (Album)'))
                return (await resp.json())['data']
