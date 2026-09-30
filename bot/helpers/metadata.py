# [GANTI FILE: bot/helpers/metadata.py]

import os
import aiohttp
import aiofiles
import base64
import hashlib
import asyncio
import tempfile
from datetime import datetime
from typing import Union, Dict

# Import Mutagen
from mutagen import File
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus
from mutagen.wave import WAVE
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover
from mutagen.mp3 import MP3, EasyMP3
from mutagen.id3 import TALB, TCOP, TDRC, TIT2, TPE1, TRCK, APIC, \
    TCON, TOPE, TSRC, USLT, TPOS, TXXX, \
    TCOM, TDRL, TLEN, TPE2, TPUB

from config import Config
from bot.logger import LOGGER

COVER_LOCKS = {}
_COVER_SESSIONS = {}

class SafeTempFile:
    def __init__(self, file_obj):
        self.file_obj = file_obj
    
    def __deepcopy__(self, memo):
        return self
        
    @property
    def name(self):
        return self.file_obj.name

try:
    from bot.helpers.lyrics.manager import lyrics_manager
except ImportError:
    lyrics_manager = None

def parse_duration_to_ms(raw):
    if not raw:
        return 0
    try:
        s = str(raw).strip()
        if ':' in s:
            parts = s.split(':')
            seconds = 0
            for part in parts:
                seconds = seconds * 60 + float(part)
            return int(seconds * 1000)
        
        val = float(s)
        if val < 30000: 
            return int(val * 1000)
        else:
            return int(val)
    except Exception:
        return 0

metadata = {
        'itemid': '', 'copyright': '', 'albumartist': '', 'cover': '', 'thumbnail': '',
        'artist': '', 'upc': '', 'album': '', 'isrc': '', 'title': '', 'duration': '',
        'explicit': '', "tracknumber": '', 'date': '', 'release_date': '', 'totaltracks': '',
        'quality': '', 'extension': '', 'lyrics': '', 'volume': '', 'totalvolume': '',
        'genre': '', 'subgenre': '', 'publisher': '', 'provider': '', 'tracks': [], 'albums': [],
        'composer': '', 'tempfolder': f'{Config.DOWNLOAD_BASE_DIR}/', 'filepath': '',
        'folderpath': '', 'poster_msg': None, 'type': ''
    }

