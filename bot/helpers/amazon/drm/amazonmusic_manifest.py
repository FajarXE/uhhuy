import os
import re
import sys
import json
import time
import uuid
import html
import base64
import logging
import unicodedata
import requests
from pathlib import Path
from urllib.parse import urlparse
from pypr import PlayReadyHeaderBuilder, PSSH, Device, Cdm

logging.basicConfig(level=logging.INFO, format="%(name)s - %(levelname)s - %(message)s")
log = logging.getLogger("amazonmusic_manifest")

try:
    import inquirer
except Exception:
    log.error("Missing dependency: pip install inquirer")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_PROGRESS_WIDTH = 40
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)


def clean_text(value, fallback):
    if value is None:
        value = ""
    value = html.unescape(str(value))
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    value = re.sub(r"\s+", " ", value).strip()
    return value if value else fallback

def first_text(*values):
    for value in values:
        value = clean_text(value, "")
        if value:
            return value
    return ""

def get_artist_name(track, album_data):
    artist_values = []
    if isinstance(track.get("artist"), dict):
        artist_values.append(track["artist"].get("name"))
    artist_values.append(track.get("artistName"))
    artist_values.append(track.get("primaryArtistName"))
    artist_values.append(track.get("albumArtistName"))
    if isinstance(album_data.get("artist"), dict):
        artist_values.append(album_data["artist"].get("name"))
    return first_text(*artist_values) or "Unknown artist"

def get_track_title(track):
    return first_text(track.get("title"), track.get("name"), track.get("trackTitle"), track.get("displayTitle")) or "Unknown title"

def get_album_title(album_data, album_asin):
    return first_text(album_data.get("title"), album_data.get("name"), album_data.get("albumTitle"), album_data.get("displayTitle")) or album_asin

def windows_safe_name(value, fallback):
    value = clean_text(value, fallback)
    value = re.sub(r'[<>:"/\\\\|?*\x00-\x1F]', " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = value.rstrip(" .")
    reserved_names = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }
    if not value:
        value = fallback
    if value.upper() in reserved_names:
        value = value + "_"
    return value

def limit_filename_bytes(value, max_bytes):
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    while value and len(value.encode("utf-8")) > max_bytes:
        value = value[:-1]
    return value.rstrip(" .") or "track"

def build_codec_file_label(track_type, codec_value, sampling_value, bitdepth_value, ql_value, bitrate_label):
    track_type = clean_text(track_type, "UNKNOWN").upper()
    codec_value = clean_text(codec_value, "unknown").upper()
    sampling_value = clean_text(sampling_value, "0")
    bitdepth_value = clean_text(bitdepth_value, "")
    ql_value = clean_text(ql_value, track_type).upper().replace("_", "")
    bitrate_value = clean_text(bitrate_label, "0 kbps").lower().replace(" kbps", "k").replace(" ", "")
    parts = []
    if ql_value:
        parts.append(ql_value)
    elif track_type:
        parts.append(track_type)
    parts.append(codec_value)
    if bitdepth_value:
        parts.append(f"{bitdepth_value}b")
    if bitrate_value and bitrate_value != "0k":
        parts.append(bitrate_value)
    return "-".join(parts)

def build_codec_folder_label(track_type, codec_value, sampling_value, bitdepth_value, ql_value, bitrate_label):
    track_type = clean_text(track_type, "UNKNOWN").upper()
    codec_value = clean_text(codec_value, "unknown").upper()
    ql_value = clean_text(ql_value, track_type).upper().replace("_", "")
    bitdepth_value = clean_text(bitdepth_value, "")
    parts = []
    if ql_value:
        parts.append(ql_value)
    elif track_type:
        parts.append(track_type)
    parts.append(codec_value)
    if bitdepth_value:
        parts.append(f"{bitdepth_value}b")
    return "-".join(parts)

def build_album_codec_dir(album_title, album_asin, codec_folder_label):
    safe_album = windows_safe_name(album_title, album_asin or "Unknown album")
    safe_album_asin = windows_safe_name(album_asin or "Unknown album", "Unknown album")
    safe_codec = windows_safe_name(codec_folder_label, "Unknown codec")
    album_folder_name = limit_filename_bytes(f"{safe_album} [{safe_album_asin}]", 180)
    codec_folder_name = limit_filename_bytes(safe_codec, 100)
    album_codec_dir = DOWNLOAD_DIR / album_folder_name / codec_folder_name
    album_codec_dir.mkdir(parents=True, exist_ok=True)
    return album_codec_dir

