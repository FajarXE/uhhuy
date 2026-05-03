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
from urllib.parse import unquote
from bot.logger import LOGGER

class AmazonApi:
    def __init__(self, region="us"):
        self.region = region.lower()
        self.session = aiohttp.ClientSession()
        self.tokens = {}
        
        self.base_urls = {
            "mx": "https://music.amazon.com.mx/",
            "br": "https://music.amazon.com.br/",
            "fr": "https://music.amazon.fr/",
            "us": "https://music.amazon.com/",
            "jp": "https://music.amazon.co.jp/",
            "uk": "https://music.amazon.co.uk/",
            "de": "https://music.amazon.de/",
        }
        
        # --- FIX: HARDCODE MARKETPLACE ID AGAR TIDAK KONFLIK ---
        self.marketplaces = {
            "mx": "ART4WZ8MWBX2Y",
            "br": "A2Q3Y263D00KWC",
            "fr": "A13V1IB3VIYZZH",
            "us": "ATVPDKIKX0DER",
            "jp": "A1VC38T7YXB528",
            "uk": "A1F83G8C2ARO7P",
            "de": "A1PA6795UKMFR9"
        }
        
        api_locations = {"NA": ["br", "mx", "us"], "EU": ["fr", "de", "uk"], "FE": ["jp"]}
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

    async def get_tv_device_code(self):
        self.tokens["device_id"] = os.urandom(8).hex()
        headers = {
            "x-amzn-request-id": str(uuid.uuid4()),
            "x-amzn-timestamp": str(int(time.time() * 1000)),
            "x-amzn-device-id": self.tokens["device_id"],
        }
        async with self.session.post(f"https://{self.api_url}/api/showHome", json={"userHash": ""}, headers=headers) as resp:
            if resp.status != 200:
                raise Exception(f"HTTP {resp.status}: {await resp.text()}")
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
            if resp.status != 200:
                return False
            register_json = await resp.json()
            
            service_token = None
            video_player_token = None
            
            for item in register_json.get("methods", []):
                if item.get("interface") == "PlaybackAuthenticationInterface.v1_0.SetAuthenticationMethod" and item.get("authentication"):
                    service_token = item["authentication"]
                if item.get("interface") == "VideoPlayerAuthenticationInterface.v1_0.SetVideoPlayerTokenMethod" and item.get("header"):
                    video_player_token = item["header"]
                    
            if service_token:
                token_data = json.loads(service_token)
                self.tokens["service_token"] = service_token
                self.tokens["x-amz-access-token"] = token_data["accessToken"]
                self.tokens["deviceTypeId"] = "A1KAXIG6VXSG8Y"
                
                if video_player_token:
                    try:
                        v_obj = json.loads(video_player_token)
                        v_tok = v_obj.get("token", video_player_token)
                    except:
                        v_tok = video_player_token
                        
                    if v_tok and v_tok.count(".") >= 2:
                        try:
                            jwt_payload = v_tok.split(".")[1]
                            jwt_payload += "=" * (-len(jwt_payload) % 4)
                            decoded = base64.urlsafe_b64decode(jwt_payload.encode()).decode("latin-1", errors="ignore")
                            c_id = re.search(r'"customerId"\s*:\s*"([^"]+)"', decoded)
                            d_id = re.search(r'"deviceId"\s*:\s*"([^"]+)"', decoded)
                            if c_id: self.tokens["customerId"] = c_id.group(1)
                            if d_id: self.tokens["device_id"] = d_id.group(1)
                        except Exception as e:
                            LOGGER.error(f"Gagal parsing JWT VideoPlayer: {e}")
                
                LOGGER.info("Amazon API: Sesi TV berhasil didapatkan!")
                return self.tokens
        return False

    async def get_playback_info(self, asin: str):
        device_id = self.tokens.get('device_id')
        access_token = self.tokens.get('x-amz-access-token')
        customer_id = self.tokens.get('customerId')
        device_type_id = self.tokens.get('deviceTypeId', "A1KAXIG6VXSG8Y")
        
        marketplace_id = self.marketplaces.get(self.region, "ATVPDKIKX0DER")
        music_territory = self.region.upper()
        
        # --- FIX: HAPUS self.api_location DARI URL AGAR TIDAK ERROR 404/400 ---
        lookup_url = f"{self.base_url}api/muse/legacy/lookup"
        
        lookup_payload = {
            "asins": [asin],
            "features": ["popularity", "expandTracklist", "trackLibraryAvailability", "collectionLibraryAvailability"],
            "requestedContent": "MUSIC_SUBSCRIPTION",
            "musicTerritory": music_territory, 
            "deviceId": device_id,
            "deviceType": device_type_id
        }
        lookup_headers = {
            "x-amzn-requestid": str(uuid.uuid4()),
            "X-Amz-Target": "com.amazon.musicensembleservice.MusicEnsembleService.lookup",
            "x-amz-access-token": access_token
        }
        
        title, artist, album = asin, "Unknown Artist", "Unknown Album"
        async with self.session.post(lookup_url, json=lookup_payload, headers=lookup_headers) as resp:
            if resp.status == 200:
                lookup_data = await resp.json()
                if 'trackList' in lookup_data and lookup_data['trackList']:
                    track = lookup_data['trackList'][0]
                    title = track.get('title', asin)
                    artist = track.get('artist', {}).get('name', 'Unknown Artist')
                    album = track.get('album', {}).get('title', 'Unknown Album')
        
        # --- FIX: HAPUS self.api_location DARI URL ---
        dmls_url = f"{self.base_url}api/dmls/"
        
        customer_info = {
            "marketplaceId": marketplace_id,
            "territoryId": music_territory
        }
        if customer_id:
            customer_info["customerId"] = customer_id
            
        dmls_payload = {
            "deviceToken": {"deviceTypeId": device_type_id, "deviceId": device_id},
            "appInfo": {"musicAgent": f"Harley/3.12.11.183 Harley/24.10.1 ({uuid.uuid4()} {asin})"},
            "contentIdList": [{"identifier": asin, "identifierType": "ASIN"}],
            "musicDashVersionList": ["SIREN_KATANA"],
            "contentProtectionList": ["TRACK_PSSH"],
            "customerInfo": customer_info,
            "try3dAsinSubstitution": True,
            "tryAsinSubstitution": True
        }
        dmls_headers = {
            "X-Amz-RequestId": str(uuid.uuid4()),
            "X-Amz-Target": "com.amazon.digitalmusiclocator.DigitalMusicLocatorServiceExternal.getDashManifestsV2",
            "x-amz-access-token": access_token,
            "Content-Encoding": "amz-1.0"
        }
        
        async with self.session.post(dmls_url, json=dmls_payload, headers=dmls_headers) as resp:
            if resp.status != 200:
                raise Exception(f"Gagal memuat MPD Amazon ({resp.status}): {await resp.text()}")
            
            dmls_data = await resp.json()
            
            if not dmls_data.get("contentResponseList"):
                raise Exception(f"Amazon menolak memberikan file. Respons: {json.dumps(dmls_data)}")
                
            item_resp = dmls_data["contentResponseList"][0]
            if item_resp.get("status") != "SUCCESS" or "error" in item_resp:
                err_code = item_resp.get("error", {}).get("code", "UNKNOWN")
                err_msg = item_resp.get("error", {}).get("message", "Akses ditolak.")
                raise Exception(f"Ditolak Amazon: [{err_code}] {err_msg}")
                
            mpd_text = item_resp.get("manifest", "")
            
        best_bw = 0
        best_url = ""
        kid_match = re.search(r'default_KID=["\']([^"\']+)["\']', mpd_text, re.IGNORECASE)
        kid = kid_match.group(1).strip() if kid_match else ""
        
        reps = re.findall(r"<Representation\b([\s\S]*?)</Representation>", mpd_text, re.IGNORECASE)
        for rep in reps:
            bw_match = re.search(r'bandwidth=["\'](\d+)["\']', rep, re.IGNORECASE)
            url_match = re.search(r"<BaseURL(?:[^>]*)>([\s\S]*?)</BaseURL>", rep, re.IGNORECASE)
            
            if url_match:
                bw = int(bw_match.group(1)) if bw_match else 0
                if bw >= best_bw:
                    best_bw = bw
                    best_url = html.unescape(url_match.group(1).strip())
                    
        if not best_url:
            url_match = re.search(r"<BaseURL(?:[^>]*)>([\s\S]*?)</BaseURL>", mpd_text, re.IGNORECASE)
            if url_match:
                best_url = html.unescape(url_match.group(1).strip())
                
        if not best_url:
            LOGGER.error(f"Amazon MPD Parse Failed! Isi MPD: {mpd_text[:1000]}")
            
        return {'title': title, 'artist': artist, 'album': album, 'url': best_url, 'kid': kid}

    async def get_license(self, challenge_b64, track_asin):
        # --- FIX: HAPUS self.api_location DARI URL ---
        url = f"{self.base_url}api/dmls/getLicenseForPlaybackV2"
        
        payload = {
            "deviceToken": {
                "deviceTypeId": self.tokens.get('deviceTypeId', "A1KAXIG6VXSG8Y"),
                "deviceId": self.tokens.get('device_id')
            },
            "appInfo": {
                "musicAgent": f"Harley/3.12.11.183 Harley/24.10.1 ({uuid.uuid4()} {track_asin})"
            },
            "DrmType": "PLAYREADY",
            "licenseChallenge": challenge_b64
        }
        headers = {
            "x-amzn-requestid": str(uuid.uuid4()),
            "X-Amz-Target": "com.amazon.digitalmusiclocator.DigitalMusicLocatorServiceExternal.getLicenseForPlaybackV2",
            "x-amz-access-token": self.tokens.get('x-amz-access-token'),
            "Content-Encoding": "amz-1.0"
        }
        async with self.session.post(url, json=payload, headers=headers) as resp:
            if resp.status != 200:
                raise Exception(f"License API failed: {resp.status}")
            data = await resp.json()
            if "license" not in data:
                raise Exception("Lisensi PlayReady ditolak oleh Amazon.")
            return data["license"]

    async def close(self):
        if not self.session.closed:
            await self.session.close()
