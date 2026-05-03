# [FILE: bot/helpers/amazon/amazon_api.py]

import os, json, uuid, time, asyncio, aiohttp, re, html, base64
from urllib.parse import unquote
from bot.logger import LOGGER

class AmazonApi:
    def __init__(self, region="us"):
        self.region = region.lower()
        self.session = aiohttp.ClientSession()
        self.tokens = {}
        self.base_urls = {
            "mx": "https://music.amazon.com.mx/", "br": "https://music.amazon.com.br/",
            "fr": "https://music.amazon.fr/", "us": "https://music.amazon.com/",
            "jp": "https://music.amazon.co.jp/", "uk": "https://music.amazon.co.uk/", "de": "https://music.amazon.de/"
        }
        self.marketplaces = {
            "mx": "ART4WZ8MWBX2Y", "br": "A2Q3Y263D00KWC", "fr": "A13V1IB3VIYZZH",
            "us": "ATVPDKIKX0DER", "jp": "A1VC38T7YXB528", "uk": "A1F83G8C2ARO7P", "de": "A1PA6795UKMFR9"
        }
        api_locations = {"NA": ["br", "mx", "us"], "EU": ["fr", "de", "uk"], "FE": ["jp"]}
        self.api_location = next((loc for loc, regs in api_locations.items() if self.region in regs), "NA")
        self.base_url = self.base_urls.get(self.region, self.base_urls["us"])
        self.api_url = f"{self.api_location.lower()}.tvmesk.skill.music.a2z.com"

        # --- FIX: KEMBALIKAN HEADERS LENGKAP UNTUK MENCEGAH NumberFormatException (HTTP 500) ---
        self.session.headers.update({
            "origin": "https://music.amazon.com",
            "referer": "https://music.amazon.com/",
            "user-agent": "Harley/3.12.11.183 A1I3OANZGDNGEE/24.10.1",
            "x-amzn-device-type-id": "A1KAXIG6VXSG8Y",
            "x-amzn-hardware-device-type-id": "A1KAXIG6VXSG8Y",
            "x-amzn-device-family": "AndroidTV",
            "x-amzn-device-manufacturer": "NVIDIA",
            "x-amzn-device-model": "A1KAXIG6VXSG8Y",
            "x-amzn-device-language": "en_US",
            "x-amzn-device-height": "2160",
            "x-amzn-device-width": "3840",
            "x-amzn-os-version": "11",
            "x-amzn-application-version": "3.12.11.183",
            "x-amzn-device-time-zone": "America/Detroit",
            "x-amzn-user-agent": "Dalvik/2.1.0 (Linux; U; Android 9; Smart TV Build/PPR1.180610.011)"
        })

    async def get_tv_device_code(self):
        self.tokens["device_id"] = os.urandom(8).hex()
        headers = {
            "x-amzn-request-id": str(uuid.uuid4()),
            "x-amzn-timestamp": str(int(time.time()*1000)),
            "x-amzn-device-id": self.tokens["device_id"]
        }
        async with self.session.post(f"https://{self.api_url}/api/showHome", json={"userHash": ""}, headers=headers) as resp:
            # Ambil sedikit teks saja jika error agar tidak crash Telegram
            if resp.status != 200: raise Exception(f"HTTP {resp.status}: {(await resp.text())[:150]}")
            data = await resp.json()
            pair = data["methods"][0]["template"]
            return pair.get("code"), unquote(pair["onPollingIntervalElapsed"][0]["url"].rsplit("code=", 1)[-1]), self.base_url.replace("music.", "") + "code"

    async def poll_tv_auth(self, register_code):
        headers = {"x-amzn-request-id": str(uuid.uuid4()), "x-amzn-timestamp": str(int(time.time()*1000)), "x-amzn-device-id": self.tokens["device_id"]}
        async with self.session.post(f"https://{self.api_url}/api/showHome", headers=headers, json={"code": register_code}) as resp:
            if resp.status != 200: return False
            data = await resp.json()
            for item in data.get("methods", []):
                if item.get("interface") == "PlaybackAuthenticationInterface.v1_0.SetAuthenticationMethod":
                    auth = json.loads(item["authentication"])
                    self.tokens.update({"x-amz-access-token": auth["accessToken"], "marketplaceId": auth.get("marketplaceId", "US")})
                if item.get("interface") == "VideoPlayerAuthenticationInterface.v1_0.SetVideoPlayerTokenMethod":
                    try:
                        jwt = item["header"].split(".")[1]
                        decoded = base64.urlsafe_b64decode(jwt + "=" * (-len(jwt)%4)).decode("latin-1")
                        self.tokens["customerId"] = re.search(r'"customerId"\s*:\s*"([^"]+)"', decoded).group(1)
                        self.tokens["device_id"] = re.search(r'"deviceId"\s*:\s*"([^"]+)"', decoded).group(1)
                        self.tokens["deviceTypeId"] = re.search(r'"deviceType(?:Id)?"\s*:\s*"([^"]+)"', decoded).group(1)
                    except: pass
            return self.tokens if "x-amz-access-token" in self.tokens else False

    async def get_playback_info(self, asin: str):
        cid = self.tokens.get('customerId')
        if not cid: raise Exception("CustomerID Kosong. Silakan login ulang.")
        mid, dtid = self.marketplaces.get(self.region, "ATVPDKIKX0DER"), self.tokens.get('deviceTypeId', "A1KAXIG6VXSG8Y")
        
        self.session.headers.update({
            "x-amz-access-token": self.tokens['x-amz-access-token'],
            "x-amzn-device-type-id": dtid, "x-amzn-device-id": self.tokens['device_id']
        })
        
        async with self.session.post(f"{self.base_url}{self.api_location}/api/muse/legacy/lookup", 
            json={"asins": [asin], "features": ["expandTracklist"], "musicTerritory": self.region.upper(), "deviceId": self.tokens['device_id'], "deviceType": dtid},
            headers={"X-Amz-Target": "com.amazon.musicensembleservice.MusicEnsembleService.lookup"}) as resp:
            meta = {}
            if resp.status == 200:
                d = await resp.json()
                t = d.get('trackList', [{}])[0]
                meta = {'title': t.get('title', asin), 'artist': t.get('artist', {}).get('name'), 'album': t.get('album', {}).get('title')}

        payload = {
            "deviceToken": {"deviceTypeId": dtid, "deviceId": self.tokens['device_id']},
            "contentIdList": [{"identifier": asin, "identifierType": "ASIN"}],
            "customerInfo": {"customerId": cid, "marketplaceId": mid, "territoryId": self.region.upper()},
            "appInfo": {"musicAgent": f"Harley/3.12.11.183 ({uuid.uuid4()})"},
            "musicDashVersionList": ["SIREN_KATANA"], "contentProtectionList": ["TRACK_PSSH"]
        }
        async with self.session.post(f"{self.base_url}{self.api_location}/api/dmls/", json=payload,
            headers={"X-Amz-Target": "com.amazon.digitalmusiclocator.DigitalMusicLocatorServiceExternal.getDashManifestsV2"}) as resp:
            data = await resp.json()
            if "contentResponseList" not in data: raise Exception("Amazon menolak akses.")
            mpd = data["contentResponseList"][0].get("manifest", "")
            kid = re.search(r'default_KID=["\']([^"\']+)["\']', mpd, re.I).group(1) if "default_KID" in mpd else ""
            url = html.unescape(re.search(r"<BaseURL[^>]*>([\s\S]*?)</BaseURL>", mpd, re.I).group(1).strip()) if "<BaseURL" in mpd else ""
            
        return {**meta, 'url': url, 'kid': kid}

    async def get_license(self, challenge, asin):
        payload = {
            "deviceToken": {"deviceTypeId": self.tokens.get('deviceTypeId', "A1KAXIG6VXSG8Y"), "deviceId": self.tokens['device_id']},
            "DrmType": "PLAYREADY", "licenseChallenge": challenge, "appInfo": {"musicAgent": f"Harley ({asin})"}
        }
        async with self.session.post(f"{self.base_url}{self.api_location}/api/dmls/getLicenseForPlaybackV2", json=payload,
            headers={"X-Amz-Target": "com.amazon.digitalmusiclocator.DigitalMusicLocatorServiceExternal.getLicenseForPlaybackV2"}) as resp:
            return (await resp.json())["license"]

    async def close(self):
        if not self.session.closed: await self.session.close()