async def get_track_metadata(track_id, track_data, user_id, cover=None, thumbnail=None, client=None):
    album_data = track_data.get('album', {})
    artist_data = track_data.get('artist', {})
    
    meta = metadata.copy()
    meta['itemid'] = str(track_id)
    meta['title'] = track_data.get('title', 'Unknown Title')
    meta['tracknumber'] = str(track_data.get('trackNumber', '1'))
    meta['totaltracks'] = str(track_data.get('volumeNumber', '1'))
    meta['volume'] = str(track_data.get('volumeNumber', '1'))
    meta['totalvolume'] = '1'
    meta['duration'] = track_data.get('duration', 0)
    meta['explicit'] = track_data.get('explicit', False)
    meta['copyright'] = track_data.get('copyright', '')
    meta['isrc'] = track_data.get('isrc', '')
    meta['upc'] = ''
    meta['provider'] = 'tidal'
    meta['type'] = 'track'
    
    if cover: meta['cover'] = cover
    elif album_data.get('cover'): meta['cover'] = f"https://resources.tidal.com/images/{album_data['cover'].replace('-', '/')}/1280x1280.jpg"
    
    if thumbnail: meta['thumbnail'] = thumbnail
    else: meta['thumbnail'] = meta['cover']

    meta['artist'] = artist_data.get('name', 'Unknown Artist')
    
    meta['album'] = album_data.get('title', 'Unknown Album')
    if 'artists' in track_data:
        meta['albumartist'] = track_data['artists'][0].get('name', meta['artist'])
    else:
        meta['albumartist'] = meta['artist']

    raw_date = track_data.get('streamStartDate', track_data.get('dateAdded', ''))
    if raw_date:
        try:
            date_obj = datetime.strptime(raw_date[:10], '%Y-%m-%d')
            meta['date'] = str(date_obj.year)
            meta['release_date'] = raw_date
        except:
            meta['date'] = ''

    if client:
        try:
            if 'id' in album_data:
                full_album = await client.get_album(album_data['id'])
                if 'genre' in full_album and 'name' in full_album['genre']: meta['genre'] = full_album['genre']['name']
                if 'upc' in full_album: meta['upc'] = full_album['upc']
                if 'numberOfTracks' in full_album: meta['totaltracks'] = str(full_album['numberOfTracks'])
                if 'numberOfVolumes' in full_album: meta['totalvolume'] = str(full_album['numberOfVolumes'])
                if 'releaseDate' in full_album:
                    meta['release_date'] = full_album['releaseDate']
                    meta['date'] = full_album['releaseDate'][:4]

            credits_data = await client.get_track_contributors(track_id)
            composers, producers = [], []
            
            if 'items' in credits_data:
                for item in credits_data['items']:
                    role = item.get('role', '').lower()
                    name = item.get('name', '')
                    if 'composer' in role: composers.append(name)
                    if 'producer' in role: producers.append(name)
            
            if composers: meta['composer'] = ', '.join(composers)
            if producers and not meta.get('publisher'): meta['publisher'] = ', '.join(producers)

        except Exception as e:
            LOGGER.warning(f"Metadata Enrichment Error (Track {track_id}): {e}")

    meta['cover'] = await create_cover_file(meta['cover'], meta)
    return meta

