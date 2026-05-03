import os
import json
import uuid
import time
import asyncio
import aiohttp
from urllib.parse import unquote
from bot.logger import LOGGER

class AmazonApi:
    def __init__(self, region="us"):
        self.region = region.lower()
        self.session = aiohttp.ClientSession()
        self.tokens = {}
        
        # Konfigurasi Region & Endpoint
        self.base_urls = {
            "mx": "https://music.amazon.com.mx/",
            "br": "https://music.amazon.com.br/",
            "fr": "https://music.amazon.fr/",
            "us": "https://music.amazon.com/",
            "jp": "https://music.amazon.co.jp/",
            "uk": "https://music.amazon.co.uk/",
            "de": "https://music.amazon.de/",
        }
        
        # Mapping API Location
        api_locations = {"NA": ["br", "mx", "us"], "EU": ["fr", "de", "uk"], "FE": ["jp"]}
        api_urls = {"NA": "na.tvmesk.skill.music.a2z.com", "EU": "eu.tvmesk.skill.music.a2z.com", "FE": "fe.tvmesk.skill.music.a2z.com"}
        
        self.base_url = self.base_urls.get(self.region, self.base_urls["us"])
        
        api_location = next((loc for loc, regs in api_locations.items() if self.region in regs), "NA")
        self.api_url = api_urls.get(api_location)

        # --- FIX: KEMBALIKAN HEADERS LENGKAP AGAR TIDAK KENA ERROR 500 ---
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
        
        async with self.session.post(
            f"https://{self.api_url}/api/showHome",
            json={"userHash": ""},
            headers=headers
        ) as resp:
            # Tambahkan pembacaan error text agar kalau gagal, log-nya lebih jelas
            if resp.status != 200:
                err_text = await resp.text()
                raise Exception(f"HTTP {resp.status}: {err_text}")
                
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

        async with self.session.post(
            f"https://{self.api_url}/api/showHome",
            headers=headers,
            data=payload
        ) as resp:
            if resp.status != 200:
                return False
                
            register_json = await resp.json()
            
            service_token = None
            for item in register_json.get("methods", []):
                if item.get("interface") == "PlaybackAuthenticationInterface.v1_0.SetAuthenticationMethod" and item.get("authentication"):
                    service_token = item["authentication"]
                    break
                    
            if service_token:
                token_data = json.loads(service_token)
                self.tokens["service_token"] = service_token
                self.tokens["x-amz-access-token"] = token_data["accessToken"]
                LOGGER.info("Amazon API: Sesi TV berhasil didapatkan!")
                return self.tokens
                
        return False

    async def close(self):
        if not self.session.closed:
            await self.session.close()