def build_download_path(album_title, album_asin, codec_folder_label, track_number, artist_name, track_title, track_asin):
    album_codec_dir = build_album_codec_dir(album_title, album_asin, codec_folder_label)
    safe_artist = windows_safe_name(artist_name, "Unknown artist")
    safe_title = windows_safe_name(track_title, track_asin or "Unknown title")
    safe_asin = windows_safe_name(track_asin or str(uuid.uuid4()), "Unknown ASIN")
    base_name = f"{track_number:02d} - {safe_artist} - {safe_title} [{safe_asin}]"
    base_name = limit_filename_bytes(base_name, 220)
    download_path = album_codec_dir / f"{base_name}.mp4"
    if not download_path.exists():
        return download_path
    duplicate_index = 2
    while True:
        candidate_base = limit_filename_bytes(f"{base_name} [{duplicate_index}]", 220)
        candidate_path = album_codec_dir / f"{candidate_base}.mp4"
        if not candidate_path.exists():
            return candidate_path
        duplicate_index += 1

def extract_cover_url(value):
    if isinstance(value, dict):
        direct_keys = [
            "image",
            "imageUrl",
            "albumArt",
            "albumArtUrl",
            "cover",
            "coverUrl",
            "largeImage",
            "thumbnail",
            "thumbnailUrl",
            "url",
        ]
        for key in direct_keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and re.match(r"https?://", candidate, re.I):
                return html.unescape(candidate)
        for nested_key in ["album", "images", "imageSet", "artwork", "coverArt", "metadata"]:
            nested_value = value.get(nested_key)
            found = extract_cover_url(nested_value)
            if found:
                return found
        for nested_value in value.values():
            found = extract_cover_url(nested_value)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = extract_cover_url(item)
            if found:
                return found
    if isinstance(value, str) and re.match(r"https?://.*\.(jpg|jpeg|png)(\?|$)", value, re.I):
        return html.unescape(value)
    return ""

def download_cover_image(cover_url, album_asin, session):
    if not cover_url:
        return None
    cover_path = DOWNLOAD_DIR / f"{album_asin}_cover.jpg"
    try:
        response = session.get(cover_url, headers={"User-Agent": DEFAULT_HEADERS["user-agent"]}, timeout=30)
        if response.status_code != 200 or not response.content:
            log.warning(f"Cover download failed: HTTP {response.status_code}")
            return None
        content_type = response.headers.get("content-type", "").lower()
        if "png" in content_type or response.content.startswith(b"\x89PNG"):
            cover_path = DOWNLOAD_DIR / f"{album_asin}_cover.png"
        cover_path.write_bytes(response.content)
        log.info(f"Cover: {cover_path.name}")
        return cover_path
    except Exception as e:
        log.warning(f"Cover download failed: {e}")
        return None

def embed_cover_image(mp4_path, cover_path):
    if not cover_path or not Path(cover_path).exists():
        return False
    try:
        from mutagen.mp4 import MP4, MP4Cover
        audio = MP4(str(mp4_path))
        cover_data = Path(cover_path).read_bytes()
        image_format = MP4Cover.FORMAT_PNG if cover_data.startswith(b"\x89PNG") else MP4Cover.FORMAT_JPEG
        audio["covr"] = [MP4Cover(cover_data, imageformat=image_format)]
        audio.save()
        log.info(f"Cover embedded: {Path(mp4_path).name}")
        return True
    except ImportError:
        log.warning("Cover embed skipped: pip install mutagen")
    except Exception as e:
        log.warning(f"Cover embed failed: {e}")
    return False

def get_track_mpd(session, base_url, api_location, device_type_id, device_id, marketplace_id, territory_id, access_token, track_asin):
    dmls_response = session.post(f"{base_url}{api_location}/api/dmls/",
                                 json={
                                     "deviceToken": {
                                         "deviceTypeId": device_type_id,
                                         "deviceId": device_id
                                     },
                                     "appInfo": {
                                         "musicAgent": f"Harley/3.12.11.183 Harley/24.10.1 ({uuid.uuid4()} {track_asin})"
                                     },
                                     "contentIdList": [
                                         {
                                             "identifier": track_asin,
                                             "identifierType": "ASIN"
                                         }
                                     ],
                                     "musicDashVersionList": [
                                         "SIREN_KATANA"
                                     ],
                                     "contentProtectionList": [
                                         "TRACK_PSSH"
                                     ],
                                     "customerInfo": {
                                         "marketplaceId": marketplace_id,
                                         "territoryId": territory_id
                                     },
                                     "try3dAsinSubstitution": True,
                                     "tryAsinSubstitution": True
                                 },
                                 headers={
                                     "X-Amz-RequestId": str(uuid.uuid4()),
                                     "X-Amz-Target": "com.amazon.digitalmusiclocator.DigitalMusicLocatorServiceExternal.getDashManifestsV2",
                                     "x-amz-access-token": access_token,
                                     "Content-Encoding": "amz-1.0"
                                 })
    if dmls_response.status_code != 200:
        log.error(f"DMLS failed: {track_asin} {dmls_response.status_code} {dmls_response.text[:300]}")
        return ""
    try:
        dmls_json = dmls_response.json()
        return dmls_json["contentResponseList"][0]["manifest"]
    except Exception as e:
        log.error(f"MPD parse failed: {track_asin} {e}")
        return ""


