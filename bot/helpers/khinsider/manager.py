# [GANTI TOTAL ISI FILE: bot/helpers/khinsider/manager.py]

import aiohttp
import asyncio
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from yarl import URL
from ...logger import LOGGER

class KhinsiderManager:
    def __init__(self):
        self.session = None
        self.quality = 'flac'
        self.base_album_url = "https://downloads.khinsider.com/game-soundtracks/album/"
        self.base_referer = "https://downloads.khinsider.com/"
        
        # Header lengkap yang identik dengan khiscrape.py
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/153.0.8010.37 Safari/537.36"
            ),
            "Accept": "text/html;q=1.0,*/*;q=0.9",
            "Accept-Language": "en-US;q=1.0,en;q=0.9",
            "Accept-Encoding": "identity;q=1.0,gzip;q=0.9,deflate;q=0.8,br;q=0.7",
            "Connection": "keep-alive",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
        }

    async def initialize_clients(self):
        connector = aiohttp.TCPConnector(ssl=False)
        self.session = aiohttp.ClientSession(connector=connector, headers=self.headers)
        LOGGER.info("KhinsiderManager: Session initialized.")

    async def shutdown(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def setup_quality(self, user_id, quality):
        self.quality = quality

    def normalize_album_url(self, input_str: str) -> str:
        """Menghapus query/fragment dan memastikan format kanonikal album Khinsider."""
        clean_input = re.split(r"[?#]", input_str)[0]
        pattern = r"(?:/game-soundtracks)?/album/([^/?#]+)"
        match = re.search(pattern, clean_input)
        if match:
            album_id = match.group(1)
        else:
            album_id = clean_input.strip("/")
            if "/" in album_id:
                album_id = album_id.split("/")[-1]
                
        if not album_id:
            return input_str
        return str(URL(self.base_album_url) / album_id)

    async def get_album(self, url):
        album_url = self.normalize_album_url(url)
        
        if self.session is None or self.session.closed:
            await self.initialize_clients()

        # Wajib menyertakan Referer agar tidak dicegat 403 Forbidden
        req_headers = self.headers.copy()
        req_headers["Referer"] = self.base_referer

        async with self.session.get(album_url, headers=req_headers) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to fetch album page: {resp.status}")
            html = await resp.text()

        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Judul Album
        title_elem = soup.select_one("#pageContent h2")
        title = title_elem.get_text(strip=True) if title_elem else "Unknown Album"
        title = re.sub(r"\s+", " ", title)
        title = re.sub(r"MP3 - Download.*", "", title).strip()

        # 2. Tanggal / Tahun Rilis
        date = "N/A"
        page_content = soup.select_one("#pageContent")
        if page_content:
            text_content = page_content.get_text()
            match_year = re.search(r"Year:\s*(\d{4})", text_content)
            if match_year:
                date = match_year.group(1)

        # 3. Ekstraksi Gambar
        images = []
        for img in soup.select("div.albumImage a"):
            href = img.get('href')
            if href:
                full_img_url = href if href.startswith('http') else urljoin(album_url, href)
                if "/thumbs/" not in full_img_url:
                    images.append(full_img_url)
        cover_url = images[0] if images else None

        # 4. Ekstraksi Daftar Track
        tracks = []
        table = soup.find("table", id="songlist")
        disc_numbers = set()
        
        if table:
            headers = []
            header_row = table.find("tr", id="songlist_header")
            if header_row:
                headers = [th.get_text(strip=True).lower() for th in header_row.find_all("th")]
            
            disc_col_idx = -1
            for i, h in enumerate(headers):
                if "cd" in h or "disc" in h:
                    disc_col_idx = i
                    break

            rows = table.find_all("tr")[1:]
            for row in rows:
                if row.get("id") in ["songlist_footer", "songlist_header"]:
                    continue
                
                cells = row.find_all("td")
                if len(cells) < 2: 
                    continue
                
                link = row.find("a", href=True)
                if not link:
                    continue
                
                track_url = urljoin(album_url, link['href'])
                track_name = link.get_text(strip=True)
                
                track_num = None
                for cell in cells:
                    txt = cell.get_text(strip=True).replace('.', '')
                    if txt.isdigit() and len(txt) < 4:
                        if disc_col_idx != -1 and cells.index(cell) == disc_col_idx:
                            continue
                        track_num = txt
                        break
                
                disc_num = 1
                if disc_col_idx != -1 and len(cells) > disc_col_idx:
                    try:
                        d_txt = cells[disc_col_idx].get_text(strip=True)
                        if d_txt.isdigit():
                            disc_num = int(d_txt)
                    except:
                        pass
                
                disc_numbers.add(disc_num)

                tracks.append({
                    'title': track_name,
                    'url': track_url,
                    'track_number': track_num or str(len(tracks) + 1),
                    'disc_number': str(disc_num)
                })

        total_volumes = len(disc_numbers) if disc_numbers else 1

        return {
            'title': title,
            'album_url': album_url,
            'cover': cover_url,
            'images': images,
            'tracks': tracks,
            'date': date,
            'totalvolumes': str(total_volumes),
            'explicit': False,
            'provider': 'Khinsider'
        }

    async def get_track_download_url(self, track_url, preferred_formats=None, album_url=None):
        if not preferred_formats:
            preferred_formats = ['flac', 'mp3']
            if self.quality in preferred_formats:
                preferred_formats.insert(0, preferred_formats.pop(preferred_formats.index(self.quality)))

        if self.session is None or self.session.closed:
            await self.initialize_clients()

        req_headers = self.headers.copy()
        req_headers["Referer"] = album_url or self.base_referer

        async with self.session.get(track_url, headers=req_headers) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to fetch track page: {resp.status}")
            html = await resp.text()
        
        soup = BeautifulSoup(html, 'html.parser')
        
        found_links = {}
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.get_text().strip().lower()
            for fmt in ['flac', 'mp3', 'm4a', 'ogg', 'wav']:
                if f"download as {fmt}" in text or href.lower().endswith(f".{fmt}"):
                    full_link = href if href.startswith('http') else urljoin(track_url, href)
                    found_links[fmt] = full_link
        
        final_url = None
        final_fmt = 'mp3'
        
        for fmt in preferred_formats:
            if fmt in found_links:
                final_url = found_links[fmt]
                final_fmt = fmt
                break
        
        if not final_url and found_links:
            if 'mp3' in found_links:
                final_fmt = 'mp3'
                final_url = found_links['mp3']
            else:
                final_fmt = list(found_links.keys())[0]
                final_url = found_links[final_fmt]

        if not final_url:
            raise Exception("No download link found on track page.")

        return final_url, final_fmt

khinsider_manager = KhinsiderManager()