async def set_metadata(metadata:dict, user_id: int = None):
    audio_path = str(metadata['filepath'])
    true_codec = ""
    
    try:
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "a:0", 
            "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1", 
            audio_path
        ]
        import asyncio
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
        if process.returncode == 0:
            true_codec = stdout.decode().strip().lower()
    except Exception as e:
        LOGGER.warning(f"Gagal menjalankan ffprobe asinkron pada {audio_path}: {e}")

    def _load_audio_sync(path, codec):
        import os
        from mutagen import File, MutagenError
        from mutagen.wave import WAVE
        from mutagen.mp3 import MP3
        from mutagen.flac import FLAC
        from mutagen.oggvorbis import OggVorbis
        from mutagen.oggopus import OggOpus
        from mutagen.mp4 import MP4
        
        h = None
        try:
            if codec in ['aac', 'alac', 'mp4']: h = MP4(path)
            elif codec == 'flac': h = FLAC(path)
            elif codec == 'mp3': h = MP3(path)
            elif codec == 'vorbis': h = OggVorbis(path)
            elif codec == 'opus': h = OggOpus(path)
            elif 'pcm' in codec: h = WAVE(path)
            else:
                ext = os.path.splitext(path)[1].lower().strip()
                if ext == '.flac': h = FLAC(path)
                elif ext in ['.m4a', '.mp4', '.m4b']: h = MP4(path)
                elif ext == '.mp3': h = MP3(path)
                elif ext == '.ogg': h = OggVorbis(path)
                elif ext == '.opus': h = OggOpus(path)
                elif ext == '.wav': h = WAVE(path)
                else: h = File(path) 
        except MutagenError:
            LOGGER.exception(f"MutagenError: File rusak, korup, atau header invalid pada {path}")
        except Exception:
            LOGGER.exception(f"Format Audio Tidak Valid pada {path}")
        return h

    handle = None
    try:
        import asyncio
        handle = await asyncio.to_thread(_load_audio_sync, audio_path, true_codec)
    except Exception:
        LOGGER.exception(f"Gagal membuka file {audio_path}:")
        return

    if handle is None:
         LOGGER.error(f"File tidak dikenali formatnya: {audio_path}")
         return
    
    current_dur = metadata.get('duration', 0)
    if not current_dur:
        try:
            if hasattr(handle, 'info') and hasattr(handle.info, 'length'):
                current_dur = handle.info.length 
        except Exception: pass

    dur_ms = parse_duration_to_ms(current_dur)
    metadata['duration'] = int(dur_ms / 1000)

    if lyrics_manager and user_id:
        from bot.settings import bot_set
        user_settings = bot_set.user_data.get(user_id) or bot_set.user_data.get(str(user_id)) or {}
        embed_lyrics = user_settings.get('lyrics_status', False)
        send_file_lyrics = user_settings.get('send_lyrics_file', False)
        
        if embed_lyrics or send_file_lyrics:
            try:
                original_status = user_settings.get('lyrics_status')
                user_settings['lyrics_status'] = True 
                
                lyrics_text = await lyrics_manager.fetch_lyrics(metadata, user_id)
                
                if original_status is not None: user_settings['lyrics_status'] = original_status
                else: user_settings['lyrics_status'] = False

                if lyrics_text: 
                    if embed_lyrics: metadata['lyrics'] = lyrics_text
                    else: metadata['lyrics'] = ""
                        
                    if send_file_lyrics:
                        ext = ".lrc" if "[00:" in lyrics_text else ".txt"
                        base_path = os.path.splitext(audio_path)[0]
                        lyrics_file_path = f"{base_path}{ext}"
                        try:
                            with open(lyrics_file_path, 'w', encoding='utf-8') as lf:
                                lf.write(lyrics_text)
                        except Exception as e:
                            LOGGER.exception("Gagal menulis file lirik fisik:")
            except Exception as e:
                LOGGER.exception("Error fetching lyrics:")

    try:
        if isinstance(handle, (OggVorbis, OggOpus)): await set_vorbis(metadata, handle, dur_ms)
        elif isinstance(handle, FLAC): await set_flac(metadata, handle, dur_ms)
        elif isinstance(handle, MP4): await set_m4a(metadata, handle)
        elif isinstance(handle, WAVE): await set_wav(metadata, handle, dur_ms)
        elif isinstance(handle, (MP3, EasyMP3)): await set_mp3(metadata, handle, dur_ms)
        else:
            ext = os.path.splitext(audio_path)[1].lower()
            if ext in ['.m4a', '.mp4']: await set_m4a(metadata, handle)
            elif ext in ['.ogg', '.opus']: await set_vorbis(metadata, handle, dur_ms)
            else: await set_mp3(metadata, handle, dur_ms)  
    except Exception as e:
        handle_type = type(handle).__name__ if handle else "Unknown/Corrupt"
        LOGGER.exception(f"Gagal menulis metadata audio pada file {audio_path} (Tipe Handle: {handle_type}):")