def get_playready_license_keys(session, api_location, device_type_id, device_id, access_token, track_asin, default_kid):
    kid = clean_text(default_kid, "").replace("-", "")
    if not kid:
        log.error("Default KID missing")
        return []

    builder = PlayReadyHeaderBuilder(kid)
    header = builder.build_header(
        version="4.0",
        header_spec=None,
        encryption_scheme="cenc",
        key_specs=[(kid, kid)],
    )
    playready_header = base64.b64encode(header).decode("ascii")

    device_path = BASE_DIR / "hisense_smarttv_hu32e5600fhwv_sl3000.prd"
    if not device_path.exists():
        device_path = Path("hisense_smarttv_hu32e5600fhwv_sl3000.prd")

    device = Device.load(str(device_path))
    cdm = Cdm.from_device(device)
    session_id = cdm.open()

    try:
        pssh = PSSH(playready_header)
        challenge = cdm.get_license_challenge(session_id, pssh.wrm_headers[0])
        challenge = base64.b64encode(challenge.encode("utf-8")).decode("utf-8")

        license_response = session.post(f"{base_url}{api_location}/api/dmls/getLicenseForPlaybackV2",
                                        json={
                                            "deviceToken": {
                                                "deviceTypeId": device_type_id,
                                                "deviceId": device_id
                                            },
                                            "appInfo": {
                                                "musicAgent": f"Harley/3.12.11.183 Harley/24.10.1 ({str(uuid.uuid4())} {track_asin})"
                                            },
                                            "DrmType": "PLAYREADY",
                                            "licenseChallenge": challenge
                                        },
                                        headers={
                                            "x-amzn-requestid": str(uuid.uuid4()),
                                            "X-Amz-Target": "com.amazon.digitalmusiclocator.DigitalMusicLocatorServiceExternal.getLicenseForPlaybackV2",
                                            "x-amz-access-token": access_token,
                                            "Content-Encoding": "amz-1.0"
                                        },
                                        cookies=None)

        if license_response.status_code != 200:
            log.error(f"License failed: HTTP {license_response.status_code}")
            return []

        try:
            license_json = license_response.json()
        except Exception as e:
            log.error(f"License JSON failed: {e}")
            return []

        if license_json.get("__type", "").endswith("DrmLicenseDeniedException"):
            log.error("License denied")
            return []

        license_data = license_json.get("license")
        if not license_data:
            log.error("License missing")
            return []

        decoded_data = base64.b64decode(license_data).decode("utf-8")
        cdm.parse_license(session_id, decoded_data)

        keys = []
        for key in cdm.get_keys(session_id):
            key_str = f"{key.key_id.hex}:{key.key.hex()}"
            log.info(key_str)
            keys.append(key_str)

        return keys

    finally:
        try:
            cdm.close(session_id)
        except Exception:
            pass


def decrypt_downloaded_file(download_path, keys, cover_path):
    if not keys:
        log.error("No keys available")
        return False

    try:
        import pydecrypt
    except Exception:
        log.error("Missing dependency: pydecrypt")
        return False

    try:
        temp_output = download_path.with_name(download_path.stem + "_decrypt" + download_path.suffix)
        keys_by_track, keys_by_kid = pydecrypt.parse_keys(keys)

        pydecrypt.decrypt_mp4_file(
            input_path=str(download_path),
            output_path=str(temp_output),
            keys_by_track=keys_by_track,
            keys_by_kid=keys_by_kid,
            show_tracks=True,
        )

        temp_output.replace(download_path)
        log.info(f"Decrypted: {download_path.name}")
        embed_cover_image(download_path, cover_path)
        return True

    except Exception as e:
        log.error(f"Decrypt failed: {e}")
        return False


