import re
import aiohttp

class MangaPlusAPI:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        }
        # Endpoint asli yang disadap oleh MangaPlus
        self.api_url = "https://jumpg-webapi.tokyo-cdn.com/api/manga_viewer?chapter_id={}&split=yes&img_quality=super_high"

    def extract_page_number(self, url: str) -> int:
        # Mencari nomor halaman dari string URL (Sama persis seperti Regex di JS)
        m = re.search(r'/manga_page/(?:high|super_high|mid|low|raw)?/(\d+)\.jpg', url, re.IGNORECASE)
        if m: return int(m.group(1))
        
        m = re.search(r'/chapter/\d+/(?:manga_page|page)/(\d+)\.jpg', url, re.IGNORECASE)
        if m: return int(m.group(1))
        
        m = re.search(r'/(?:page|p)/(\d+)\.jpg', url, re.IGNORECASE)
        if m: return int(m.group(1))
        
        m = re.search(r'/0*([1-9]\d{0,2})\.jpg(?:\?|$)', url, re.IGNORECASE)
        if m: return int(m.group(1))
        
        return -1

    def decrypt_image(self, raw_bytes: bytes, hex_key: str) -> bytes:
        if not raw_bytes: return raw_bytes
        
        # Validasi: Apakah sudah berupa gambar JPEG normal (FF D8 FF)?
        if len(raw_bytes) >= 3 and raw_bytes[:3] == b'\xff\xd8\xff':
            return raw_bytes
        
        # Operasi Dekripsi XOR
        if hex_key and len(hex_key) >= 2:
            key_bytes = bytes.fromhex(hex_key)
            key_len = len(key_bytes)
            
            decrypted = bytearray(raw_bytes)
            for i in range(len(decrypted)):
                decrypted[i] ^= key_bytes[i % key_len]
            
            if len(decrypted) >= 3 and decrypted[:3] == b'\xff\xd8\xff':
                return bytes(decrypted)
        
        return raw_bytes

    async def get_chapter_data(self, chapter_id: str) -> dict:
        url = self.api_url.format(chapter_id)
        
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise Exception(f"Gagal menghubungi API MangaPlus (HTTP {resp.status})")
                raw_data = await resp.read()
        
        # Parsing Protobuf Binary ke String Latin1
        latin1_string = raw_data.decode('latin1')
        
        # Regex pencarian URL gambar aman & terenkripsi DRM
        url_pattern = re.compile(r'(https://[a-zA-Z0-9.\-_]+/(?:secure|drm)/[a-zA-Z0-9_\-\.\/\?=&%]+\.jpg[a-zA-Z0-9_\-\.\/\?=&%]*)')
        
        pages = []
        max_page_num = 0
        page_count = 0
        
        for match in url_pattern.finditer(latin1_string):
            img_url = match.group(1)
            
            # Abaikan banner, thumbnail, dll
            if any(x in img_url for x in ['banner', 'thumbnail', 'icon', 'title_avatar']): continue
            if not any(x in img_url for x in ['manga_page', '/chapter/', '/page/']): continue
                
            page_count += 1
            page_num = self.extract_page_number(img_url)
            if page_num == -1: page_num = page_count
            
            if 0 < page_num < 300 and page_num > max_page_num:
                max_page_num = page_num
                
            # Deteksi Key XOR 16-Byte (32 Karakter Hex) dari string tetangganya
            lookahead_area = latin1_string[match.end():match.end()+140]
            hex_match = re.search(r'([a-f0-9]{32})', lookahead_area)
            hex_key = hex_match.group(1) if hex_match else ""
            
            pages.append({
                'url': img_url,
                'page_num': page_num,
                'key': hex_key
            })
            
        return {
            'chapter_id': chapter_id,
            'total_pages': max_page_num or page_count,
            'pages': sorted(pages, key=lambda x: x['page_num'])
        }
