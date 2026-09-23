import aiohttp
import asyncio
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from ...logger import LOGGER

class KhinsiderManager:
    def __init__(self):
        self.session = None
        self.quality = 'flac' 
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        }

    async def initialize_clients(self):
        self.session = aiohttp.ClientSession(headers=self.headers)
        LOGGER.info("KhinsiderManager: Session initialized.")

    async def shutdown(self):
        if self.session:
            await self.session.close()

    async def setup_quality(self, user_id, quality):
        self.quality = quality

    async def get_album(self, url):
        async with self.session.get(url) as resp:
            if resp.status != 200:
                raise Exception(f"Failed to fetch album page: {resp.status}")
            html = await resp.text()

        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Metadata Dasar
        title = soup.select_one("#pageContent h2")
        title = title.get_text(strip=True) if title else "Unknown Album"
        
        # 2. Ambil Year & Metadata Teks Lainnya
        date = "N/A"
        # Cari di paragraf info (biasanya ada <p><b>Year:</b> 2012</p>)
        page_content = soup.select_one("#pageContent")
        if page_content:
            text_content = page_content.get_text()
            # Regex untuk mencari tahun (4 digit setelah 'Year:')
            match_year = re.search(r"Year:\s*(\d{4})", text_content)
            if match_year:
                date = match_year.group(1)

        # 3. Ambil Gambar
        images = []
        for img in soup.select("div.albumImage a"):
            href = img.get('href')
            if href:
                full_img_url = href if href.startswith('http') else urljoin(url, href)
                images.append(full_img_url)
        cover_url = images[0] if images else None

        # 4. Parse Tracks & Deteksi Disc
        tracks = []
        table = soup.find("table", id="songlist")
        
        disc_numbers = set()
        
        if table:
            # Cek Header untuk kolom Disc
            headers = []
            header_row = table.find("tr", id="songlist_header")
            if header_row:
                headers = [th.get_text(strip=True).lower() for th in header_row.find_all("th")]
            
            disc_col_idx = -1
            for i, h in enumerate(headers):
                if "disc" in h:
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
                
                track_url = urljoin(url, link['href'])
                track_name = link.get_text(strip=True)
                
                # Ambil Nomor Track
                track_num = None
                # Biasanya kolom setelah disc atau kolom ke-1/ke-2
                # Kita cari cell yang isinya angka dan ada titik (misal 1.)
                for cell in cells:
                    txt = cell.get_text(strip=True).replace('.', '')
                    if txt.isdigit() and len(txt) < 4: # Asumsi nomor track < 1000
                        # Cek apakah ini kolom disc?
                        if disc_col_idx != -1 and cells.index(cell) == disc_col_idx:
                            continue
                        track_num = txt
                        break
                
                # Ambil Nomor Disc (Jika ada kolomnya)
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
            'cover': cover_url,
            'images': images,
            'tracks': tracks,
            'date': date,               # <-- Baru
            'totalvolumes': str(total_volumes), # <-- Baru
            'explicit': False,          # Khinsider mayoritas Game OST (Clean)
            'provider': 'Khinsider'
        }

    async def get_track_download_url(self, track_url, preferred_formats=None):
        if not preferred_formats:
            preferred_formats = ['flac', 'mp3']
            if self.quality in preferred_formats:
                preferred_formats.insert(0, preferred_formats.pop(preferred_formats.index(self.quality)))

        async with self.session.get(track_url) as resp:
            if resp.status != 200:
                raise Exception(f"HTTP {resp.status} saat mengakses halaman track: {track_url}")
            html = await resp.text()
        
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        soup = BeautifulSoup(html, 'html.parser')
        
        found_links = {}
        
        # Prioritas 1: Audio player src (Paling akurat & direct)
        audio_tag = soup.find('audio', id='audio')
        if audio_tag and audio_tag.get('src'):
            src = audio_tag['src']
            fmt_match = src.split('.')[-1].lower()
            found_links[fmt_match] = urljoin(track_url, src)

        # Prioritas 2: Ekstrak dari seluruh link (sebagai fallback)
        for a in soup.find_all('a', href=True):
            href = a['href']
            for fmt in ['flac', 'mp3', 'm4a', 'ogg']:
                if href.lower().endswith(f".{fmt}"):
                    found_links[fmt] = urljoin(track_url, href)
        
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
            raise Exception("Tidak ada link unduhan di halaman track. Struktur web mungkin berubah.")

        return final_url, final_fmt

khinsider_manager = KhinsiderManager()