def build_codec_choices_from_mpd(mpd_text):
    adaptation_blocks = re.findall(r"<AdaptationSet\b[\s\S]*?</AdaptationSet>", mpd_text)
    codec_choices = []
    codec_seen = set()
    for adaptation_block in adaptation_blocks:
        track_type_match = re.search(r'schemeIdUri="amz-music:trackType"\s+value="([^"]+)"', adaptation_block)
        track_type = track_type_match.group(1) if track_type_match else "UNKNOWN"
        representations = re.findall(r"<Representation\b[\s\S]*?</Representation>", adaptation_block)
        for representation_block in representations:
            codec_match = re.search(r'codecs="([^"]+)"', representation_block)
            bandwidth_match = re.search(r'bandwidth="([^"]+)"', representation_block)
            sampling_match = re.search(r'audioSamplingRate="([^"]+)"', representation_block)
            ranking_match = re.search(r'qualityRanking="([^"]+)"', representation_block)
            bitdepth_match = re.search(r'schemeIdUri="amz-music:bitDepth"\s+value="([^"]+)"', representation_block)
            baseurl_match = re.search(r"<BaseURL>([\s\S]*?)</BaseURL>", representation_block)
            codec_value = codec_match.group(1) if codec_match else "unknown"
            bandwidth_value = bandwidth_match.group(1) if bandwidth_match else "0"
            sampling_value = sampling_match.group(1) if sampling_match else "0"
            ranking_value = ranking_match.group(1) if ranking_match else "0"
            bitdepth_value = bitdepth_match.group(1) if bitdepth_match else ""
            baseurl_value = html.unescape(baseurl_match.group(1).strip()) if baseurl_match else ""
            ql_match = re.search(r"[?&]ql=([^&]+)", baseurl_value)
            ql_value = ql_match.group(1) if ql_match else track_type
            signature = f"{track_type}|{codec_value}|{sampling_value}|{bitdepth_value}|{ql_value}|{ranking_value}"
            bandwidth_int = 0
            try:
                bandwidth_int = int(bandwidth_value)
            except Exception:
                bandwidth_int = 0
            bitrate_label = "0 kbps"
            if bandwidth_int > 0:
                raw_kbps = bandwidth_int / 1000
                normalized_kbps = int(round(raw_kbps))
                if codec_value.lower().startswith("ec-3") or codec_value.lower().startswith("ac-4") or codec_value.lower() == "opus":
                    known_bitrates = [48, 64, 96, 128, 160, 192, 224, 256, 320, 384, 448, 512, 576, 640, 768, 1024, 1536]
                    normalized_kbps = min(known_bitrates, key=lambda item: abs(item - raw_kbps))
                bitrate_label = f"{normalized_kbps} kbps"
            label = f"{track_type} | {codec_value} | {sampling_value} Hz"
            if bitdepth_value:
                label += f" | {bitdepth_value}-bit"
            label += f" | {ql_value} | {bitrate_label}"
            if signature not in codec_seen:
                codec_seen.add(signature)
                codec_choices.append((label, signature, bandwidth_int))
    return [(label, signature) for label, signature, _ in sorted(codec_choices, key=lambda item: item[2], reverse=True)]


REGION_FROM_DOMAIN = {
    "music.amazon.com.mx": "mx",
    "music.amazon.com.br": "br",
    "music.amazon.com": "us",
    "music.amazon.fr": "fr",
    "music.amazon.co.jp": "jp",
    "music.amazon.co.uk": "uk",
    "music.amazon.de": "de",
}

BASE_URLS = {
    "mx": "https://music.amazon.com.mx/",
    "br": "https://music.amazon.com.br/",
    "fr": "https://music.amazon.fr/",
    "us": "https://music.amazon.com/",
    "jp": "https://music.amazon.co.jp/",
    "uk": "https://music.amazon.co.uk/",
    "de": "https://music.amazon.de/",
}

API_LOCATION_BY_REGION = {
    "mx": "NA",
    "br": "NA",
    "us": "NA",
    "fr": "EU",
    "de": "EU",
    "uk": "EU",
    "jp": "FE",
}

TVMESK_BY_LOCATION = {
    "NA": "na.tvmesk.skill.music.a2z.com",
    "EU": "eu.tvmesk.skill.music.a2z.com",
    "FE": "fe.tvmesk.skill.music.a2z.com",
}

DEFAULT_HEADERS = {
    "origin": "https://music.amazon.com",
    "referer": "https://music.amazon.com/",
    "user-agent": "Harley/3.12.11.183 A1I3OANZGDNGEE/24.10.1",
    "x-amzn-device-type-id": "A1I3OANZGDNGEE",
    "x-amzn-hardware-device-type-id": "A1MPSLFC7L5AFK",
    "x-amzn-device-family": "AndroidTV",
    "x-amzn-device-manufacturer": "NVIDIA",
    "x-amzn-device-model": "A1I3OANZGDNGEE",
    "x-amzn-device-language": "en_US",
    "x-amzn-device-height": "1080",
    "x-amzn-device-width": "1920",
    "x-amzn-os-version": "11",
    "x-amzn-application-version": "3.12.11.183",
    "x-amzn-device-time-zone": "America/Detroit",
    "x-amzn-user-agent": "Dalvik/2.1.0 (Linux; U; Android 9; Smart TV Build/PPR1.180610.011)",
}

album_url = input("Enter Amazon Music album URL: ").strip()

if not album_url:
    log.error("URL required")
    sys.exit(1)

parsed_url = urlparse(album_url)
domain = parsed_url.netloc.lower()
region = None

