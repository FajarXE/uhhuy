# [GANTI FILE: bot/helpers/tidal/mqa_identifier.py]

import io
import struct
import wave
from pathlib import Path

try:
    from . import flac
except ImportError:
    import flac


def twos_complement(n, bits):
    mask = 2 ** (bits - 1)
    return -(n & mask) + (n & ~mask)


def iter_i24_as_i32(data):
    for l, h in struct.iter_unpack('<BH', data):
        yield twos_complement(h << 8 | l, 24) << 8


def iter_i16_as_i32(data):
    for x, in struct.iter_unpack('<h', data):
        yield x << 16


def peek(f, n):
    o = f.tell()
    r = f.read(n)
    f.seek(o)
    return r


def original_sample_rate_decoder(c: int) -> int:
    base = 48000 if (c & 1) == 1 else 44100
    multiplier = 1 << (((c >> 3) & 1) | (((c >> 2) & 1) << 1) | (((c >> 1) & 1) << 2))
    return base * multiplier


MAGIC = 51007556744


class MqaIdentifier:
    def __init__(self, flac_file_path: str | Path):
        self.is_mqa = False
        self.is_mqa_studio = False
        self.original_sample_rate = None
        self.bit_depth = 16

        try:
            self.detect(flac_file_path)
        except Exception:
            self.is_mqa = False

    def get_original_sample_rate(self) -> float | int:
        if not self.original_sample_rate:
            return 44.1
        sample_rate = self.original_sample_rate / 1000
        if sample_rate.is_integer():
            return int(sample_rate)
        return sample_rate

    def _decode_flac_samples(self, flac_file_path: str | Path) -> list:
        with open(str(flac_file_path), 'rb') as raw_f:
            magic = peek(raw_f, 4)

            if magic == b'fLaC':
                wav_buf = io.BytesIO()
                with flac.BitInputStream(raw_f) as bf:
                    try:
                        flac.decode_file(bf, wav_buf, seconds=1)
                    except EOFError:
                        pass
                wav_buf.seek(0)
                target_stream = wav_buf
            else:
                target_stream = raw_f

            with wave.open(target_stream) as wf:
                channel_count, sample_width, framerate, *_ = wf.getparams()

                if channel_count != 2:
                    return []

                if sample_width == 3:
                    iter_data = iter_i24_as_i32
                    self.bit_depth = 24
                elif sample_width == 2:
                    iter_data = iter_i16_as_i32
                else:
                    return []

                return list(iter_data(wf.readframes(framerate)))

    def detect(self, flac_file_path: str | Path) -> bool:
        samples = self._decode_flac_samples(flac_file_path)
        if not samples:
            return False

        channel_samples = list(zip(samples[::2], samples[1::2]))
        total_len = len(channel_samples)

        buffer = {16: 0, 17: 0, 18: 0}
        for i, sample in enumerate(channel_samples):
            buffer = {key: value | (sample[0] ^ sample[1]) >> key & 1 for key, value in buffer.items()}

            if MAGIC in buffer.values():
                if i + 34 >= total_len:
                    break

                self.is_mqa = True
                pos = [k for k, v in buffer.items() if v == MAGIC][0]

                org = 0
                for k in range(3, 7):
                    j = ((channel_samples[i + k][0]) ^ (channel_samples[i + k][1])) >> pos & 1
                    org |= j << (6 - k)

                self.original_sample_rate = original_sample_rate_decoder(org)

                provenance = 0
                for k in range(29, 34):
                    j = ((channel_samples[i + k][0]) ^ (channel_samples[i + k][1])) >> pos & 1
                    provenance |= j << (33 - k)

                self.is_mqa_studio = provenance > 8
                return True
            else:
                buffer = {key: (value << 1) & 0xFFFFFFFFF for key, value in buffer.items()}

        return False
