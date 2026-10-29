# [GANTI FILE: bot/helpers/qobuz/bundle.py]

import re
import base64
from collections import OrderedDict

from requests import Session
from config import Config

# Modified code based on DashLt's spoofbuz

_SEED_TIMEZONE_REGEX = re.compile(
    r'[a-z]\.initialSeed\("(?P<seed>[\w=]+)",window\.utimezone\.(?P<timezone>[a-z]+)\)'
)
_INFO_EXTRAS_REGEX = r'name:"\w+/(?P<timezone>{timezones})",info:"(?P<info>[\w=]+)",extras:"(?P<extras>[\w=]+)"'
_APP_ID_REGEX = re.compile(
    r'production:{api:{appId:"(?P<app_id>\d{9})",appSecret:"\w{32}"'
)

_BASE_URL = "https://play.qobuz.com"
_BUNDLE_URL_REGEX = re.compile(
    r'<script src="(/resources/\d+\.\d+\.\d+-[a-z]\d{3}/bundle\.js)"></script>'
)


class Bundle:
    def __init__(self):
        self._session = Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0"
        })

        # --- SUNTIKAN PROXY GLOBAL ---
        if getattr(Config, 'QOBUZ_PROXY', None):
            self._session.proxies = {
                "http": Config.QOBUZ_PROXY,
                "https": Config.QOBUZ_PROXY
            }
        # -----------------------------

        try:
            response = self._session.get(f"{_BASE_URL}/login", timeout=20)
            response.raise_for_status()

            bundle_url_match = _BUNDLE_URL_REGEX.search(response.text)
            if not bundle_url_match:
                raise NotImplementedError("Bundle URL not found")

            bundle_url = bundle_url_match.group(1)
            response = self._session.get(_BASE_URL + bundle_url, timeout=30)
            response.raise_for_status()

            self._bundle = response.text
        finally:
            self._session.close()

    def get_app_id(self):
        match = _APP_ID_REGEX.search(self._bundle)
        if not match:
            raise NotImplementedError("Failed to match APP ID")

        return match.group("app_id")

    def get_secrets(self):
        seed_matches = _SEED_TIMEZONE_REGEX.finditer(self._bundle)
        secrets = OrderedDict()

        for match in seed_matches:
            seed, timezone = match.group("seed", "timezone")
            secrets[timezone] = [seed]

        keypairs = list(secrets.items())
        if len(keypairs) > 1:
            secrets.move_to_end(keypairs[1][0], last=False)

        info_extras_regex = _INFO_EXTRAS_REGEX.format(
            timezones="|".join([timezone.capitalize() for timezone in secrets])
        )
        info_extras_matches = re.finditer(info_extras_regex, self._bundle)
        for match in info_extras_matches:
            timezone, info, extras = match.group("timezone", "info", "extras")
            secrets[timezone.lower()] += [info, extras]
        for secret_pair in list(secrets.keys()):
            try:
                secrets[secret_pair] = base64.standard_b64decode(
                    "".join(secrets[secret_pair])[:-44]
                ).decode("utf-8")
            except Exception:
                secrets[secret_pair] = ""
        return secrets