for known_domain, known_region in REGION_FROM_DOMAIN.items():
    if domain == known_domain or domain.endswith("." + known_domain):
        region = known_region
        break

if not region:
    log.error("Region not detected")
    sys.exit(1)

album_match = re.search(r"/albums/([A-Z0-9]+)", album_url, re.I)

if not album_match:
    log.error("Album ASIN not found")
    sys.exit(1)

album_asin = album_match.group(1).upper()
api_location = API_LOCATION_BY_REGION[region]
base_url = BASE_URLS[region]
tvmesk_host = TVMESK_BY_LOCATION[api_location]

log.info(f"Album: {album_asin}")
log.info(f"Region: {region.upper()}")

token_candidates = []
for path in BASE_DIR.glob(f"amazonmusic_{region}_tokens*.json"):
    token_candidates.append(path)
for path in BASE_DIR.glob("amazonmusic_*_tokens*.json"):
    if path not in token_candidates:
        token_candidates.append(path)
for path in BASE_DIR.glob("*tokens*.json"):
    if path not in token_candidates:
        token_candidates.append(path)

if not token_candidates:
    log.error("Token JSON not found")
    sys.exit(1)

token_candidates = sorted(token_candidates, key=lambda p: p.stat().st_mtime, reverse=True)
tokens_path = token_candidates[0]

log.info(f"Tokens: {tokens_path.name}")

try:
    tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
except Exception as e:
    log.error(f"Token read failed: {e}")
    sys.exit(1)

if not tokens.get("service_token") or not tokens.get("device_id"):
    log.error("Invalid token JSON")
    sys.exit(1)

service_token_json = {}
try:
    service_token_json = json.loads(tokens["service_token"])
except Exception:
    service_token_json = {}

access_token = tokens.get("x-amz-access-token") or service_token_json.get("accessToken")
service_marketplace_id = tokens.get("marketplaceId") or service_token_json.get("marketplaceId")
music_territory = tokens.get("musicTerritory") or region.upper()
device_id = tokens.get("device_id")
device_type_id = "A1I3OANZGDNGEE"
video_marketplace_id = None
video_territory_id = None
video_device_id = None
video_device_type_id = None
customer_id = None

video_player_header = tokens.get("x-amzn-video-player-token")
video_player_token = None

if isinstance(video_player_header, str):
    try:
        video_player_obj = json.loads(video_player_header)
        video_player_token = video_player_obj.get("token")
    except Exception:
        video_player_token = video_player_header

if video_player_token and video_player_token.count(".") >= 2:
    jwt_payload = video_player_token.split(".")[1]
    jwt_payload += "=" * (-len(jwt_payload) % 4)
    try:
        decoded_payload = base64.urlsafe_b64decode(jwt_payload.encode()).decode("latin-1", errors="ignore")
        match_customer = re.search(r'"customerId"\s*:\s*"([^"]+)"', decoded_payload)
        match_marketplace = re.search(r'"marketplaceId"\s*:\s*"([^"]+)"', decoded_payload)
        match_territory = re.search(r'"territoryId"\s*:\s*"([^"]+)"', decoded_payload)
        match_device_id = re.search(r'"deviceId"\s*:\s*"([^"]+)"', decoded_payload)
        match_device_type = re.search(r'"deviceTypeId"\s*:\s*"([^"]+)"', decoded_payload)
        if match_customer:
            customer_id = match_customer.group(1)
        if match_marketplace:
            video_marketplace_id = match_marketplace.group(1)
        if match_territory:
            video_territory_id = match_territory.group(1)
        if match_device_id:
            video_device_id = match_device_id.group(1)
        if match_device_type:
            video_device_type_id = match_device_type.group(1)
    except Exception:
        pass

if video_device_id:
    device_id = video_device_id

if video_device_type_id:
    device_type_id = video_device_type_id

marketplace_id = video_marketplace_id or service_marketplace_id
territory_id = video_territory_id or music_territory

if not access_token:
    log.error("Access token missing")
    sys.exit(1)

if not marketplace_id:
    log.error("Marketplace missing")
    sys.exit(1)

session = requests.Session()
session.headers.update(DEFAULT_HEADERS)

try:
    expires_at_ms = int(service_token_json.get("expiresAtMillis", "0"))
except Exception:
    expires_at_ms = 0

