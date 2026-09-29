# [GANTI SELURUH FILE: bot/helpers/bandcamp/api.py]

import json
import re
import aiohttp
import aiolimiter
from datetime import datetime
from bs4 import BeautifulSoup

# --- KONTROL RATE LIMIT (ANTI-BAN BANDCAMP) ---
BC_LIMITER = aiolimiter.AsyncLimiter(15, 5)
# ----------------------------------------------

class BandcampAPI:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

    async def get_track_or_album(self, session: aiohttp.ClientSession, url: str):
        try:
            # --- BUNGKUS REQUEST DENGAN LIMITER ---
            async with BC_LIMITER:
                async with session.get(url, headers=self.headers) as resp:
                    if resp.status != 200:
                        return None
                    html = await resp.text()

            soup = BeautifulSoup(html, 'html.parser')
            
            scripts = soup.find_all('script', {'data-tralbum': True})
            json_data = None

            if scripts:
                json_data = json.loads(scripts[0]['data-tralbum'])
            else:
                scripts_text = soup.find_all('script')
                for s in scripts_text:
                    if s.string and 'TralbumData' in s.string:
                        match = re.search(r'TralbumData\s*=\s*({.*?});', s.string, re.DOTALL)
                        if match:
                            json_data = json.loads(match.group(1))
                            break
            
            if not json_data:
                return None

            embed_data = {}
            embed_script = soup.find('script', {'id': 'pagedata'})
            if embed_script and embed_script.has_attr('data-blob'):
                 embed_data = json.loads(embed_script['data-blob'])

            raw_date = json_data.get('album_release_date') or json_data.get('current', {}).get('release_date')
            release_date = "Unknown"
            
            if raw_date:
                try:
                    dt = datetime.strptime(raw_date, "%d %b %Y %H:%M:%S GMT")
                    release_date = dt.strftime("%Y-%m-%d") 
                except:
                    release_date = str(raw_date)

            keywords = json_data.get('keywords')
            genre = None
            
            if keywords and isinstance(keywords, list):
                genre = ", ".join([k.strip().title() for k in keywords])

            label = None
            if 'item_sellers' in json_data and json_data['item_sellers']:
                first_seller = next(iter(json_data['item_sellers'].values()))
                label = first_seller.get('name')
            
            if not label:
                label = json_data.get('artist')

            tracks = json_data.get('trackinfo', [])
            is_explicit_content = False
            for t in tracks:
                if t.get('is_explicit') or t.get('explicit'): 
                    is_explicit_content = True
                    break
            explicit_str = "True" if is_explicit_content else "False"

            result = {
                'raw': json_data,
                'is_album': 'trackinfo' in json_data and len(json_data['trackinfo']) > 1,
                'artist': json_data.get('artist') or embed_data.get('artist') or "Unknown Artist",
                'album_artist': json_data.get('artist'),
                'album_title': json_data.get('current', {}).get('title') or embed_data.get('album_title') or "Unknown Album",
                'art_id': json_data.get('art_id'),
                'tracks': tracks,
                'release_date': release_date,
                'genre': genre, 
                'label': label,
                'explicit': explicit_str
            }
            return result

        except Exception as e:
            print(f"Error parsing Bandcamp: {e}")
            return None