async def set_flac(data: Dict, handle: FLAC, dur_ms: int = 0):
    if handle.tags is None: handle.add_tags()
    
    handle.tags['TITLE'] = data['title']
    handle.tags['ALBUM'] = data['album']
    handle.tags['ALBUMARTIST'] = data['albumartist']
    handle.tags['ARTIST'] = data['artist']
    
    cpr = data.get('copyright') or ''
    if cpr:
        handle.tags['COPYRIGHT'] = cpr
        handle.tags['cpr'] = cpr 
        
    pub = data.get('publisher') or data.get('organization') or ''
    if pub:
        handle.tags['PUBLISHER'] = pub
        handle.tags['ORGANIZATION'] = pub
        handle.tags['LABEL'] = pub
        handle.tags['pub'] = pub

    t_num = str(data.get('tracknumber') or '1')
    t_tot = str(data.get('totaltracks') or '1')
    d_num = str(data.get('volume') or '1')
    d_tot = str(data.get('totalvolume') or '1')

    handle.tags['TRACKNUMBER'] = t_num
    handle.tags['TRACKTOTAL'] = t_tot
    handle.tags['TOTALTRACKS'] = t_tot 
    handle.tags['DISCNUMBER'] = d_num
    handle.tags['DISCTOTAL'] = d_tot
    handle.tags['TOTALDISCS'] = d_tot 

    if data.get('upc'):
        handle.tags['UPC'] = data['upc']
        handle.tags['BARCODE'] = data['upc']
        handle.tags['EAN'] = data['upc']

    if data.get('isrc'): handle.tags['ISRC'] = data['isrc']

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    if data.get('date'): 
        handle.tags['DATE'] = data['date']
        handle.tags['YEAR'] = data['date']
    
    if data.get('release_date'): 
        handle.tags['RELEASETIME'] = data['release_date']
        handle.tags['ORIGINALDATE'] = data['release_date']

    handle.tags['TAGGING_TIME'] = now_str
    handle.tags['DATE_TAGGED'] = now_str
    handle.tags['ENCODED_DATE'] = now_str 

    if data.get('explicit') is True:
        handle.tags['ITUNESADVISORY'] = '1'
        handle.tags['RATING'] = 'Explicit'
    elif data.get('explicit') is False:
        handle.tags['ITUNESADVISORY'] = '2'
        handle.tags['RATING'] = 'Clean'

    if data.get('genre'): handle.tags['GENRE'] = data['genre']
    if data.get('subgenre'): handle.tags['SUBGENRE'] = data['subgenre']
    if data.get('composer'): handle.tags['COMPOSER'] = data['composer']
    if data.get('lyrics'): handle.tags['LYRICS'] = data['lyrics']
    
    if data.get('bit_depth'): handle.tags['BPS'] = str(data['bit_depth'])
    if data.get('sample_rate'): handle.tags['SAMPLERATE'] = str(int(data['sample_rate'] * 1000))
    
    if data.get('mqa_details'):
        mqa_file = data['mqa_details']
        mqa_str = f'MQAEncode v1.1, 2.4.0+0, {now_str}'
        handle.tags['ENCODER'] = mqa_str
        handle.tags['MQAENCODER'] = mqa_str
        handle.tags['ORIGINALSAMPLERATE'] = str(mqa_file.original_sample_rate)
    
    await savePic(handle, data)
    import asyncio
    await asyncio.to_thread(handle.save)
    return True