if expires_at_ms and expires_at_ms <= int(time.time() * 1000):
    log.info("Refreshing token")
    refresh_response = session.post(
        url=f"https://{tvmesk_host}/api/transferPlayback",
        json={
            "showNowPlaying": "false",
            "newMediaRequired": "true",
            "userHash": "",
        },
        headers={
            "x-amzn-request-id": str(uuid.uuid4()),
            "x-amzn-timestamp": str(int(time.time() * 1000)),
            "x-amzn-authentication": tokens["service_token"],
            "x-amzn-device-id": device_id,
        },
        timeout=30,
    )
    if refresh_response.status_code != 200:
        log.error(f"Refresh failed: {refresh_response.status_code}")
        sys.exit(1)
    refresh_json = refresh_response.json()
    refreshed_service_token = None
    for item in refresh_json.get("methods", []):
        if item.get("interface") == "PlaybackAuthenticationInterface.v1_0.SetAuthenticationMethod" and item.get("authentication"):
            refreshed_service_token = item["authentication"]
            break
    if not refreshed_service_token:
        log.error("Refresh token missing")
        sys.exit(1)
    tokens["service_token"] = refreshed_service_token
    service_token_json = json.loads(refreshed_service_token)
    tokens["x-amz-access-token"] = service_token_json.get("accessToken")
    access_token = tokens["x-amz-access-token"]
    if service_token_json.get("marketplaceId"):
        tokens["marketplaceId"] = service_token_json.get("marketplaceId")
    tokens_path.write_text(json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Token refreshed")

log.info("Album lookup")
lookup_response = session.post(
    url=f"{base_url}{api_location}/api/muse/legacy/lookup",
    headers={
        "x-amzn-requestid": str(uuid.uuid4()),
        "X-Amz-Target": "com.amazon.musicensembleservice.MusicEnsembleService.lookup",
    },
    json={
        "asins": [album_asin],
        "features": [
            "popularity",
            "expandTracklist",
            "trackLibraryAvailability",
            "collectionLibraryAvailability",
        ],
        "requestedContent": "MUSIC_SUBSCRIPTION",
        "musicTerritory": territory_id,
        "deviceId": device_id,
        "deviceType": device_type_id,
    },
    timeout=30,
)

if lookup_response.status_code != 200:
    log.error(f"Lookup failed: {lookup_response.status_code} {lookup_response.text[:300]}")
    sys.exit(1)

try:
    lookup_json = lookup_response.json()
except Exception:
    log.error("Lookup JSON failed")
    sys.exit(1)

album_data = None

if isinstance(lookup_json, dict) and lookup_json.get("albumList"):
    album_data = lookup_json["albumList"][0]

if not album_data:
    log.error("Album not found")
    sys.exit(1)

album_title = get_album_title(album_data, album_asin)
log.info(f"Album title: {album_title}")

album_cover_url = extract_cover_url(album_data)
cover_path = download_cover_image(album_cover_url, album_asin, session)

tracks = []

if isinstance(album_data.get("tracks"), list):
    for track in album_data.get("tracks", []):
        if isinstance(track, dict) and track.get("asin"):
            tracks.append(track)

if not tracks:
    log.error("No tracks")
    sys.exit(1)

log.info(f"Tracks: {len(tracks)}")

track_choices = [("All tracks", "__ALL__")]
for index, track in enumerate(tracks, 1):
    title = get_track_title(track)
    artist_name = get_artist_name(track, album_data)
    asin_value = clean_text(track.get("asin"), "")
    track_choices.append((f"{index}. {artist_name} - {title} [{asin_value}]", str(index - 1)))

track_answers = inquirer.prompt([
    inquirer.Checkbox(
        "tracks",
        message="Choose track",
        choices=track_choices,
    )
])

if not track_answers or not track_answers.get("tracks"):
    log.error("No track selected")
    sys.exit(1)

selected_track_indexes = []
if "__ALL__" in track_answers["tracks"]:
    selected_track_indexes = list(range(len(tracks)))
else:
    for selected_value in track_answers["tracks"]:
        try:
            selected_track_indexes.append(int(selected_value))
        except Exception:
            pass

selected_track_indexes = sorted(set(selected_track_indexes))

if not selected_track_indexes:
    log.error("No track selected")
    sys.exit(1)

log.info(f"Selected: {len(selected_track_indexes)}")

all_outputs = []

for count_index, track_index in enumerate(selected_track_indexes, 1):
    track = tracks[track_index]
    track_asin = clean_text(track.get("asin"), "")
    track_title = get_track_title(track)
    artist_name = get_artist_name(track, album_data)
    track_number = track.get("trackNum") or track.get("itemIndex") or track_index + 1
    try:
        track_number = int(track_number)
    except Exception:
        track_number = track_index + 1

    log.info(f"MPD {count_index}/{len(selected_track_indexes)}: {track_asin}")
    mpd_text = get_track_mpd(
        session,
        base_url,
        api_location,
        device_type_id,
        device_id,
        marketplace_id,
        territory_id,
        access_token,
        track_asin,
    )

    if not mpd_text:
        continue

    codec_choices = build_codec_choices_from_mpd(mpd_text)

    if not codec_choices:
        log.error(f"No codec options: {track_asin}")
        continue

    codec_choices_with_all = [("All codecs", "__ALL_CODECS__")] + codec_choices
    codec_answers = inquirer.prompt([
        inquirer.Checkbox(
            "codecs",
            message=f"Select codec for {track_number:02d} - {track_title}",
            choices=codec_choices_with_all,
        )
    ])

    if not codec_answers or not codec_answers.get("codecs"):
        log.error(f"No codec selected: {track_asin}")
        continue

    selected_codec_signatures = []
    if "__ALL_CODECS__" in codec_answers["codecs"]:
        selected_codec_signatures = [signature for _, signature in codec_choices]
    else:
        selected_codec_signatures = list(codec_answers["codecs"])

    selected_codec_signatures = [signature for signature in selected_codec_signatures if signature != "__ALL_CODECS__"]
    selected_codec_signatures = list(dict.fromkeys(selected_codec_signatures))

    if not selected_codec_signatures:
        log.error(f"No codec selected: {track_asin}")
        continue

    log.info(f"Codecs selected: {len(selected_codec_signatures)}")

    for codec_position, codec_signature in enumerate(selected_codec_signatures, 1):
        log.info(f"Codec job {codec_position}/{len(selected_codec_signatures)}")
        selected_mp4_url = ""
        selected_pssh = ""
        selected_kid = ""
        selected_label = ""
        selected_bitrate_label = ""
        selected_codec_file_label = ""
        selected_codec_folder_label = ""
        selected_init_range = ""
        selected_media_ranges = []
        adaptation_blocks = re.findall(r"<AdaptationSet\b[\s\S]*?</AdaptationSet>", mpd_text)

        for adaptation_block in adaptation_blocks:
            track_type_match = re.search(r'schemeIdUri="amz-music:trackType"\s+value="([^"]+)"', adaptation_block)
            track_type = track_type_match.group(1) if track_type_match else "UNKNOWN"
            pssh_match = re.search(r"<cenc:pssh>([^<]+)</cenc:pssh>", adaptation_block)
            pssh_value = pssh_match.group(1).strip() if pssh_match else ""
            kid_match = re.search(r'cenc:default_KID="([^"]+)"', adaptation_block)
            kid_value = kid_match.group(1).strip() if kid_match else ""
            representations = re.findall(r"<Representation\b[\s\S]*?</Representation>", adaptation_block)
            for representation_block in representations:
                codec_match = re.search(r'codecs="([^"]+)"', representation_block)
                sampling_match = re.search(r'audioSamplingRate="([^"]+)"', representation_block)
                bandwidth_match = re.search(r'bandwidth="([^"]+)"', representation_block)
                ranking_match = re.search(r'qualityRanking="([^"]+)"', representation_block)
                bitdepth_match = re.search(r'schemeIdUri="amz-music:bitDepth"\s+value="([^"]+)"', representation_block)
                baseurl_match = re.search(r"<BaseURL>([\s\S]*?)</BaseURL>", representation_block)
                init_match = re.search(r'<Initialization\s+range="([^"]+)"', representation_block)
                codec_value = codec_match.group(1) if codec_match else "unknown"
                sampling_value = sampling_match.group(1) if sampling_match else "0"
                bandwidth_value = bandwidth_match.group(1) if bandwidth_match else "0"
                ranking_value = ranking_match.group(1) if ranking_match else "0"
                bitdepth_value = bitdepth_match.group(1) if bitdepth_match else ""
                baseurl_value = html.unescape(baseurl_match.group(1).strip()) if baseurl_match else ""
                ql_match = re.search(r"[?&]ql=([^&]+)", baseurl_value)
                ql_value = ql_match.group(1) if ql_match else track_type
                signature = f"{track_type}|{codec_value}|{sampling_value}|{bitdepth_value}|{ql_value}|{ranking_value}"
                if signature == codec_signature:
                    bandwidth_int = 0
                    try:
                        bandwidth_int = int(bandwidth_value)
                    except Exception:
                        bandwidth_int = 0
                    bitrate_label = "0 kbps"
                    if bandwidth_int > 0:
                        raw_kbps = bandwidth_int / 1000
                        normalized_kbps = int(round(raw_kbps))
                        if codec_value.lower().startswith("ec-3") or codec_value.lower().startswith("ac-4") or codec_value.lower() == "opus":
                            known_bitrates = [48, 64, 96, 128, 160, 192, 224, 256, 320, 384, 448, 512, 576, 640, 768, 1024, 1536]
                            normalized_kbps = min(known_bitrates, key=lambda item: abs(item - raw_kbps))
                        bitrate_label = f"{normalized_kbps} kbps"
                    selected_mp4_url = baseurl_value
                    selected_pssh = pssh_value
                    selected_kid = kid_value
                    selected_init_range = init_match.group(1) if init_match else ""
                    selected_media_ranges = re.findall(r'<SegmentURL\s+mediaRange="([^"]+)"', representation_block)
                    selected_label = f"{track_type} | {codec_value} | {sampling_value} Hz"
                    if bitdepth_value:
                        selected_label += f" | {bitdepth_value}-bit"
                    selected_label += f" | {ql_value} | {bitrate_label}"
                    selected_bitrate_label = bitrate_label
                    selected_codec_file_label = build_codec_file_label(track_type, codec_value, sampling_value, bitdepth_value, ql_value, bitrate_label)
                    selected_codec_folder_label = build_codec_folder_label(track_type, codec_value, sampling_value, bitdepth_value, ql_value, bitrate_label)
                    break
            if selected_mp4_url:
                break

        if not selected_mp4_url:
            log.error(f"Codec not found: {track_asin}")
            continue

        download_path = build_download_path(album_title, album_asin, selected_codec_folder_label, track_number, artist_name, track_title, track_asin)

        log.info(f"Track: {track_title}")
        log.info(f"Artist: {artist_name}")
        log.info(f"ASIN: {track_asin}")
        log.info(f"Codec: {selected_label}")

        keys = get_playready_license_keys(
            session,
            api_location,
            device_type_id,
            device_id,
            access_token,
            track_asin,
            selected_kid,
        )

        if not keys:
            log.error(f"License keys missing: {track_asin}")
            continue

        chunk_times = []
        chunk_ranges = []
        if selected_init_range:
            chunk_ranges.append(selected_init_range)
        for media_range in selected_media_ranges:
            chunk_ranges.append(media_range)
        for _ in chunk_ranges:
            chunk_times.append(0.0)

        log.info(f"Folder: {download_path.parent.relative_to(DOWNLOAD_DIR)}")
        log.info(f"Download: {download_path.name}")
        download_start = time.time()
        download_failed = False

        try:
            with session.get(
                selected_mp4_url,
                headers={"User-Agent": DEFAULT_HEADERS["user-agent"]},
                stream=True,
                timeout=60,
            ) as stream_response:
                if stream_response.status_code != 200:
                    log.error(f"Download failed: HTTP {stream_response.status_code}")
                    download_failed = True
                else:
                    total_size = int(stream_response.headers.get("content-length", "0") or "0")
                    downloaded_size = 0

                    with open(download_path, "wb") as output_file:
                        for chunk in stream_response.iter_content(chunk_size=1024 * 1024):
                            if not chunk:
                                continue

                            output_file.write(chunk)
                            downloaded_size += len(chunk)

                            ratio = 1.0 if total_size <= 0 else max(0.0, min(1.0, downloaded_size / total_size))
                            filled = int(DOWNLOAD_PROGRESS_WIDTH * ratio)
                            bar = "■" * filled + " " * (DOWNLOAD_PROGRESS_WIDTH - filled)

                            elapsed = max(0.0, time.time() - download_start)
                            remaining = 0.0 if ratio <= 0 else max(0.0, elapsed * (1.0 - ratio) / ratio)

                            elapsed_s = int(round(elapsed))
                            remaining_s = int(round(remaining))

                            elapsed_h, elapsed_rem = divmod(elapsed_s, 3600)
                            elapsed_m, elapsed_sec = divmod(elapsed_rem, 60)

                            remaining_h, remaining_rem = divmod(remaining_s, 3600)
                            remaining_m, remaining_sec = divmod(remaining_rem, 60)

                            sys.stdout.write(
                                f"[{bar}] {ratio * 100:6.2f}% "
                                f"(elapsed: {elapsed_h:02d}:{elapsed_m:02d}:{elapsed_sec:02d}, "
                                f"remaining: {remaining_h:02d}:{remaining_m:02d}:{remaining_sec:02d})\r"
                            )
                            sys.stdout.flush()

                    sys.stdout.write("\n")
                    sys.stdout.flush()

        except Exception as e:
            log.error(f"Download failed: {e}")
            download_failed = True

        if download_failed:
            if download_path.exists() and download_path.stat().st_size <= 0:
                download_path.unlink(missing_ok=True) 

        log.info(f"Downloaded: {download_path.name}")

        if not decrypt_downloaded_file(download_path, keys, cover_path):
            continue

album_output_dir = DOWNLOAD_DIR / limit_filename_bytes(f"{windows_safe_name(album_title, album_asin)} [{windows_safe_name(album_asin, album_asin)}]", 180)
album_output_dir.mkdir(parents=True, exist_ok=True)

if cover_path and Path(cover_path).exists():
    try:
        Path(cover_path).unlink()
        log.info(f"Cover removed: {Path(cover_path).name}")
    except Exception as e:
        log.warning(f"Cover remove failed: {e}")

log.info(f"Done: {len(all_outputs)}")