# [FILE: bot/helpers/amazon/amazon_api.py]

import os
import json
import uuid
import time
import asyncio
import aiohttp
import re
import html
import base64
from urllib.parse import unquote, quote
from bot.logger import LOGGER

class AmazonApi:
    def __init__(self, region="us"):
        self.region = region.lower()
        self.session = aiohttp.ClientSession()
        self.tokens = {}
        self.refresh_lock = asyncio.Lock()
        
        self.base_urls = {
            "mx": "https://music.amazon.com.mx/",
            "br": "https://music.amazon.com.br/",
            "fr": "https://music.amazon.fr/",
            "us": "https://music.amazon.com/",
            "jp": "https://music.amazon.co.jp/",
            "uk": "https://music.amazon.co.uk/",
            "de": "https://music.amazon.de/",
            "au": "https://music.amazon.com.au/",
            "nz": "https://music.amazon.com.au/",
            "ca": "https://music.amazon.ca/",
            "it": "https://music.amazon.it/",
            "es": "https://music.amazon.es/",
            "ar": "https://music.amazon.com.ar/",
            "in": "https://music.amazon.in/",
        }
        
        self.marketplaces = {
            "mx": "ART4WZ8MWBX2Y", "br": "A2Q3Y263D00KWC", "fr": "A13V1IB3VIYZZH",
            "us": "ATVPDKIKX0DER", "jp": "A1VC38T7YXB528", "uk": "A1F83G8C2ARO7P", "de": "A1PA6795UKMFR9",
            "au": "A15PK738MTQHSO", "nz": "A15PK738MTQHSO",
            "ca": "A2EUQ1WTGCTBG2", "it": "APJ6JZADPQ8N9", "es": "A1RKKUPIHCS9HS",
            "ar": "ATVPDKIKX0DER", "in": "A21TJRUUN4KGV"
        }
        
        api_locations = {
            "NA": ["br", "mx", "us", "ca", "ar"], 
            "EU": ["fr", "de", "uk", "it", "es", "in"], 
            "FE": ["jp", "au", "nz"]
        }
        api_urls = {"NA": "na.tvmesk.skill.music.a2z.com", "EU": "eu.tvmesk.skill.music.a2z.com", "FE": "fe.tvmesk.skill.music.a2z.com"}
        
        self.base_url = self.base_urls.get(self.region, self.base_urls["us"])
        self.api_location = next((loc for loc, regs in api_locations.items() if self.region in regs), "NA")
        self.api_url = api_urls.get(self.api_location)

        self.default_headers = {
            "origin": "https://music.amazon.com",
            "referer": "https://music.amazon.com/",
            "user-agent": "Harley/3.12.11.183 A1I3OANZGDNGEE/24.10.1",
            "x-amzn-device-type-id": "A1KAXIG6VXSG8Y",
            "x-amzn-hardware-device-type-id": "A1KAXIG6VXSG8Y",
            "x-amzn-device-family": "AndroidTV",
            "x-amzn-device-manufacturer": "NVIDIA",
            "x-amzn-device-model": "A1KAXIG6VXSG8Y",
            "x-amzn-device-language": "en_US",
            "x-amzn-device-height": "3840",
            "x-amzn-device-width": "2160",
            "x-amzn-os-version": "11",
            "x-amzn-application-version": "3.12.11.183",
            "x-amzn-device-time-zone": "America/Detroit",
            "x-amzn-user-agent": "Dalvik/2.1.0 (Linux; U; Android 9; Smart TV Build/PPR1.180610.011)",
        }
        self.session.headers.update(self.default_headers)

    def _extract_jwt_data(self, token_str):
        if not token_str or token_str.count(".") < 2: return {}
        try:
            payload = token_str.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            decoded = base64.urlsafe_b64decode(payload.encode()).decode("latin-1", errors="ignore")
            
            res = {}
            c_id = re.search(r'"customerId"\s*:\s*"([^"]+)"', decoded)
            if c_id: res["customerId"] = c_id.group(1)
            d_id = re.search(r'"deviceId"\s*:\s*"([^"]+)"', decoded)
            if d_id: res["device_id"] = d_id.group(1)
            dt_id = re.search(r'"deviceType(?:Id)?"\s*:\s*"([^"]+)"', decoded)
            if dt_id: res["deviceTypeId"] = dt_id.group(1)
            
            cl_id = re.search(r'"aud"\s*:\s*"([^"]+)"', decoded) or re.search(r'"appId"\s*:\s*"([^"]+)"', decoded)
            if cl_id: res["client_id"] = cl_id.group(1)
            return res
        except: return {}

    def load_tokens(self, saved_tokens):
        self.tokens.update(saved_tokens)
        access_token = self.tokens.get("x-amz-access-token", "")
        extracted = self._extract_jwt_data(access_token)
        for k, v in extracted.items():
            if not self.tokens.get(k): self.tokens[k] = v

    async def get_tv_device_code(self):
        self.tokens["device_id"] = os.urandom(8).hex()
        headers = {
            "x-amzn-request-id": str(uuid.uuid4()),
            "x-amzn-timestamp": str(int(time.time() * 1000)),
            "x-amzn-device-id": self.tokens["device_id"],
        }
        async with self.session.post(f"https://{self.api_url}/api/showHome", json={"userHash": ""}, headers=headers) as resp:
            if resp.status != 200: raise Exception(f"HTTP {resp.status}: {await resp.text()}")
            codepair_json = await resp.json()
            code_pair = codepair_json["methods"][0]["template"]
            public_code = code_pair.get("code", "")
            poll_url = code_pair["onPollingIntervalElapsed"][0]["url"]
            register_code = unquote(poll_url.rsplit("code=", 1)[-1])
            activation_url = self.base_url.replace("music.", "") + "code"
            return public_code, register_code, activation_url

    async def poll_tv_auth(self, register_code):
        headers = {
            "x-amzn-request-id": str(uuid.uuid4()),
            "x-amzn-timestamp": str(int(time.time() * 1000)),
            "x-amzn-device-id": self.tokens["device_id"],
        }
        payload = json.dumps({"code": register_code}, separators=(",", ":"))
        async with self.session.post(f"https://{self.api_url}/api/showHome", headers=headers, data=payload) as resp:
            if resp.status != 200: return False
            register_json = await resp.json()
            
            service_token, video_player_token = None, None
            for item in register_json.get("methods", []):
                if item.get("interface") == "PlaybackAuthenticationInterface.v1_0.SetAuthenticationMethod":
                    service_token = item.get("authentication")
                if item.get("interface") == "VideoPlayerAuthenticationInterface.v1_0.SetVideoPlayerTokenMethod":
                    video_player_token = item.get("header")
                    
            if service_token:
                token_data = json.loads(service_token)
                self.tokens["service_token"] = service_token
                self.tokens["x-amz-access-token"] = token_data.get("accessToken")
                self.tokens["refresh_token"] = token_data.get("refreshToken") 
                if "clientId" in token_data: self.tokens["client_id"] = token_data["clientId"]
                if self.tokens["x-amz-access-token"]: self.tokens.update(self._extract_jwt_data(self.tokens["x-amz-access-token"]))
                
                if video_player_token and not self.tokens.get("customerId"):
                    try:
                        v_tok = json.loads(video_player_token).get("token", video_player_token)
                    except: v_tok = video_player_token
                    self.tokens.update(self._extract_jwt_data(v_tok))
                
                return self.tokens
        return False

    async def refresh_access_token(self):
        if not hasattr(self, 'refresh_lock'): self.refresh_lock = asyncio.Lock()
        old_access_token = self.tokens.get("x-amz-access-token")
        
        async with self.refresh_lock:
            if self.tokens.get("x-amz-access-token") != old_access_token:
                return True
                
            service_token = self.tokens.get("service_token")
            device_id = self.tokens.get("device_id")
            
            if not service_token or not device_id:
                return False

            url = f"https://{self.api_url}/api/transferPlayback"
            payload = {"showNowPlaying": "false", "newMediaRequired": "true", "userHash": ""}
            headers = {
                "x-amzn-request-id": str(uuid.uuid4()),
                "x-amzn-timestamp": str(int(time.time() * 1000)),
                "x-amzn-authentication": service_token,
                "x-amzn-device-id": device_id,
            }
            
            try:
                async with self.session.post(url, json=payload, headers=headers) as resp:
                    if resp.status == 200:
                        transfer_json = await resp.json()
                        transferred_service_token = None
                        
                        for item in transfer_json.get("methods", []):
                            if item.get("interface") == "PlaybackAuthenticationInterface.v1_0.SetAuthenticationMethod" and item.get("authentication"):
                                transferred_service_token = item["authentication"]
                                break
                                
                        if not transferred_service_token: raise Exception("Tidak ada token.")

                        transfer_token_data = json.loads(transferred_service_token)
                        self.tokens["service_token"] = transferred_service_token
                        self.tokens["x-amz-access-token"] = transfer_token_data.get("accessToken")
                        if transfer_token_data.get("marketplaceId"): self.tokens["marketplaceId"] = transfer_token_data["marketplaceId"]
                        
                        try:
                            from bot.helpers.amazon.manager import amazon_manager
                            if hasattr(amazon_manager, 'clients'):
                                for c in amazon_manager.clients:
                                    if c.tokens.get('customerId') == self.tokens.get('customerId'): c.tokens.update(self.tokens)
                            if hasattr(amazon_manager, 'user_clients'):
                                for uid, c in amazon_manager.user_clients.items():
                                    if c.tokens.get('customerId') == self.tokens.get('customerId'): c.tokens.update(self.tokens)
                            for save_func in ['save_data', 'save_config', 'save_database', 'save']:
                                if hasattr(amazon_manager, save_func):
                                    getattr(amazon_manager, save_func)()
                                    break
                        except: pass
                        return True
                    else:
                        err_txt = await resp.text()
                        if resp.status in [400, 401, 403]: raise Exception("AUTH_EXPIRED")
                        return False
            except Exception as e:
                if str(e) == "AUTH_EXPIRED": raise e
                return False

    async def fetch_master_cover(self, album_title, album_asin):
        try:
            site_region = self.region if self.region != 'uk' else 'gb'
            url = f"https://music.amazon.com/{site_region}/api/textsearch/search/v1_1/"
            
            payload = {
                "customerIdentity": {
                    "customerId": self.tokens.get('customerId'),
                    "deviceId": self.tokens.get('device_id'),
                    "deviceType": self.tokens.get('deviceTypeId') or "A1KAXIG6VXSG8Y",
                    "sessionId": "123-1234567-5555555",
                },
                "features": {
                    "spellCorrection": {"allowCorrection": True},
                    "upsell": {"allowUpsellForCatalogContent": False}
                },
                "musicTerritory": self.region.upper(),
                "query": album_title,
                "locale": "en_US",
                "resultSpecs": [{
                    "contentRestrictions": {
                        "allowedParentalControls": {"hasExplicitLanguage": True},
                        "contentTier": "UNLIMITED"
                    },
                    "documentSpecs": [{
                        "fields": ["artOriginal"],
                        "type": "catalog_album"
                    }],
                    "label": "catalog_album",
                    "maxResults": 10
                }]
            }
            headers = {
                "X-Amz-Target": "com.amazon.tenzing.textsearch.v1_1.TenzingTextSearchServiceExternalV1_1.search",
                "Authorization": f"Bearer {self.tokens.get('x-amz-access-token')}",
                "Content-Encoding": "amz-1.0",
            }
            async with self.session.post(url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results", [])
                    if results:
                        for hit in results[0].get("hits", []):
                            doc = hit.get("document", {})
                            if doc.get("asin") == album_asin:
                                if doc.get("artOriginal") and doc["artOriginal"].get("URL"):
                                    return doc["artOriginal"]["URL"]
        except Exception as e:
            LOGGER.debug(f"Amazon Search API Cover fallback failed: {e}")
        return None

    # --- PENGAMBIL COVER ITUNES (STUDIO MASTER) ---
    async def fetch_itunes_cover(self, artist, album):
        try:
            # Bersihkan teks agar pencarian iTunes lebih akurat
            clean_artist = re.sub(r'\(.*?\)', '', artist).strip()
            clean_album = re.sub(r'\(.*?\)', '', album).strip()
            term = quote(f"{clean_artist} {clean_album}")
            
            url = f"https://itunes.apple.com/search?term={term}&entity=album&limit=1"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('resultCount', 0) > 0:
                            artwork = data['results'][0].get('artworkUrl100')
                            if artwork:
                                # Trik 10000x10000bb memaksa CDN Apple memberikan resolusi
                                # murni yang paling maksimal (tanpa upscale!)
                                return artwork.replace('100x100bb.jpg', '10000x10000bb.jpg')
        except Exception as e:
            from bot.logger import LOGGER
            LOGGER.debug(f"iTunes cover fallback failed: {e}")
        return None
    # -------------------------------------------------------------

    async def get_playback_info(self, asin: str, target_quality: str = "UHD"):
        for attempt in range(2):
            device_id = self.tokens.get('device_id')
            access_token = self.tokens.get('x-amz-access-token')
            customer_id = self.tokens.get('customerId')
            device_type_id = self.tokens.get('deviceTypeId') or "A1KAXIG6VXSG8Y"
            
            if not customer_id: raise Exception("Missing 'customerId' di memori. Login ulang diperlukan.")
            marketplace_id = self.marketplaces.get(self.region, "ATVPDKIKX0DER")
            music_territory = self.region.upper()
            
            lookup_url = f"{self.base_url}{self.api_location}/api/muse/legacy/lookup"
            lookup_payload = {
                "customerId": customer_id,
                "asins": [asin],
                "features": ["popularity", "expandTracklist", "trackLibraryAvailability", "collectionLibraryAvailability", "albumArtist", "fullAlbumDetails"],
                "requestedContent": "MUSIC_SUBSCRIPTION",
                "musicTerritory": music_territory, 
                "deviceId": device_id,
                "deviceType": device_type_id
            }
            lookup_headers = {
                "x-amzn-requestid": str(uuid.uuid4()),
                "X-Amz-Target": "com.amazon.musicensembleservice.MusicEnsembleService.lookup",
                "x-amz-access-token": access_token,
                "x-amzn-device-type-id": device_type_id,
                "x-amzn-hardware-device-type-id": device_type_id
            }
            
            title, artist, album, image = asin, "Unknown Artist", "Unknown Album", ""
            albumartist, tracknumber, discnumber, tracktotal = "Unknown Artist", 1, 1, 1
            isrc, composer, genre, copyright, release_date, label = "", "", "", "", "", ""
            
            async with self.session.post(lookup_url, json=lookup_payload, headers=lookup_headers) as resp:
                resp_text = await resp.text()
                if (resp.status == 403 or (resp.status == 400 and "INVALID_TOKEN" in resp_text)) and attempt == 0:
                    try:
                        if await self.refresh_access_token(): continue
                    except Exception as e:
                        if str(e) == "AUTH_EXPIRED": raise Exception("Sesi kedaluwarsa permanen. Silakan login kembali.")
                    raise Exception("Gagal memperbarui token metadata.")
                
                if resp.status == 200:
                    lookup_data = json.loads(resp_text)
                    
                    track_data_obj = None
                    if 'trackList' in lookup_data and lookup_data['trackList']:
                        track_data_obj = lookup_data['trackList'][0]
                    elif 'albumList' in lookup_data and lookup_data['albumList']:
                        album_tracks = lookup_data['albumList'][0].get('tracks', [])
                        if album_tracks: track_data_obj = album_tracks[0]

                    album_main_obj = {}
                    if 'albumList' in lookup_data and lookup_data['albumList']:
                        album_main_obj = lookup_data['albumList'][0]
                    elif track_data_obj and track_data_obj.get('album', {}).get('asin'):
                        alb_payload = lookup_payload.copy()
                        alb_payload['asins'] = [track_data_obj['album']['asin']]
                        try:
                            async with self.session.post(lookup_url, json=alb_payload, headers=lookup_headers) as alb_resp:
                                if alb_resp.status == 200:
                                    alb_data = await alb_resp.json()
                                    if 'albumList' in alb_data and alb_data['albumList']:
                                        album_main_obj = alb_data['albumList'][0]
                        except: pass

                    if track_data_obj:
                        title = track_data_obj.get('title', asin)
                        artist = track_data_obj.get('artist', {}).get('name', 'Unknown Artist')
                        album_obj = track_data_obj.get('album', {}) if isinstance(track_data_obj.get('album'), dict) else {}
                        
                        album = album_main_obj.get('title') or album_obj.get('title', 'Unknown Album')
                        image = album_main_obj.get('image') or album_obj.get('image', '')
                        albumartist = album_main_obj.get('primaryArtistName') or album_obj.get('primaryArtistName', artist)
                        tracktotal = album_main_obj.get('trackCount') or album_obj.get('trackCount', 1)
                        
                        prod_details = album_main_obj.get('productDetails', {})
                        genre = prod_details.get('primaryGenreName', '')
                        copyright = prod_details.get('copyright', '')
                        label = album_main_obj.get('label') or album_obj.get('label', '')
                        
                        date_ms = album_main_obj.get('originalReleaseDate') or album_obj.get('originalReleaseDate') or album_main_obj.get('merchantReleaseDate') or album_obj.get('merchantReleaseDate')
                        if date_ms:
                            from datetime import datetime, timedelta
                            release_date = (datetime(1970, 1, 1) + timedelta(seconds=date_ms / 1000)).strftime('%Y-%m-%d')

                        tracknumber = track_data_obj.get('trackNum', 1)
                        discnumber = track_data_obj.get('discNum', 1)
                        isrc = track_data_obj.get('isrc', '')
                        
                        # --- FIX COMPOSER NULL EXCEPTION ---
                        writers = track_data_obj.get('songWriters')
                        composer = ', '.join(writers) if isinstance(writers, list) else ''

                        # --- STRATEGI PENEMBUSAN COVER MASTER (ITUNES FIRST) ---
                        album_asin = album_main_obj.get('asin') or album_obj.get('asin')
                        master_cover = None
                        
                        # 1. PRIORITAS UTAMA: RAMPAS DARI ITUNES API!
                        master_cover = await self.fetch_itunes_cover(albumartist or artist, album)
                        
                        # 2. Jika gagal di iTunes, baru Fallback ke Tenzing Amazon Search
                        if not master_cover and album_asin and album:
                            master_cover = await self.fetch_master_cover(album, album_asin)
                            
                        if master_cover:
                            image = master_cover
                            
                        if image:
                            # 3. Proses Akhir Resolusi
                            if 'mzstatic.com' in image or 'itunes.apple.com' in image:
                                pass # Biarkan URL iTunes 10000x10000bb bekerja (Otomatis Max Res)
                            else:
                                # Jika terpaksa pakai Amazon, ambil file mentah (RAW)
                                image = re.sub(r'\._[^.]+\.(jpg|jpeg|png)$', r'.\1', image, flags=re.IGNORECASE)
            
            # --- 2. PENCARIAN FILE AUDIO (MPD) ---
            dmls_url = f"{self.base_url}{self.api_location}/api/dmls/"
            dmls_payload = {
                "customerId": customer_id,
                "deviceToken": {"deviceTypeId": device_type_id, "deviceId": device_id},
                "appInfo": {"musicAgent": f"Harley/3.12.11.183 Harley/24.10.1 ({uuid.uuid4()} {asin})"},
                "contentIdList": [{"identifier": asin, "identifierType": "ASIN"}],
                "musicDashVersionList": ["SIREN_KATANA"],
                "contentProtectionList": ["TRACK_PSSH"],
                "customerInfo": {"marketplaceId": marketplace_id, "territoryId": music_territory, "customerId": customer_id},
                "tryAsinSubstitution": True
            }
            dmls_headers = {
                "X-Amz-RequestId": str(uuid.uuid4()),
                "X-Amz-Target": "com.amazon.digitalmusiclocator.DigitalMusicLocatorServiceExternal.getDashManifestsV2",
                "x-amz-access-token": access_token,
                "Content-Encoding": "amz-1.0",
                "x-amzn-device-type-id": device_type_id,
                "x-amzn-hardware-device-type-id": device_type_id
            }
            
            async with self.session.post(dmls_url, json=dmls_payload, headers=dmls_headers) as resp:
                resp_text = await resp.text()
                if (resp.status == 403 or (resp.status == 400 and "INVALID_TOKEN" in resp_text)) and attempt == 0:
                    try:
                        if await self.refresh_access_token(): continue
                    except Exception as e:
                        if str(e) == "AUTH_EXPIRED": raise Exception("Sesi kedaluwarsa permanen.")
                    raise Exception("Gagal refresh saat mengambil MPD.")
                    
                if resp.status != 200: raise Exception(f"Gagal MPD ({resp.status}): {resp_text}")
                
                dmls_data = json.loads(resp_text)
                if not dmls_data.get("contentResponseList"): raise Exception("Amazon menolak file.")
                item_resp = dmls_data["contentResponseList"][0]
                if item_resp.get("error"): raise Exception(f"Ditolak Amazon: {item_resp.get('error')}")
                mpd_text = item_resp.get("manifest", "")

            # --- 3. FILTERING KUALITAS & FISIK ---
            target_rank = {"SD": 2, "HD": 3, "UHD": 4}.get(target_quality.upper(), 4)
            valid_reps = []
            
            adp_sets = re.findall(r"<AdaptationSet\b([\s\S]*?)</AdaptationSet>", mpd_text, re.IGNORECASE)
            for adp in adp_sets:
                kid_match = re.search(r'default_KID=["\']([^"\']+)["\']', adp, re.IGNORECASE)
                adp_kid = kid_match.group(1).strip() if kid_match else ""
                
                for rep in re.findall(r"<Representation\b([\s\S]*?)</Representation>", adp, re.IGNORECASE):
                    bw_match = re.search(r'bandwidth=["\'](\d+)["\']', rep, re.IGNORECASE)
                    url_match = re.search(r"<BaseURL(?:[^>]*)>([\s\S]*?)</BaseURL>", rep, re.IGNORECASE)
                    codec_match = re.search(r'codecs=["\']([^"\']+)["\']', rep, re.IGNORECASE)
                    sr_match = re.search(r'audioSamplingRate=["\'](\d+)["\']', rep, re.IGNORECASE)
                    
                    if url_match:
                        bw = int(bw_match.group(1)) if bw_match else 0
                        rep_url = html.unescape(url_match.group(1).strip())
                        rep_codec = html.unescape(codec_match.group(1).strip()).lower() if codec_match else "flac"
                        sr = int(sr_match.group(1)) if sr_match else 44100
                        
                        if "mp4a" in rep_codec or "opus" in rep_codec: rep_rank = 2 
                        elif "flac" in rep_codec: rep_rank = 4 if (sr > 48000 or bw > 1200000) else 3
                        else: rep_rank = 3
                            
                        valid_reps.append({"url": rep_url, "bw": bw, "codec": rep_codec, "kid": adp_kid, "rank": rep_rank})
            
            best_bw, best_url, best_codec, best_kid = 0, "", "flac", ""
            filtered_reps = [r for r in valid_reps if r["rank"] <= target_rank]
            if not filtered_reps: filtered_reps = valid_reps
                
            if filtered_reps:
                best_rep = max(filtered_reps, key=lambda x: x["bw"])
                best_url, best_kid, best_codec = best_rep["url"], best_rep["kid"], best_rep["codec"]
            else:
                url_match = re.search(r"<BaseURL(?:[^>]*)>([\s\S]*?)</BaseURL>", mpd_text, re.IGNORECASE)
                if url_match: best_url = html.unescape(url_match.group(1).strip())
                kid_match = re.search(r'default_KID=["\']([^"\']+)["\']', mpd_text, re.IGNORECASE)
                if kid_match: best_kid = kid_match.group(1).strip()
                    
            return {
                'title': title, 'artist': artist, 'album': album, 'albumartist': albumartist,
                'tracknumber': tracknumber, 'discnumber': discnumber, 'totaltracks': tracktotal,
                'isrc': isrc, 'composer': composer, 'genre': genre, 'copyright': copyright,
                'publisher': label, 'release_date': release_date, 'cover': image, 
                'url': best_url, 'kid': best_kid, 'codec': best_codec
            }

    async def get_license(self, challenge_b64, track_asin):
        for attempt in range(2):
            url = f"{self.base_url}{self.api_location}/api/dmls/getLicenseForPlaybackV2"
            device_type_id = self.tokens.get('deviceTypeId') or "A1KAXIG6VXSG8Y"
            
            payload = {
                "deviceToken": {"deviceTypeId": device_type_id, "deviceId": self.tokens.get('device_id')},
                "appInfo": {"musicAgent": f"Harley/3.12.11.183 Harley/24.10.1 ({uuid.uuid4()} {track_asin})"},
                "DrmType": "PLAYREADY", "licenseChallenge": challenge_b64
            }
            headers = {
                "x-amzn-requestid": str(uuid.uuid4()),
                "X-Amz-Target": "com.amazon.digitalmusiclocator.DigitalMusicLocatorServiceExternal.getLicenseForPlaybackV2",
                "x-amz-access-token": self.tokens.get('x-amz-access-token'),
                "Content-Encoding": "amz-1.0",
                "x-amzn-device-type-id": device_type_id,
                "x-amzn-hardware-device-type-id": device_type_id
            }
            
            async with self.session.post(url, json=payload, headers=headers) as resp:
                resp_text = await resp.text()
                if (resp.status == 403 or (resp.status == 400 and "INVALID_TOKEN" in resp_text)) and attempt == 0:
                    try:
                        if await self.refresh_access_token(): continue
                    except: pass
                    raise Exception("Gagal meminta lisensi DRM.")
                    
                if resp.status != 200: raise Exception(f"License API failed: {resp.status}")
                data = json.loads(resp_text)
                if "license" not in data: raise Exception("Lisensi ditolak.")
                return data["license"]

    async def close(self):
        if not self.session.closed: await self.session.close()