async def set_m4a(data: Dict, handle: MP4):
    if handle.tags is None: handle.add_tags()
    
    handle.tags['\u00a9nam'] = data['title']
    handle.tags['\u00a9alb'] = data['album']
    handle.tags['\u00a9ART'] = data['artist']
    handle.tags['aART'] = data['albumartist']
    
    cpr = data.get('copyright') or ''
    if cpr:
        handle.tags['\u00a9cpr'] = cpr 
        handle.tags['----:com.apple.iTunes:cpr'] = cpr.encode('utf-8')
        handle.tags['----:com.apple.iTunes:COPYRIGHT'] = cpr.encode('utf-8')

    pub = data.get('publisher') or data.get('label') or data.get('organization') or ''
    if pub:
        handle.tags['\u00a9pub'] = pub 
        handle.tags['----:com.apple.iTunes:PUBLISHER'] = str(pub).encode('utf-8')
        handle.tags['----:com.apple.iTunes:LABEL'] = str(pub).encode('utf-8')
        handle.tags['----:com.apple.iTunes:pub'] = str(pub).encode('utf-8')

    if data.get('producer'): handle.tags['----:com.apple.iTunes:PRODUCER'] = str(data['producer']).encode('utf-8')
    if data.get('genre'): handle.tags['\u00a9gen'] = data['genre']
    if data.get('composer'): handle.tags['\u00a9wrt'] = data['composer']

    def safe_int(x):
        try: return int(x)
        except: return 0

    t_num = safe_int(data.get('tracknumber'))
    t_tot = safe_int(data.get('totaltracks'))
    d_num = safe_int(data.get('volume'))
    d_tot = safe_int(data.get('totalvolume'))

    if t_tot == 0 and t_num > 0: t_tot = t_num 
    if d_tot == 0 and d_num > 0: d_tot = d_num

    handle.tags['trkn'] = [(t_num, t_tot)]
    handle.tags['disk'] = [(d_num, d_tot)]
    
    if data.get('upc'):
        val = str(data['upc']).encode('utf-8')
        handle.tags['----:com.apple.iTunes:UPC'] = val
        handle.tags['----:com.apple.iTunes:BARCODE'] = val
        handle.tags['----:com.apple.iTunes:EAN'] = val

    if data.get('isrc'): handle.tags['----:com.apple.iTunes:ISRC'] = str(data['isrc']).encode('utf-8')

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    if data.get('date'): handle.tags['\u00a9day'] = data['date']
    if data.get('release_date'): handle.tags['----:com.apple.iTunes:RELEASETIME'] = data.get('release_date').encode('utf-8')

    handle.tags['\u00a9too'] = f"Encoded on {now_str}" 
    handle.tags['----:com.apple.iTunes:TAGGING_TIME'] = now_str.encode('utf-8')
    handle.tags['----:com.apple.iTunes:ENCODED_DATE'] = now_str.encode('utf-8')

    if data.get('explicit') is True: handle.tags['rtng'] = [1] 
    elif data.get('explicit') is False: handle.tags['rtng'] = [2]
    else: handle.tags['rtng'] = [0]

    if data.get('subgenre'): handle.tags['----:com.apple.iTunes:SUBGENRE'] = data.get('subgenre').encode('utf-8')
    if data.get('lyrics'): handle.tags['\u00a9lyr'] = data['lyrics']

    if data.get('bit_depth'): handle.tags['----:com.apple.iTunes:BITS PER SAMPLE'] = str(data['bit_depth']).encode('utf-8')
    if data.get('sample_rate'): handle.tags['----:com.apple.iTunes:SAMPLERATE'] = str(int(data['sample_rate'] * 1000)).encode('utf-8')
    
    await savePic(handle, data)
    import asyncio
    await asyncio.to_thread(handle.save)
    return True


async def set_mp3(data: Dict, handle: Union[MP3, EasyMP3], dur_ms: int = 0):
    if handle.tags is None: handle.add_tags()
    
    t_num = str(data.get('tracknumber', ''))
    t_tot = str(data.get('totaltracks', ''))
    track_pos = f"{t_num}/{t_tot}" if (t_tot and t_tot != '0') else t_num
        
    d_num = str(data.get('volume') or '')
    d_tot = str(data.get('totalvolume') or '')
    disc_pos = f"{d_num}/{d_tot}" if (d_tot and d_tot != '0') else d_num
    
    handle.tags.add(TIT2(encoding=3, text=data['title']))
    handle.tags.add(TALB(encoding=3, text=data['album']))
    handle.tags.add(TPE2(encoding=3, text=data['albumartist']))
    handle.tags.add(TOPE(encoding=3, text=data['albumartist'])) 
    handle.tags.add(TPE1(encoding=3, text=data['artist']))
    handle.tags.add(TCOP(encoding=3, text=data['copyright']))
    
    pub = data.get('publisher') or data.get('label') or data.get('organization') or ''
    if pub:
        handle.tags.add(TPUB(encoding=3, text=pub))
        handle.tags.add(TXXX(encoding=3, desc='LABEL', text=pub))

    handle.tags.add(TRCK(encoding=3, text=track_pos)) 
    if disc_pos: handle.tags.add(TPOS(encoding=3, text=disc_pos)) 
    
    if data.get('genre'): handle.tags.add(TCON(encoding=3, text=data['genre'])) 
    if data.get('date'): handle.tags.add(TDRC(encoding=3, text=data['date']))
    if data.get('release_date'): handle.tags.add(TDRL(encoding=3, text=data['release_date']))
    if data.get('subgenre'): handle.tags.add(TXXX(encoding=3, desc='SUBGENRE', text=data['subgenre']))
    
    if data.get('producer'): handle.tags.add(TXXX(encoding=3, desc='PRODUCER', text=data['producer']))
    handle.tags.add(TSRC(encoding=3, text=data['isrc']))
    
    if data.get('upc'):
        handle.tags.add(TXXX(encoding=3, desc='UPC', text=data['upc']))
        handle.tags.add(TXXX(encoding=3, desc='BARCODE', text=data['upc']))
        handle.tags.add(TXXX(encoding=3, desc='EAN', text=data['upc']))

    if data.get('lyrics'): handle.tags.add(USLT(encoding=3, lang=u'eng', desc=u'desc', text=data['lyrics']))
    if data.get('composer'): handle.tags.add(TCOM(encoding=3, text=data['composer'])) 
    
    if dur_ms > 0: handle.tags.add(TLEN(encoding=3, text=str(dur_ms)))
    if data.get('bit_depth'): handle.tags.add(TXXX(encoding=3, desc='BPS', text=str(data['bit_depth'])))
    if data.get('sample_rate'): handle.tags.add(TXXX(encoding=3, desc='SAMPLERATE', text=str(int(data['sample_rate'] * 1000))))
    
    await savePic(handle, data)
    import asyncio
    await asyncio.to_thread(handle.save)
    return True


