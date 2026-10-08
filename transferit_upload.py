#!/usr/bin/env python3
"""Headless transfer.it uploader (Windows/Linux). Stdlib + openssl."""
from __future__ import annotations

import argparse
import base64
import functools
import hashlib
import http.client
import io
import json
import os
import secrets
import shutil
import signal
import string
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from tqdm import tqdm

tqdm.set_lock(threading.RLock())

try:
    import megacrypt  # native AES-CTR + chunk MAC; falls back to openssl when absent

    if not hasattr(megacrypt, "FileCipher"):  # a megacrypt/ source dir shadowing an uninstalled module
        megacrypt = None
except ImportError:
    megacrypt = None

G_API = "https://g.api.mega.co.nz/"
BT7_API = "https://bt7.api.mega.co.nz/"
WCV = "2.246.1130"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)
RETRY_HTTP = {408, 429, 500, 502, 503, 504}
RETRY_MEGA = {-3, -4, -6}  # EAGAIN, ERATELIMIT, ETOOMANY
ATTEMPTS = 5

VERBOSE = False
_LOG_LOCK = threading.Lock()
_PROGRESS: dict[str, tuple[float, str]] = {}
_LOCAL = threading.local()


def log(msg: str) -> None:
    if not VERBOSE:
        return
    with _LOG_LOCK:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def beat(key: str, detail: str) -> None:
    """Record what this thread is waiting on, replacing this thread's previous phase."""
    if not VERBOSE:
        return
    _PROGRESS.pop(getattr(_LOCAL, "key", None), None)
    _LOCAL.key = key
    _PROGRESS[key] = (time.monotonic(), detail)


def clear_beat(key: str | None = None) -> None:
    key = key if key is not None else getattr(_LOCAL, "key", None)
    if key is None:
        return
    _PROGRESS.pop(key, None)
    if getattr(_LOCAL, "key", None) == key:
        _LOCAL.key = None


def watchdog(interval: float = 10.0, idle: float = 25.0) -> None:
    """Report anything that has made no progress for `idle` seconds."""
    while True:
        time.sleep(interval)
        now = time.monotonic()
        for key, (ts, detail) in list(_PROGRESS.items()):
            if now - ts >= idle:
                log(f"WAITING {now - ts:.0f}s  {key}: {detail}")


def install_fast_interrupt() -> None:
    def _die(_sig, _frame):
        os._exit(130)

    signal.signal(signal.SIGINT, _die)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _die)


def _u32(x: int) -> int:
    return x & 0xFFFFFFFF


def a32_to_bytes(a: list[int]) -> bytes:
    return struct.pack(">%dI" % len(a), *(_u32(x) for x in a))