async def set_wav(data: Dict, handle: WAVE, dur_ms: int = 0):
    if not isinstance(handle, WAVE):
        try: handle = WAVE(data['filepath'])
        except Exception: 
            LOGGER.exception("Mutagen gagal membaca objek WAVE:")
            return

    if handle.tags is None:
        try: handle.add_tags()
        except Exception: 
            LOGGER.exception("Mutagen gagal menambahkan TAGS ke file WAVE:")
            return
    
    tags = handle.tags
    t_num = str(data.get('tracknumber', ''))
    t_tot = str(data.get('totaltracks', ''))
    track_pos = f"{t_num}/{t_tot}" if (t_tot and t_tot != '0') else t_num
    
    d_num = str(data.get('volume') or '')
    d_tot = str(data.get('totalvolume') or '')
    disc_pos = f"{d_num}/{d_tot}" if (d_tot and d_tot != '0') else d_num

    tags.add(TIT2(encoding=3, text=data['title']))
    tags.add(TALB(encoding=3, text=data['album']))
    tags.add(TPE2(encoding=3, text=data['albumartist']))
    tags.add(TPE1(encoding=3, text=data['artist']))
    tags.add(TCOP(encoding=3, text=data['copyright']))
    tags.add(TRCK(encoding=3, text=track_pos)) 
    
    pub = data.get('publisher') or ''
    if pub: tags.add(TPUB(encoding=3, text=pub))

    if disc_pos: tags.add(TPOS(encoding=3, text=disc_pos)) 
    if data.get('genre'): tags.add(TCON(encoding=3, text=data['genre'])) 
    if data.get('date'): tags.add(TDRC(encoding=3, text=data['date']))
    if data.get('release_date'): tags.add(TDRL(encoding=3, text=data['release_date']))
    
    tags.add(TSRC(encoding=3, text=data['isrc']))
    if data.get('lyrics'): tags.add(USLT(encoding=3, lang=u'eng', desc=u'desc', text=data['lyrics']))
    
    await savePic(handle, data)
    import asyncio
    await asyncio.to_thread(handle.save)
    return True


async def set_vorbis(data: Dict, handle: Union[OggVorbis, OggOpus], dur_ms: int = 0):
    if handle.tags is None:
        try: handle.add_tags()
        except: pass
    
    handle.tags['TITLE'] = data.get('title', '')
    handle.tags['ALBUM'] = data.get('album', '')
    handle.tags['ALBUMARTIST'] = data.get('albumartist', '')
    handle.tags['ARTIST'] = data.get('artist', '')
    
    if data.get('composer'): handle.tags['COMPOSER'] = data['composer']
    if data.get('lyrics'): handle.tags['LYRICS'] = data['lyrics']
    
    cpr = data.get('copyright') or ''
    if cpr: handle.tags['COPYRIGHT'] = cpr
        
    pub = data.get('publisher') or data.get('organization') or ''
    if pub: 
        handle.tags['PUBLISHER'] = pub
        handle.tags['ORGANIZATION'] = pub 
        handle.tags['LABEL'] = pub

    t_num = str(data.get('tracknumber') or '1')
    t_tot = str(data.get('totaltracks') or '1')
    d_num = str(data.get('discnumber') or data.get('volume') or '1')
    d_tot = str(data.get('totalvolumes') or data.get('totalvolume') or '1')

    handle.tags['TRACKNUMBER'] = t_num
    handle.tags['TRACKTOTAL'] = t_tot
    handle.tags['TOTALTRACKS'] = t_tot
    handle.tags['DISCNUMBER'] = d_num
    handle.tags['DISCTOTAL'] = d_tot
    handle.tags['TOTALDISCS'] = d_tot

    if data.get('upc'): 
        handle.tags['UPC'] = data['upc']
        handle.tags['BARCODE'] = data['upc']
        handle.tags['EAN'] = data['upc']

    if data.get('isrc'): handle.tags['ISRC'] = data['isrc']

    if data.get('date'): 
        handle.tags['DATE'] = data['date']
        handle.tags['YEAR'] = data['date']

    if data.get('release_date'): handle.tags['ORIGINALDATE'] = data['release_date']
    
    if data.get('explicit') is True:
        handle.tags['ITUNESADVISORY'] = '1'
        handle.tags['RATING'] = 'Explicit'
    elif data.get('explicit') is False:
        handle.tags['ITUNESADVISORY'] = '2'
        handle.tags['RATING'] = 'Clean'

    if data.get('genre'): handle.tags['GENRE'] = data['genre']
    
    await savePic(handle, data)
    import asyncio
    await asyncio.to_thread(handle.save)
    return True


async def savePic(handle, metadata):
    album_art = metadata.get('cover')
    if album_art and album_art.startswith('http'):
        album_art = await create_cover_file(album_art, metadata, thumbnail=False)
        metadata['cover'] = album_art 

    if not album_art or album_art == './project-siesta.png' or not os.path.exists(album_art): return

    try:
        import aiofiles
        async with aiofiles.open(album_art, "rb") as f:
            data = await f.read()
    except Exception as e:
        LOGGER.exception(f"Error membaca file cover art {album_art}:")
        return
    
    if isinstance(handle, FLAC):
        pic = Picture()
        pic.data = data
        pic.mime = u"image/jpeg"
        handle.clear_pictures()
        handle.add_picture(pic)

    elif isinstance(handle, (OggVorbis, OggOpus)): 
        try:
            def _encode_ogg_pic(img_data):
                pic = Picture()
                pic.data = img_data
                pic.mime = u"image/jpeg"
                pic.type = 3
                pic.desc = u"Cover"
                pic_data = pic.write()
                return base64.b64encode(pic_data).decode("ascii")

            import asyncio
            encoded_data = await asyncio.to_thread(_encode_ogg_pic, data)
            handle["METADATA_BLOCK_PICTURE"] = [encoded_data]
        except Exception as e:
            LOGGER.exception("Gagal set cover art OGG:")

    elif isinstance(handle, MP4):
        pic = MP4Cover(data, imageformat=MP4Cover.FORMAT_JPEG)
        handle.tags['covr'] = [pic]

    elif isinstance(handle, (MP3, EasyMP3, WAVE)) or hasattr(handle, 'tags'):
        try:
            handle.tags.delall("APIC")
            handle.tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc=u'Cover', data=data))
        except Exception:
            LOGGER.exception("Gagal memasang cover art ID3 ke file (Kemungkinan korupsi struktur ID3):")
            