def bytes_to_a32(b: bytes) -> list[int]:
    if len(b) % 4:
        b += b"\0" * (4 - len(b) % 4)
    return list(struct.unpack(">%dI" % (len(b) // 4), b))


def b64u_encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii").replace("+", "-").replace("/", "_").rstrip("=")


def b64u_decode(s: str) -> bytes:
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * ((4 - len(s) % 4) % 4)
    return base64.b64decode(s)


def a32_to_b64(a: list[int]) -> str:
    return b64u_encode(a32_to_bytes(a))


def rand_a32(n: int = 4) -> list[int]:
    return list(struct.unpack(">%dI" % n, secrets.token_bytes(n * 4)))


def openssl_aes(mode: str, key: bytes, data: bytes, iv: bytes | None = None) -> bytes:
    if len(data) % 16:
        data = data + b"\0" * (16 - len(data) % 16)
    if mode not in ("cbc", "ctr", "ecb"):
        raise ValueError(mode)
    native_iv = iv or b"\0" * 16
    if megacrypt is not None and mode != "ctr":
        if mode == "ecb":
            return megacrypt.aes_ecb(key, data)
        return megacrypt.aes_cbc(key, data, native_iv)
    args = ["openssl", "enc", f"-aes-128-{mode}", "-K", key.hex(), "-nopad"]
    if mode in ("cbc", "ctr"):
        args += ["-iv", native_iv.hex()]
    try:
        p = subprocess.run(args, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except FileNotFoundError as e:
        raise RuntimeError("openssl not found on PATH (needed for AES without megacrypt)") from e
    if p.returncode:
        raise RuntimeError(p.stderr.decode("utf-8", "replace") or "openssl failed")
    return p.stdout


def aes_ecb_block(key: bytes, block: bytes) -> bytes:
    return openssl_aes("ecb", key, block[:16])[:16]


def encrypt_key(key_a32: list[int], data_a32: list[int]) -> list[int]:
    k = a32_to_bytes(key_a32)
    out: list[int] = []
    b = a32_to_bytes(data_a32)
    for i in range(0, len(b), 16):
        out.extend(bytes_to_a32(aes_ecb_block(k, b[i : i + 16])))
    return out


def aes_cbc_encrypt(key: bytes, data: bytes) -> bytes:
    return openssl_aes("cbc", key, data, b"\0" * 16)[: (len(data) + 15) & ~15]


def make_attr(name: str, key_a32: list[int], mtime: int | None = None, file_hash: str | None = None) -> str:
    ar: dict = {}
    if file_hash:
        ar["c"] = file_hash
    elif mtime is not None:
        ar["t"] = int(mtime)
    ar["n"] = name
    raw = b"MEGA" + json.dumps(ar, separators=(",", ":")).encode("utf-8")
    padded = raw + b"\0" * ((16 - len(raw) % 16) % 16)
    kk = key_a32
    aes_key = a32_to_bytes(
        [
            kk[0] ^ (kk[4] if len(kk) > 4 else 0),
            kk[1] ^ (kk[5] if len(kk) > 5 else 0),
            kk[2] ^ (kk[6] if len(kk) > 6 else 0),
            kk[3] ^ (kk[7] if len(kk) > 7 else 0),
        ]
    )
    return b64u_encode(aes_cbc_encrypt(aes_key, padded)[: len(padded)])


def encrypt_file(data: bytes, ul_key: list[int]) -> tuple[bytes, list[int]]:
    """AES-CTR + MEGA CBC-MAC in memory (small inputs / tests)."""
    stream = EncStream(io.BytesIO(data), len(data), ul_key)
    out = []
    while True:
        chunk = stream.read(1 << 20)
        if not chunk:
            break
        out.append(chunk)
    return b"".join(out), stream.filekey


MAC_FIRST = 0x20000
MAC_MAX = 0x100000
# MEGA chunk-MAC ramp: boundaries 128 KiB, 384 KiB, 768 KiB, ...; see mac_segment_ends.
MAC_RAMP = (0x20000, 0x60000, 0xC0000, 0x140000, 0x1E0000, 0x2A0000, 0x380000)
MAC_STEADY = 0x480000
# Encrypt/read chunk per file (--chunk-mib). Peak RSS grows with this, so keep it modest when
# uploading many large files in parallel or under a memory cap. Reads are assembled up to
# SOCK_CHUNK bytes, so a smaller encrypt chunk does not shrink socket writes.
CHUNK = 8 << 20
# Bytes handed to the socket per write. Large writes are what make the upload fast
# (8 KiB writes take about twice as long); this costs little memory of its own.
SOCK_CHUNK = 32 << 20


def mac_segment_ends(padded_len: int) -> list[int]:
    """MEGA chunk-MAC boundaries for zero-padded length (byte offsets).

    Boundaries are the fixed ramp then every MAC_MAX. This is O(segments), so it stays
    instant for multi-GiB files (a per-16-byte loop cost ~2.2 s per GiB).
    """
    ends = [pos for pos in MAC_RAMP if pos < padded_len]
    pos = MAC_STEADY
    while pos < padded_len:
        ends.append(pos)
        pos += MAC_MAX
    ends.append(padded_len)
    return ends


class EncStream:
    """Streaming MEGA file encryption: read() yields ciphertext, filekey at EOF.

    Reads, encrypts (one CTR call) and emits `chunk` bytes at a time; each MEGA chunk MAC
    segment (128 KiB .. 1 MiB) is still hashed separately, so `chunk` is free to change
    without affecting the wire format. Peak RSS grows by roughly 3x `chunk` per in-flight
    file (plaintext + ciphertext + the openssl child), transient and released after each chunk.
    """

    def __init__(self, f, size: int, ul_key: list[int], chunk: int = CHUNK):
        self._f = f
        self._ul = ul_key
        self.size = size
        self._chunk = max(16, chunk - chunk % 16)
        self._key = a32_to_bytes(ul_key[:4])
        self._nonce = a32_to_bytes(ul_key[4:6])
        self._iv = int.from_bytes(self._nonce + b"\0" * 8, "big")
        self._padded = (size + 15) & ~15
        self._ends = mac_segment_ends(self._padded)
        self._ei = 0
        self._seg = bytearray()
        self._off = 0
        self._buf = b""
        self._cond = [0, 0, 0, 0]
        self._done = False
        self.filekey: list[int] = []

    def _mac_segment(self, seg: bytes) -> None:
        mac = openssl_aes("cbc", self._key, seg, self._nonce + self._nonce)[-16:] if seg else self._nonce + self._nonce
        m = bytes_to_a32(mac)
        c = self._cond
        c[0] ^= m[0]
        c[1] ^= m[1]
        c[2] ^= m[2]
        c[3] ^= m[3]
        self._cond = bytes_to_a32(aes_ecb_block(self._key, a32_to_bytes(c)))

    def _feed_mac(self, data: bytes) -> None:
        i = 0
        while i < len(data):
            prev = self._ends[self._ei - 1] if self._ei else 0
            size = self._ends[self._ei] - prev
            take = min(len(data) - i, size - len(self._seg))
            self._seg += data[i : i + take]
            i += take
            if len(self._seg) == size:
                self._mac_segment(bytes(self._seg))
                self._seg = bytearray()
                self._ei += 1

    def _fill(self) -> None:
        start = self._off
        want = min(self._chunk, self._padded - start)
        raw = self._f.read(want) if want else b""
        buf = raw + b"\0" * (want - len(raw))
        keep = min(want, max(0, self.size - start))
        if buf:
            iv = (self._iv + (start >> 4)) % (1 << 128)
            self._buf = openssl_aes("ctr", self._key, buf, iv.to_bytes(16, "big"))[:keep]
        else:
            self._buf = b""
        self._feed_mac(buf)
        self._off = start + len(buf)

    def _finish(self) -> None:
        if self._done:
            return
        self._done = True
        if self._ei == 0 and self._ends == [0]:
            self._mac_segment(b"")  # zero-length file still contributes one MAC
            self._ei = 1
        if self._ei < len(self._ends):
            return
        c = self._cond
        ul = self._ul
        self.filekey = [
            _u32(x)
            for x in (
                ul[0] ^ ul[4],
                ul[1] ^ ul[5],
                ul[2] ^ c[0] ^ c[1],
                ul[3] ^ c[2] ^ c[3],
                ul[4],
                ul[5],
                c[0] ^ c[1],
                c[2] ^ c[3],
            )
        ]

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = 1 << 62
        out: list[bytes] = []
        while n > 0:
            if not self._buf:
                if self._off >= self._padded:
                    self._finish()
                    break
                self._fill()
                continue
            take = self._buf[:n]
            self._buf = self._buf[n:]
            out.append(take)
            n -= len(take)
        return b"".join(out)


def _backoff(i: int) -> None:
    time.sleep(min(8.0, 0.5 * (2**i)) + secrets.randbelow(250) / 1000.0)


def retryable(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRY_HTTP
    return isinstance(
        exc,
        (
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            http.client.IncompleteRead,
            http.client.RemoteDisconnected,
        ),
    )


def clear_error_frames(exc: BaseException) -> None:
    """Clear completed frames' locals while keeping exception types, chains and locations."""
    pending = [exc]
    seen = set()
    while pending:
        error = pending.pop()
        if id(error) in seen:
            continue
        seen.add(id(error))
        traceback.clear_frames(error.__traceback__)
        pending.extend(link for link in (error.__cause__, error.__context__) if link is not None)


def retry(fn, attempts: int = ATTEMPTS, sleep=_backoff, label: str = ""):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            clear_error_frames(e)
            last = e
            name = label or getattr(fn, "__name__", "call")
            if not retryable(e) or i + 1 == attempts:
                log(f"{name}: giving up after {i + 1} attempt(s): {type(e).__name__}: {e}")
                raise
            log(f"{name}: attempt {i + 1}/{attempts} failed ({type(e).__name__}: {e}); backing off")
            sleep(i)
    raise last  # pragma: no cover


def http_read(req: urllib.request.Request, timeout: int) -> bytes:
    with _OPENER.open(req, timeout=timeout) as resp:
        return resp.read()


class _ChunkHTTPSHandler(urllib.request.HTTPSHandler):
    """Hand the request body to the socket in SOCK_CHUNK-sized writes instead of 8 KiB."""

    def https_open(self, req):
        cls = functools.partial(http.client.HTTPSConnection, blocksize=SOCK_CHUNK)
        return self.do_open(cls, req, context=self._context)


_OPENER = urllib.request.build_opener(_ChunkHTTPSHandler())


def hashcash(token_b64: str, easiness: int) -> str:
    token = b64u_decode(token_b64)
    threshold = (((easiness & 63) << 1) + 1) << ((easiness >> 6) * 7 + 3)
    buf = bytearray(4 + 262144 * 48)
    for i in range(262144):
        buf[4 + i * 48 : 4 + i * 48 + len(token)] = token
    tries = 0
    t0 = time.monotonic()
    while True:
        digest = hashlib.sha256(buf).digest()
        if int.from_bytes(digest[:4], "big") <= threshold:
            log(f"hashcash solved: {tries} tries in {time.monotonic() - t0:.1f}s")
            return b64u_encode(bytes(buf[:4]))
        tries += 1
        if tries % 2048 == 0:
            log(f"hashcash working: {tries} tries, {time.monotonic() - t0:.1f}s")
            beat("hashcash", f"{tries} tries, {time.monotonic() - t0:.1f}s")
        j = 0
        while True:
            buf[j] = (buf[j] + 1) & 0xFF
            if buf[j]:
                break
            j += 1


class MegaAPI:
    def __init__(self):
        self.sid = ""
        self.seq = secrets.randbelow(10**8) + 10**7
        self.lang = "en"
        self._lock = threading.Lock()  # ponytail: global seq lock, per-host if it contends

    def _url(self, host: str, extra: str = "") -> str:
        with self._lock:
            seq = self.seq
            self.seq += 1
            sid = self.sid
        qs = f"id={seq}&v=3&lang={self.lang}&wcv={WCV}&domain=transferit"
        if sid:
            qs += f"&sid={sid}"
        if extra:
            qs += extra
        return f"{host}cs?{qs}"

    def req(self, payload, host: str = G_API, timeout: int = 60):
        action = payload.get("a", "?") if isinstance(payload, dict) else "?"
        body = json.dumps(payload if isinstance(payload, list) else [payload], separators=(",", ":")).encode()
        extra = "&bc=1" if host.startswith(BT7_API) else ""
        cash_hdr = None
        url = fetch_url = headers = None
        last = None
        for attempt in range(8):
            if cash_hdr is None:
                url = self._url(host, extra)
                fetch_url = url.split("?")[0] + "?"
            u = urlparse(url)
            headers = {
                "Content-Type": "text/plain;charset=UTF-8",
                "Origin": "https://transfer.it",
                "Referer": "https://transfer.it/",
                "User-Agent": UA,
                "MEGA-Chrome-Antileak": f"{u.path}?{u.query}" if u.query else u.path,
            }
            if cash_hdr:
                headers["X-Hashcash"] = cash_hdr
            req = urllib.request.Request(fetch_url, data=body, headers=headers, method="POST")
            t0 = time.monotonic()
            beat(f"api {action}", f"{action} -> {host.split('/')[2]} (attempt {attempt + 1})")
            try:
                data = json.loads(http_read(req, timeout))
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 402:
                    cash = e.headers.get("X-Hashcash")
                    if not cash:
                        log(f"api {action}: HTTP 402 without X-Hashcash header")
                        raise
                    parts = cash.split(":")
                    log(f"api {action}: HTTP 402, solving hashcash (easiness={parts[1]})")
                    cash_hdr = f"1:{parts[3]}:{hashcash(parts[3], int(parts[1]))}"
                    continue
                cash_hdr = None
                if retryable(e):
                    log(f"api {action}: HTTP {e.code} after {time.monotonic() - t0:.1f}s, retrying")
                    _backoff(attempt)
                    continue
                log(f"api {action}: HTTP {e.code} after {time.monotonic() - t0:.1f}s, giving up")
                raise
            except Exception as e:
                last = e
                cash_hdr = None
                if retryable(e):
                    log(f"api {action}: {type(e).__name__} after {time.monotonic() - t0:.1f}s, retrying")
                    _backoff(attempt)
                    continue
                log(f"api {action}: {type(e).__name__}: {e}")
                raise
            mega_err = None
            if isinstance(data, int):
                mega_err = data
            elif isinstance(data, list) and data and isinstance(data[0], int) and data[0] < 0:
                mega_err = data[0]
            if mega_err in RETRY_MEGA:
                cash_hdr = None
                last = RuntimeError(f"API error {mega_err}")
                log(f"api {action}: mega error {mega_err} after {time.monotonic() - t0:.1f}s, retrying")
                _backoff(attempt)
                continue
            log(f"api {action} ok in {time.monotonic() - t0:.2f}s")
            clear_beat(f"api {action}")
            return data
        raise RuntimeError(f"api {action} failed after 8 attempts: {last}")  # one owned retry budget

    def call(self, payload, host: str = G_API):
        res = self.req(payload, host)
        if isinstance(res, list) and len(res) == 1:
            res = res[0]
        if isinstance(res, int) and res < 0:
            raise RuntimeError(f"API error {res} for {payload}")
        return res


def create_ephemeral(api: MegaAPI) -> None:
    u_k = rand_a32(4)
    pw = rand_a32(4)
    ssc = rand_a32(4)
    k = a32_to_b64(encrypt_key(pw, u_k))
    ts = b64u_encode(a32_to_bytes(ssc) + a32_to_bytes(encrypt_key(u_k, ssc)))
    up = api.call({"a": "up", "k": k, "ts": ts})
    # up returns [0, "handle"] when batched as [[0, handle]] or handle string
    if isinstance(up, list):
        handle = up[1] if up and up[0] == 0 else up[0]
    else:
        handle = up
    us = api.call({"a": "us", "user": handle})
    tsid = us["tsid"]
    api.sid = tsid


def create_transfer(api: MegaAPI, name: str) -> tuple[str, str]:
    nkey = rand_a32(4)
    at = make_attr(name, nkey, mtime=int(time.time()))
    res = api.call({"a": "xn", "at": at, "k": a32_to_b64(nkey)}, host=BT7_API)
    # [0, [xh, h]]
    if isinstance(res, list) and res and res[0] == 0:
        xh, h = res[1]
    else:
        raise RuntimeError(f"xn failed: {res}")
    return check_root_handle(h), check_transfer_id(xh)


class ProgressBody:
    """File-like body wrapper that logs and heartbeats byte progress while streaming."""

    def __init__(self, inner, label: str, total: int, key: str, step: int = 8 << 20):
        self._inner = inner
        self._label = label
        self._key = key
        self._total = total
        self._step = step
        self._sent = 0
        self._next = step
        self._t_last = time.monotonic()
        self._s_last = 0

    def read(self, n: int = -1) -> bytes:
        data = self._inner.read(n)
        self._sent += len(data)
        now = time.monotonic()
        if self._sent and (self._sent >= self._next or now - self._t_last >= 5.0):
            self._next = self._sent + self._step
            rate = (self._sent - self._s_last) / max(1e-6, now - self._t_last)
            log(
                f"POST {self._label}: {self._sent >> 20}/{self._total >> 20} MiB "
                f"({rate / 1048576:.2f} MiB/s)"
            )
            beat(self._key, f"{self._label} {self._sent >> 20}/{self._total >> 20} MiB")
            self._t_last, self._s_last = now, self._sent
        return data


def make_cipher(path: Path, size: int, ul_key: list[int]):
    """Native encoder when the megacrypt extension is installed, else the openssl one."""
    if megacrypt is not None:
        return megacrypt.FileCipher(str(path), size, ul_key, CHUNK)
    return EncStream(path.open("rb"), size, ul_key, chunk=CHUNK)


def upload_bytes(api: MegaAPI, path: Path, name: str, parent: str) -> None:
    t_start = time.monotonic()
    ul_key = rand_a32(6)
    size = path.stat().st_size
    key = f"upload {name}"
    log(f"upload {name}: {size} bytes ({size / 1048576:.2f} MiB)")
    def put():
        beat(key, f"{name} opening + planning MAC segments")
        t_plan = time.monotonic()
        stream = make_cipher(path, size, ul_key)
        log(f"upload {name}: segment plan ready in {time.monotonic() - t_plan:.3f}s")
        body = ProgressBody(stream, name, size, key)
        t_u = time.monotonic()
        beat(key, f"{name} requesting upload URL")
        u = api.call({"a": "u", "s": size, "ssl": 1})
        url = u["p"] if isinstance(u, dict) else u
        host = urlparse(url).netloc
        log(f"upload {name}: got upload URL host={host} in {time.monotonic() - t_u:.2f}s")
        put_url = f"{url}/0-{size - 1}" if size else f"{url}/0--1"
        timeout = max(120, size // (256 * 1024))
        req = urllib.request.Request(
            put_url,
            data=body,
            headers={
                "User-Agent": UA,
                "Origin": "https://transfer.it",
                "Referer": "https://transfer.it/",
                "Content-Type": "text/plain;charset=UTF-8",
                "Content-Length": str(size),
            },
            method="POST",
        )
        log(f"POST {name}: sending {size} bytes to {host} "
            f"(socket timeout {timeout}s, encrypt chunk {CHUNK >> 20} MiB, socket write {SOCK_CHUNK >> 20} MiB)")
        beat(key, f"{name} POST 0/{size >> 20} MiB")
        t0 = time.monotonic()
        out = http_read(req, timeout)
        dt = time.monotonic() - t0
        rate = size / 1048576 / max(1e-6, dt)
        log(f"POST {name}: done in {dt:.1f}s ({rate:.2f} MiB/s), response {len(out)} bytes")
        return out, stream.filekey

    completion, filekey = retry(put, label=f"POST {name}")
    if not filekey:
        raise RuntimeError(f"incomplete upload stream for {name}")
    if len(completion) == 36 and completion.isascii() and all(c.isalnum() or c in "-_" for c in completion.decode()):
        h = completion.decode()
    else:
        h = b64u_encode(completion)
    at = make_attr(name, filekey)
    t_xp = time.monotonic()
    beat(key, f"{name} registering node (xp)")
    api.call(
        {
            "a": "xp",
            "v": 3,
            "t": parent,
            "n": [{"t": 0, "h": h, "a": at, "k": a32_to_b64(filekey)}],
        },
        host=BT7_API,
    )
    log(f"upload {name}: node registered in {time.monotonic() - t_xp:.2f}s")
    log(f"upload {name}: complete in {time.monotonic() - t_start:.1f}s")
    clear_beat(key)


def close_transfer(api: MegaAPI, xh: str) -> None:
    api.call({"a": "xc", "xh": xh}, host=BT7_API)


def create_folder(api: MegaAPI, name: str, parent: str) -> str:
    folder_key = rand_a32(4)
    at = make_attr(name, folder_key)
    h = b64u_encode(secrets.token_bytes(6))[:8]
    res = api.call(
        {
            "a": "xp",
            "v": 3,
            "t": parent,
            "n": [{"t": 1, "h": h, "a": at, "k": a32_to_b64(folder_key)}],
        },
        host=BT7_API,
    )
    nodes = res.get("f") if isinstance(res, dict) else None
    if not nodes:
        raise RuntimeError(f"xp folder failed: {res}")
    return check_root_handle(nodes[0].get("h"))


def skip_paths(state_path: Path) -> set[Path]:
    p = state_path.resolve()
    return {p, Path(str(p) + ".tmp")}


def iter_files(root: Path, skip: set[Path]) -> list[Path]:
    root = root.resolve()
    skip = {p.resolve() for p in skip}
    if root.is_file():
        return [] if root in skip else [root]
    if not root.is_dir():
        raise FileNotFoundError(root)
    out: list[Path] = []
    for dirpath, _dns, filenames in os.walk(root):
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.resolve() in skip or not p.is_file():
                continue
            out.append(p)
    return out


def rel_key(root: Path, p: Path) -> str:
    root, p = root.resolve(), p.resolve()
    if p == root and p.is_file():
        return p.name
    return p.relative_to(root).as_posix()


def parent_rel(rel: str) -> str:
    return "" if "/" not in rel else rel.rsplit("/", 1)[0]


def needed_dirs(file_rels: list[str]) -> list[str]:
    needed: set[str] = set()
    for rel in file_rels:
        acc: list[str] = []
        for part in rel.split("/")[:-1]:
            acc.append(part)
            needed.add("/".join(acc))
    return sorted(needed, key=lambda s: s.count("/"))


def split_jobs(total: int, parallel: int) -> int:
    """Workers to give each parallel unit so the product stays within `total`."""
    return max(1, total // max(1, parallel))


def collect_split(paths: list[Path], skip: set[Path]) -> list[tuple[str, Path, list[Path]]]:
    skip = {p.resolve() for p in skip}
    out: list[tuple[str, Path, list[Path]]] = []
    seen: set[Path] = set()
    for p in paths:
        p = p.resolve()
        if p.is_file():
            if p not in skip and p not in seen:
                seen.add(p)
                out.append(("file", p, [p]))
            continue
        if not p.is_dir():
            raise FileNotFoundError(p)
        for dirpath, _dns, filenames in os.walk(p):
            d = Path(dirpath)
            if d in seen:
                continue
            files = [d / fn for fn in filenames if (d / fn).is_file() and (d / fn).resolve() not in skip]
            if files:
                seen.add(d)
                out.append(("dir", d, files))
    return out


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class JobState:
    def __init__(self, path: Path, data: dict):
        self.path = path.resolve()
        self.data = data
        self._lock = threading.RLock()  # mutations and saves share one reentrant lock

    def lock(self) -> threading.RLock:
        return self._lock

    def save(self, api: MegaAPI | None = None) -> None:
        with self._lock:
            if api is not None:
                self.data["sid"] = api.sid
                self.data["seq"] = api.seq
            atomic_write(self.path, self.data)


XH_CHARS = set(string.ascii_letters + string.digits + "-_")
HANDLE_CHARS = XH_CHARS


def check_transfer_id(xh) -> str:
    if not isinstance(xh, str) or len(xh) != 12 or not set(xh) <= XH_CHARS:
        raise RuntimeError(f"bad transfer handle from the API: {xh!r}")
    return xh


def check_root_handle(h) -> str:
    if not isinstance(h, str) or len(h) != 8 or not set(h) <= HANDLE_CHARS:
        raise RuntimeError(f"bad root handle from the API: {h!r}")
    return h


def _check_handles(path: Path, where: str, xh, root_h, link) -> None:
    if xh:
        if not isinstance(xh, str) or len(xh) != 12 or not set(xh) <= XH_CHARS:
            raise ValueError(f"{path}: {where} transfer handle must be 12 base64url characters")
    if root_h and (not isinstance(root_h, str) or len(root_h) != 8 or not set(root_h) <= HANDLE_CHARS):
        raise ValueError(f"{path}: {where} root handle must be 8 base64url characters")
    if link is not None:
        if not xh:
            raise ValueError(f"{path}: {where} link without a transfer handle")
        if link != f"https://transfer.it/t/{xh}":
            raise ValueError(f"{path}: {where} link does not match its transfer handle")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_files(path: Path, records) -> None:
    if records is None:
        return
    if not isinstance(records, dict):
        raise ValueError(f"{path}: file records must be an object")
    for rel, meta in records.items():
        if not isinstance(meta, dict) or not _is_int(meta.get("size")) or not _is_int(meta.get("mtime")):
            raise ValueError(f"{path}: bad file record for {rel!r}")
        if "done" in meta and not isinstance(meta["done"], bool):
            raise ValueError(f"{path}: bad done flag for {rel!r}")


def load_state(path: Path) -> dict | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: state must be a JSON object")
    if data.get("mode") not in (None, "tree", "split"):
        raise ValueError(f"{path}: unknown mode {data.get('mode')!r}")
    for key in ("closed", "root", "xh", "root_h"):
        if key in data and not isinstance(data[key], bool if key == "closed" else str):
            raise ValueError(f"{path}: bad {key!r}")
    if bool(data.get("xh")) != bool(data.get("root_h")):
        raise ValueError(f"{path}: transfer handle is incomplete")
    if data.get("link") is not None and not isinstance(data["link"], str):
        raise ValueError(f"{path}: bad link")
    if data.get("closed") and not (data.get("link") and data.get("xh") and data.get("root_h")):
        raise ValueError(f"{path}: closed state needs a published link and a transfer handle")
    _check_handles(path, "state", data.get("xh"), data.get("root_h"), data.get("link"))
    _check_files(path, data.get("files"))
    if data.get("jobs") is not None and not isinstance(data.get("jobs"), dict):
        raise ValueError(f"{path}: jobs must be an object")
    for key, job in (data.get("jobs") or {}).items():
        if not isinstance(job, dict) or ("path" in job and not isinstance(job["path"], str)):
            raise ValueError(f"{path}: bad job record for {key!r}")
        for field in ("xh", "root_h"):
            if field in job and job[field] is not None and not isinstance(job[field], str):
                raise ValueError(f"{path}: bad {field} for job {key!r}")
        if bool(job.get("xh")) != bool(job.get("root_h")):
            raise ValueError(f"{path}: job record for {key!r} is incomplete")
        if "closed" in job and not isinstance(job["closed"], bool):
            raise ValueError(f"{path}: bad closed flag for job {key!r}")
        if job.get("link") is not None and not isinstance(job["link"], str):
            raise ValueError(f"{path}: bad job link for {key!r}")
        if job.get("closed"):
            if not (job.get("link") and job.get("xh")):
                raise ValueError(f"{path}: closed job for {key!r} needs a link and a transfer handle")
            if not job["link"].endswith(job["xh"]):
                raise ValueError(f"{path}: job link for {key!r} does not match its transfer handle")
        _check_handles(path, f"job {key!r}", job.get("xh"), job.get("root_h"), job.get("link"))
        _check_files(path, job.get("files"))
    if data.get("link") and data.get("xh") and not data["link"].endswith(data["xh"]):
        raise ValueError(f"{path}: link does not match the transfer handle")
    return data

def bind_api(state: dict) -> MegaAPI:
    api = MegaAPI()
    sid = state.get("sid") or ""
    if sid:
        api.sid = sid
        if state.get("seq") is not None:
            api.seq = int(state["seq"])
    else:
        create_ephemeral(api)
    return api


def file_meta(p: Path) -> dict:
    st = p.stat()
    return {"size": st.st_size, "mtime": int(st.st_mtime), "done": False}


def stale(meta: dict, p: Path) -> bool:
    st = p.stat()
    return (not meta.get("done")) or meta.get("size") != st.st_size or meta.get("mtime") != int(st.st_mtime)


def publish(api: MegaAPI, xh: str, ok: bool) -> str | None:
    if not ok:
        return None
    close_transfer(api, xh)
    return f"https://transfer.it/t/{xh}"


def ensure_folders(api: MegaAPI, folders: dict, file_rels: list[str], state: JobState) -> dict:
    for rel in needed_dirs(file_rels):
        if rel in folders:
            continue
        parent = folders[parent_rel(rel)]
        t0 = time.monotonic()
        k = f"folder {rel}"
        beat(k, f"creating folder {rel}")
        folders[rel] = create_folder(api, rel.split("/")[-1], parent)
        clear_beat(k)
        log(f"folder {rel} created in {time.monotonic() - t0:.2f}s")
        state.data["folders"] = folders
        state.save(api)
    return folders


def upload_pending(
    api: MegaAPI,
    items: list[tuple[str, Path, str]],
    files_meta: dict,
    state: JobState,
    jobs: int,
    bar: tqdm | None = None,
) -> list[BaseException]:
    pending = [(rel, path, parent) for rel, path, parent in items if stale(files_meta.get(rel) or {}, path)]
    errors: list[BaseException] = []
    lock = state.lock()  # serialises every state mutation and save
    own = False
    if not pending:
        return errors
    if bar is None:
        bar = tqdm(total=len(pending), unit="file", desc="upload", leave=True, disable=VERBOSE)
        own = True
    log(f"queue: {len(items)} file(s), {len(pending)} to upload, jobs={min(jobs, len(pending))}")

    def one(item):
        rel, path, parent = item
        t0 = time.monotonic()
        log(f"--> {rel}")
        beat(f"upload {path.name}", f"{rel} queued")
        try:
            upload_bytes(api, path, path.name, parent)
        except Exception as exc:
            clear_error_frames(exc)
            raise
        meta = file_meta(path)
        meta["done"] = True
        with lock:
            files_meta[rel] = meta
            state.save(api)
            bar.update(1)
            bar.set_postfix_str(rel, refresh=False)
        log(f"<-- {rel} ok in {time.monotonic() - t0:.1f}s (state saved)")

    try:
        workers = max(1, min(jobs, len(pending)))
        ex = ThreadPoolExecutor(max_workers=workers)
        futs = [ex.submit(one, it) for it in pending]
        try:
            for f in futs:
                try:
                    f.result()
                except Exception as e:
                    errors.append(e)
        except KeyboardInterrupt:
            ex.shutdown(wait=False, cancel_futures=True)
            os._exit(130)
        else:
            ex.shutdown(wait=True)
        return errors
    finally:
        if own and bar is not None:
            bar.close()


def run_tree(root: Path, state: JobState, jobs: int) -> str:
    root = root.resolve()
    d = state.data
    if d.get("closed") and d.get("link"):
        log(f"already closed, reusing {d['link']}")
        return d["link"]
    skip = skip_paths(state.path)
    files = iter_files(root, skip)
    if not files:
        raise RuntimeError("no files")
    rels = [rel_key(root, p) for p in files]
    log(f"mode=tree root={root} files={len(files)} (state={state.path.name})")
    api = bind_api(d)
    state.save(api)
    if not d.get("xh"):
        h, xh = create_transfer(api, root.name or "transfer")
        d["xh"], d["root_h"] = xh, h
        d["folders"] = {"": h}
        state.save(api)
        log(f"transfer created xh={xh}")
    else:
        log(f"resuming transfer xh={d['xh']}")
    folders = d.setdefault("folders", {"": d["root_h"]})
    folders[""] = d["root_h"]
    files_meta = d.setdefault("files", {})
    for rel, p in zip(rels, files):
        files_meta.setdefault(rel, file_meta(p))
    ensure_folders(api, folders, rels, state)
    items = [(rel, p, folders[parent_rel(rel)]) for rel, p in zip(rels, files)]
    errors = upload_pending(api, items, files_meta, state, jobs)
    if errors or any(stale(files_meta.get(rel) or {}, p) for rel, p in zip(rels, files)):
        state.save(api)
        raise RuntimeError(f"fail-closed: {errors[0] if errors else 'incomplete'}")
    log("all files uploaded; closing transfer (xc)")
    link = publish(api, d["xh"], True)
    d["closed"] = True
    d["link"] = link
    state.save(api)
    log(f"link {link}")
    return link


def run_split(paths: list[Path], state: JobState, jobs: int) -> tuple[list[tuple[Path, str]], list[tuple[Path, BaseException]]]:
    d = state.data
    skip = skip_paths(state.path)
    targets = collect_split(paths, skip)
    if not targets:
        raise RuntimeError("no files")
    api = bind_api(d)
    state.save(api)
    jobs_d: dict = d.setdefault("jobs", {})
    links: list[tuple[Path, str]] = []
    errors: list[tuple[Path, BaseException]] = []

    def one_target(item):
        kind, folder, files = item
        key = str(folder.resolve())
        with state.lock():
            job = jobs_d.setdefault(key, {"kind": kind, "path": key})
        if job.get("closed") and job.get("link"):
            log(f"{folder}: already closed, reusing {job['link']}")
            return folder, job["link"]
        if not job.get("xh"):
            h, xh = create_transfer(api, folder.name or "transfer")
            with state.lock():
                job.update({"xh": xh, "root_h": h, "files": job.get("files") or {}})
                state.save(api)
            log(f"{folder}: transfer created xh={xh}")
        else:
            log(f"{folder}: resuming transfer xh={job['xh']}")
        with state.lock():
            files_meta = job.setdefault("files", {})
        items = []
        for f in files:
            rel = f.name
            with state.lock():
                files_meta.setdefault(rel, file_meta(f))
            items.append((rel, f, job["root_h"]))
        err = upload_pending(api, items, files_meta, state, per_target, bar=bar)
        if err or any(stale(files_meta.get(f.name) or {}, f) for f in files):
            state.save(api)
            log(f"{folder}: fail-closed, no link generated")
            raise RuntimeError(err[0] if err else "incomplete")
        log(f"{folder}: all files uploaded; closing transfer (xc)")
        link = publish(api, job["xh"], True)
        with state.lock():
            job["closed"] = True
            job["link"] = link
            state.save(api)
        return folder, link

    n_pending = 0
    for _kind, _folder, files in targets:
        key = str(_folder.resolve())
        job = jobs_d.get(key) or {}
        if job.get("closed") and job.get("link"):
            continue
        meta = job.get("files") or {}
        n_pending += sum(1 for f in files if stale(meta.get(f.name) or {}, f))
    bar = tqdm(total=n_pending, unit="file", desc="upload", leave=True, disable=VERBOSE)
    workers = max(1, min(jobs, len(targets)))
    per_target = split_jobs(jobs, workers)
    log(f"mode=split targets={len(targets)} pending_files={n_pending} workers={workers} per_folder={per_target}")
    ex = ThreadPoolExecutor(max_workers=workers)
    futs = [ex.submit(one_target, t) for t in targets]
    try:
        try:
            for t, fut in zip(targets, futs):
                try:
                    links.append(fut.result())
                except Exception as e:
                    errors.append((t[1], e))
        except KeyboardInterrupt:
            ex.shutdown(wait=False, cancel_futures=True)
            os._exit(130)
        else:
            ex.shutdown(wait=True)
    finally:
        bar.close()
    return links, errors


def selfcheck() -> None:
    ul_key = [0x11111111, 0x22222222, 0x33333333, 0x44444444, 0x55555555, 0x66666666]
    data = b"hello transfer.it e2e\n"
    enc, filekey = encrypt_file(data, ul_key)
    expect_enc = bytes.fromhex("aba40842620a60071dd2ba25275b7e6fbd2adba1e250")
    expect_key = [1145324612, 1145324612, 825677689, 1756591280, 1431655765, 1717986918, 33940554, 754397428]
    assert enc == expect_enc, (enc.hex(), expect_enc.hex())
    assert filekey == expect_key, (filekey, expect_key)

    # streaming MAC boundaries must match the per-block MEGA reference
    def ref_ends(padded: int) -> list[int]:
        ends: list[int] = []
        pos = 0
        inc = MAC_FIRST
        nxt = MAC_FIRST
        for i in range(0, padded, 16):
            pos += 16
            if pos >= nxt and i + 16 < padded:
                ends.append(pos)
                if inc < MAC_MAX:
                    inc += MAC_FIRST
                nxt += inc
        ends.append(padded)
        return ends

    sizes = (0, 1, 16, 17, 100, MAC_FIRST - 16, MAC_FIRST, MAC_FIRST + 16, 0x60000, 0xC0000, 0x140000)
    sizes += (0x1E0000, 0x2A0000, 0x380000, 0x480000, 0x480000 + MAC_MAX * 3 + 8, 5 << 20)
    for size in sizes:
        padded = (size + 15) & ~15
        assert mac_segment_ends(padded) == ref_ends(padded), size

    # multi-GiB sizes: same ramp, then MAC_MAX steps, checked without looping over bytes
    huge = 3692512458
    ends = mac_segment_ends(huge)
    assert ends[:7] == list(MAC_RAMP) and ends[-1] == huge
    assert ends[-2] == MAC_STEADY + ((huge - 1 - MAC_STEADY) // MAC_MAX) * MAC_MAX
    assert ends[-2] + MAC_MAX > huge and all(b % 16 == 0 and b < huge for b in ends[:-1])
    assert all(ends[i + 1] - ends[i] == MAC_MAX for i in range(7, len(ends) - 2))
    assert len(ends) == 7 + (huge - MAC_STEADY + MAC_MAX - 1) // MAC_MAX + 1

    # the CBC batching must equal the per-block chain it replaces
    key, nonce = a32_to_bytes(ul_key[:4]), a32_to_bytes(ul_key[4:6])
    edge = bytes(range(96))
    mac = bytearray(nonce + nonce)
    for i in range(0, len(edge), 16):
        for j in range(16):
            mac[j] ^= edge[i + j]
        mac[:] = aes_ecb_block(key, bytes(mac))
    assert openssl_aes("cbc", key, edge, nonce + nonce)[-16:] == bytes(mac)

    # openssl CTR advances the full 128-bit counter, so iv+offset//16 is valid
    pt = bytes(range(48))
    assert openssl_aes("ctr", key, pt, b"\0" * 16) == (
        openssl_aes("ctr", key, pt[:16], b"\0" * 16)
        + openssl_aes("ctr", key, pt[16:32], (1).to_bytes(16, "big"))
        + openssl_aes("ctr", key, pt[32:], (2).to_bytes(16, "big"))
    )

    # read chunk size must not change the output (MAC segments are independent of it)
    tiny = bytes(range(256)) * 4
    for chunk in (16, 64, 4096):
        stream = EncStream(io.BytesIO(tiny), len(tiny), ul_key, chunk=chunk)
        got = b""
        while True:
            piece = stream.read(64)
            if not piece:
                break
            got += piece
        assert got == encrypt_file(tiny, ul_key)[0] and stream.filekey == encrypt_file(tiny, ul_key)[1], chunk

    # chunk boundaries that straddle a MAC segment boundary must still agree
    mid = bytes(range(251)) * 2000  # 502000 bytes, spans the 128 KiB and 384 KiB segments
    want_mid, want_mid_key = encrypt_file(mid, ul_key)
    for chunk in (0x30000, 0x50000, 1 << 20, CHUNK):
        stream = EncStream(io.BytesIO(mid), len(mid), ul_key, chunk=chunk)
        got = b""
        while True:
            piece = stream.read(1 << 16)
            if not piece:
                break
            got += piece
        assert got == want_mid and stream.filekey == want_mid_key, chunk

    # crossing one MAC boundary with the default chunk and with a bigger/oddly sized chunk
    big = bytes(range(256)) * ((MAC_FIRST + 4096) // 256 + 1)
    want_enc, want_key = encrypt_file(big, ul_key)
    assert len(want_enc) == len(big)
    for chunk in (MAC_FIRST, 1 << 20, CHUNK, CHUNK + 16):
        stream = EncStream(io.BytesIO(big), len(big), ul_key, chunk=chunk)
        got = b""
        while True:
            piece = stream.read(8192)
            if not piece:
                break
            got += piece
        assert got == want_enc and stream.filekey == want_key, chunk

    # zero-length file: empty ciphertext, one empty MAC segment
    empty = EncStream(io.BytesIO(b""), 0, ul_key)
    assert empty.read(8192) == b"" and empty.filekey == encrypt_file(b"", ul_key)[1]
    attr = make_attr("hello.txt", filekey)
    assert attr == "08LC56Sm9GTfh6m77TNrFpMpX1_OwzRv0smnwh0NOD0", attr
    k = [0x11111111, 0x22222222, 0x33333333, 0x44444444]
    enc0 = bytes_to_a32(aes_ecb_block(a32_to_bytes(k), b"\0" * 16))
    assert enc0 == [1248615789, 717595597, 4166813418, 2004225477], enc0
    key, pt = a32_to_bytes(k), b"0123456789abcdef" * 2
    if megacrypt is not None:
        native_ecb = megacrypt.aes_ecb(key, pt)
        native_cbc = megacrypt.aes_cbc(key, pt, b"\0" * 16)
        saved = megacrypt
        try:
            globals()["megacrypt"] = None
            ossl_ecb = openssl_aes("ecb", key, pt)
            ossl_cbc = openssl_aes("cbc", key, pt, b"\0" * 16)
        except RuntimeError:
            ossl_ecb = ossl_cbc = None
        finally:
            globals()["megacrypt"] = saved
        if ossl_ecb is not None:
            assert native_ecb == ossl_ecb and native_cbc == ossl_cbc
        assert openssl_aes("ecb", key, pt) == native_ecb
        assert openssl_aes("cbc", key, pt, b"\0" * 16) == native_cbc
    saved = megacrypt
    real_run = subprocess.run
    try:
        globals()["megacrypt"] = None

        def boom(*_a, **_k):
            raise FileNotFoundError(2, "No such file")

        subprocess.run = boom
        try:
            openssl_aes("ecb", key, b"\0" * 16)
            raise AssertionError("missing openssl did not raise")
        except RuntimeError as e:
            assert "openssl not found" in str(e), e
    finally:
        subprocess.run = real_run
        globals()["megacrypt"] = saved
    n = [0]

    def flaky():
        n[0] += 1
        if n[0] < 3:
            raise urllib.error.URLError("boom")
        return "ok"

    assert retry(flaky, sleep=lambda _i: None) == "ok" and n[0] == 3
    assert retryable(urllib.error.HTTPError("http://x", 503, "x", hdrs=None, fp=None))
    assert not retryable(urllib.error.HTTPError("http://x", 404, "x", hdrs=None, fp=None))
    assert not retryable(KeyboardInterrupt())

    # Failed workers release payloads even while the first future is still blocked.
    import weakref

    class Payload:
        pass

    refs = []
    released_before_collection = []
    release_first = threading.Event()
    real_upload = upload_bytes

    def connection_failure():
        payload = Payload()
        refs.append(weakref.ref(payload))
        raise ConnectionError("connection closed")

    def rejected(_api, _path, name, _parent):
        if name == "hold":
            assert release_first.wait(5), "failed workers did not run"
            return
        if name == "reject3":
            released_before_collection.append(all(ref() is None for ref in refs))
            release_first.set()
        payload = Payload()
        refs.append(weakref.ref(payload))
        try:
            connection_failure()
        except ConnectionError as exc:
            raise urllib.error.URLError(exc) from exc

    try:
        globals()["upload_bytes"] = rejected
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            items = []
            for name in ("hold", "reject1", "reject2", "reject3"):
                path = root / name
                path.write_bytes(b"test")
                items.append((name, path, "parent"))
            state = JobState(root / "state.json", {"files": {}})
            with tqdm(total=4, disable=True) as bar:
                errors = upload_pending(MegaAPI(), items, state.data["files"], state, 2, bar)
            assert released_before_collection == [True], "failed futures retained upload payloads"
            assert len(errors) == 3 and all(ref() is None for ref in refs)
            assert state.data["files"]["hold"]["done"]
            for error in errors:
                assert isinstance(error, urllib.error.URLError) and "connection closed" in str(error)
                assert isinstance(error.__cause__, ConnectionError)
                assert error.__traceback__ is not None and error.__cause__.__traceback__ is not None
    finally:
        release_first.set()
        globals()["upload_bytes"] = real_upload

    refs.clear()
    tries = [0]

    def retry_payload():
        assert all(ref() is None for ref in refs), "retry retained the previous payload"
        tries[0] += 1
        if tries[0] < 3:
            connection_failure()
        return "ok"

    assert retry(retry_payload, sleep=lambda _i: None) == "ok" and tries[0] == 3
    assert all(ref() is None for ref in refs)

    # Exercise upload_bytes itself: an attempt's closure must not keep its encoder alive.
    real_cipher, real_read = make_cipher, http_read
    refs.clear()

    class WatchedCipher:
        def __init__(self, inner):
            self.inner = inner

        def read(self, n):
            return self.inner.read(n)

        @property
        def filekey(self):
            return self.inner.filekey

    def watched_cipher(*args):
        cipher = WatchedCipher(real_cipher(*args))
        refs.append(weakref.ref(cipher))
        return cipher

    def rejected_response(req, _timeout):
        while req.data.read(SOCK_CHUNK):
            pass
        raise urllib.error.HTTPError(req.full_url, 400, "rejected", None, None)

    try:
        globals()["make_cipher"], globals()["http_read"] = watched_cipher, rejected_response
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            source.write_bytes(data)
            api = MegaAPI()
            api.call = lambda _payload, **_kw: {"p": "https://local.invalid/upload"}
            state = JobState(root / "state.json", {})
            with tqdm(total=1, disable=True) as bar:
                errors = upload_pending(api, [("source", source, "parent")], {}, state, 1, bar)
            assert len(errors) == 1 and isinstance(errors[0], urllib.error.HTTPError)
            assert refs and all(ref() is None for ref in refs), "failed attempt closure retained its encoder"
    finally:
        globals()["make_cipher"], globals()["http_read"] = real_cipher, real_read

    # the API layer owns one retry budget: exhaustion is not retryable again by callers
    calls = [0]
    real_read = http_read
    real_backoff = _backoff
    try:
        def always_down(*_a, **_kw):
            calls[0] += 1
            raise urllib.error.URLError("down")

        globals()["http_read"] = always_down
        globals()["_backoff"] = lambda _i: None
        try:
            MegaAPI().req({"a": "u", "s": 1, "ssl": 1})
            raise AssertionError("api failure did not raise")
        except RuntimeError as exc:
            assert calls[0] == 8, calls[0]
            assert not retryable(exc), exc
        try:
            retry(lambda: MegaAPI().req({"a": "u", "s": 1, "ssl": 1}), attempts=3, sleep=lambda _i: None)
            raise AssertionError("outer retry swallowed the api failure")
        except RuntimeError:
            pass
        assert calls[0] == 16, calls[0]
    finally:
        globals()["http_read"] = real_read
        globals()["_backoff"] = real_backoff

    # completion handle: 36-char base64url body must not be mistaken for a raw handle
    def handle_of(body: bytes) -> str:
        if len(body) == 36 and body.isascii() and all(c.isalnum() or c in "-_" for c in body.decode()):
            return body.decode()
        return b64u_encode(body)

    b64ish = b"SAwA3tB42le8RvkW6YZ0NcBS19MT0cE3-1EC"
    assert handle_of(b64ish) == b64ish.decode()
    raw = bytes(range(36))
    assert handle_of(raw) == b64u_encode(raw) != raw.decode("latin1")
    assert needed_dirs(["root.txt", "a/b/c.txt", "a/x.txt"]) == ["a", "a/b"]
    assert parent_rel("a/b/c.txt") == "a/b" and parent_rel("x.txt") == ""
    assert [split_jobs(4, n) for n in (1, 2, 4, 8)] == [4, 2, 1, 1] and split_jobs(1, 4) == 1
    assert publish(None, "x", False) is None  # type: ignore[arg-type]
    # native encoder, when installed, must agree with the openssl reference on sizes that
    # are not multiples of 16 and on files smaller than one MAC segment
    if megacrypt is not None:
        tmpdir = Path(tempfile.mkdtemp())
        try:
            cases = ((0, 1 << 20), (1, 4096), (6, 16), (17, 16), (100, 32), ((1 << 17) + 1, 4096))
            for size, chunk in cases:
                blob = bytes((i * 7) % 251 for i in range(size))
                p = tmpdir / f"s{size}.bin"
                p.write_bytes(blob)
                want_enc, want_key = encrypt_file(blob, ul_key)
                cipher = megacrypt.FileCipher(str(p), size, ul_key, chunk)
                got = bytearray()
                while True:
                    piece = cipher.read(4096)
                    if not piece:
                        break
                    got += piece
                assert bytes(got) == want_enc, (size, chunk)
                assert list(cipher.filekey or []) == want_key, (size, chunk)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    tmp = Path(tempfile.mkdtemp()) / "selfcheck-state.json"
    try:
        st = JobState(tmp, {"mode": "tree"})
        st.save()
        loaded = load_state(tmp)
        assert loaded and loaded["mode"] == "tree"
        sp = skip_paths(tmp)
        assert tmp.resolve() in sp and Path(str(tmp.resolve()) + ".tmp") in sp
        for bad in (
            {"mode": "nope"},
            {"mode": "split", "jobs": {"a": {"xh": "x"}}},
            {"mode": "tree", "files": {"a.txt": {"size": "big"}}},
            {"mode": "tree", "closed": True, "link": "arbitrary"},
            {"mode": "tree", "closed": "yes", "xh": "a" * 12, "root_h": "b" * 8, "link": "l"},
            {"mode": "tree", "files": {"a.txt": {"size": 1, "mtime": 0, "done": "false"}}},
            {"mode": "tree", "xh": "a" * 12},
            {"mode": "split", "jobs": {"a": {"closed": True, "link": "l"}}},
            {"mode": "split", "jobs": []},
            {"mode": "split", "jobs": {"a": {"closed": "yes", "link": "l", "xh": "x" * 12, "root_h": "y" * 8}}},
            {"mode": "split", "jobs": {"a": {"closed": True, "link": "https://evil.example/", "xh": "x" * 12, "root_h": "y" * 8}}},
            {"mode": "tree", "xh": [1], "root_h": [2]},
            {"mode": "tree", "closed": True, "link": "https://transfer.it/t/" + "b" * 12, "xh": "a" * 12, "root_h": "c" * 8},
            {"mode": "tree", "closed": True, "link": "javascript:x", "xh": "x", "root_h": "y"},
            {"mode": "tree", "closed": False, "link": "https://transfer.it/t/" + "a" * 12},
            {"mode": "split", "jobs": {"a": {"link": "https://transfer.it/t/" + "a" * 12}}},
            {"mode": "tree", "xh": "short", "root_h": "b" * 8},
            {"mode": "tree", "xh": "a" * 12, "root_h": "tiny"},
            {"mode": "tree", "closed": True, "link": "https://transfer.it/t/" + "a" * 12, "xh": "a" * 12, "root_h": "b" * 4},
        ):
            tmp.write_text(json.dumps(bad), encoding="utf-8")
            try:
                load_state(tmp)
                raise AssertionError(f"accepted bad state {bad}")
            except ValueError:
                pass
        ok = {
            "mode": "tree",
            "xh": "a" * 12,
            "root_h": "b" * 8,
            "closed": True,
            "link": "https://transfer.it/t/" + "a" * 12,
            "files": {"a.txt": {"size": 1, "mtime": 0, "done": True}},
        }
        tmp.write_text(json.dumps(ok), encoding="utf-8")
        assert load_state(tmp)["link"].endswith("a" * 12)
        bad_file = dict(ok, files={"a.txt": {"size": 1, "mtime": 0.5, "done": True}})
        tmp.write_text(json.dumps(bad_file), encoding="utf-8")
        try:
            load_state(tmp)
            raise AssertionError("accepted a fractional mtime")
        except ValueError:
            pass
        tmp.write_text(json.dumps({"mode": "split", "jobs": {"a": {"xh": "x" * 12, "root_h": "h" * 8}}}), encoding="utf-8")
        assert load_state(tmp)["jobs"]["a"]["root_h"] == "h" * 8
        closed_job = {
            "mode": "split",
            "jobs": {
                "a": {
                    "xh": "c" * 12,
                    "root_h": "d" * 8,
                    "closed": True,
                    "link": "https://transfer.it/t/" + "c" * 12,
                    "files": {"f.txt": {"size": 2, "mtime": 1, "done": True}},
                }
            },
        }
        tmp.write_text(json.dumps(closed_job), encoding="utf-8")
        assert load_state(tmp)["jobs"]["a"]["closed"] is True
    finally:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    try:
        api = MegaAPI()
        api.call = lambda payload, host=None: [0, ["\u00e9" * 12, "!" * 8]]
        create_transfer(api, "bad")
        raise AssertionError("malformed xn accepted")
    except RuntimeError:
        pass
    try:
        api.call = lambda payload, host=None: {"f": [{"h": "!"}]}
        create_folder(api, "bad", "parent")
        raise AssertionError("malformed folder handle accepted")
    except RuntimeError:
        pass
    print("selfcheck ok")


def relax_stream_errors() -> None:
    """Non-ASCII names must not crash printing on a narrow console encoding."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    relax_stream_errors()
    ap = argparse.ArgumentParser(description="Upload files/folders to transfer.it.")
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("-j", "--jobs", type=int, default=4, help="parallel file uploads (default 4)")
    ap.add_argument(
        "--mode",
        choices=("tree", "split"),
        default="tree",
        help="tree: one link, keep relative paths (default). split: one link per folder, direct files only",
    )
    ap.add_argument("--state", type=Path, default=Path(".transferit-upload.json"), help="resume json (never uploaded)")
    ap.add_argument("-v", "--verbose", action="store_true", help="timestamped phase log on stderr, with a stall watchdog")
    ap.add_argument(
        "--chunk-mib",
        type=int,
        default=8,
        help="streaming encrypt/read chunk per file (default 8; socket writes stay at 32 MiB)",
    )
    args = ap.parse_args(argv)
    global VERBOSE, CHUNK
    VERBOSE = args.verbose
    if args.chunk_mib < 1:
        ap.error("--chunk-mib must be >= 1")
    CHUNK = args.chunk_mib << 20
    if args.selfcheck:
        selfcheck()
        return 0
    install_fast_interrupt()
    if VERBOSE:
        threading.Thread(target=watchdog, daemon=True).start()
        log(f"verbose on; python={sys.version.split()[0]} platform={sys.platform}")
        log(f"encoder={'megacrypt ' + str(megacrypt.__file__) if megacrypt else 'openssl fallback'}")
    if not args.paths:
        ap.error("need paths or --selfcheck")
    if args.jobs < 1:
        ap.error("--jobs must be >= 1")
    state_path = args.state.resolve()
    try:
        prev = load_state(state_path)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if prev and prev.get("mode") not in (None, args.mode):
        print(f"error: state mode {prev.get('mode')!r} != {args.mode!r}", file=sys.stderr)
        return 1
    data = prev or {"mode": args.mode}
    data["mode"] = args.mode
    state = JobState(state_path, data)
    if args.mode == "tree":
        if len(args.paths) != 1:
            ap.error("tree mode needs exactly one path (use --mode split)")
        root = args.paths[0].resolve()
        if data.get("root") and Path(data["root"]) != root:
            print(f"error: state root {data['root']!r} != {str(root)!r}", file=sys.stderr)
            return 1
        data["root"] = str(root)
        try:
            link = run_tree(root, state, args.jobs)
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(link)
        return 0
    try:
        links, errors = run_split(args.paths, state, args.jobs)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for folder, link in links:
        print(f"{folder}: {link}")
    if links:
        print("---")
        for _folder, link in links:
            print(link)
    if errors:
        for path, err in errors:
            print(f"error: {path}: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        raise