async def get_audio_extension(path):
    try:
        import asyncio
        handle = await asyncio.to_thread(File, path)
        if handle is None:
             ext = os.path.splitext(path)[1].lower()
             return ext.replace('.', '')
        if isinstance(handle, MP4): return 'm4a'
        if isinstance(handle, FLAC): return 'flac'
        if isinstance(handle, WAVE): return 'wav'
        return 'mp3'
    except:
        return 'mp3'

async def get_cover_session(used_proxy=None):
    global _COVER_SESSIONS
    if used_proxy not in _COVER_SESSIONS or _COVER_SESSIONS[used_proxy].closed:
        from bot.helpers.proxy_manager import proxy_manager
        connector = proxy_manager.get_aiohttp_connector(used_proxy)
        if not connector: connector = aiohttp.TCPConnector(keepalive_timeout=30, enable_cleanup_closed=True)
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        _COVER_SESSIONS[used_proxy] = aiohttp.ClientSession(headers=headers, connector=connector)
    return _COVER_SESSIONS[used_proxy]

async def _download_cover_with_headers(url: str, destination: str, proxy: str = None):
    if not url: return
    if url.startswith("//"): url = "https:" + url
        
    from bot.helpers.proxy_manager import proxy_manager
    used_proxy = await proxy_manager.get_proxy(proxy)
    client_proxy = used_proxy if used_proxy and not used_proxy.startswith('socks') else None

    try:
        dir_path = os.path.dirname(destination)
        os.makedirs(dir_path, exist_ok=True)
        session = await get_cover_session(used_proxy)
        get_kwargs = {}
        if client_proxy: get_kwargs['proxy'] = client_proxy
            
        async with session.get(url, timeout=30, **get_kwargs) as resp:
            if resp.status == 200:
                import aiofiles
                async with aiofiles.open(destination, 'wb') as f:
                    await f.write(await resp.read())
                if used_proxy: await proxy_manager.report_success(used_proxy)
            else:
                if used_proxy: await proxy_manager.report_fail(used_proxy)
                LOGGER.error(f"Gagal download cover: HTTP {resp.status} | URL: {url}")
    except Exception as e:
        if used_proxy: await proxy_manager.report_fail(used_proxy)
        LOGGER.exception(f"Gagal download cover | URL: {url}")

async def create_cover_file(url: str, meta: dict, thumbnail=False, proxy: str = None): 
    if not url: return './project-siesta.png'
    if url.startswith("//"): url = "https:" + url

    if 'cover_temp_obj' in meta and os.path.exists(meta['cover_temp_obj'].name):
        return meta['cover_temp_obj'].name

    temp_dir = meta.get('tempfolder', '.')
    os.makedirs(temp_dir, exist_ok=True)
    temp_file = tempfile.NamedTemporaryFile(dir=temp_dir, suffix='.jpg', delete=True)
    cover_path = temp_file.name
    meta['cover_temp_obj'] = SafeTempFile(temp_file)

    lock = COVER_LOCKS.get(url)
    if lock is None:
        lock = asyncio.Lock()
        COVER_LOCKS[url] = lock

    try:
        async with lock:
            await _download_cover_with_headers(url, cover_path, proxy=proxy)
    finally:
        if url in COVER_LOCKS:
            COVER_LOCKS.pop(url, None)
    
    if os.path.exists(cover_path) and os.path.getsize(cover_path) > 0:
        return cover_path
    return './project-siesta.png'

async def close_all_cover_sessions():
    global _COVER_SESSIONS
    closed_count = 0
    for proxy, session in list(_COVER_SESSIONS.items()):
        if session and not session.closed:
            await session.close()
            closed_count += 1
    _COVER_SESSIONS.clear()
    if closed_count > 0:
        LOGGER.info(f"Metadata: Berhasil menutup {closed_count} sesi HTTP Cover Art.")
