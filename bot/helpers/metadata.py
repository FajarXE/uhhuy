# [GANTI FILE: bot/helpers/metadata.py]

import os
import aiohttp
import aiofiles
import base64
import hashlib
from datetime import datetime

# Import Mutagen
from mutagen import File
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover
from mutagen.mp3 import MP3, EasyMP3
from mutagen.id3 import TALB, TCOP, TDRC, TIT2, TPE1, TRCK, APIC, \
    TCON, TOPE, TSRC, USLT, TPOS, TXXX, \
    TCOM, TDRL, TLEN, TPE2, TPUB

from config import Config
from bot.logger import LOGGER

try:
    from bot.helpers.lyrics.manager import lyrics_manager
except ImportError:
    lyrics_manager = None

# --- FUNGSI HELPER: PARSE DURASI ---
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
# ----------------------------------------

# Struktur Metadata Default
metadata = {
        'itemid': '',
        'copyright': '',
        'albumartist': '',
        'cover': '',
        'thumbnail': '',
        'artist': '',
        'upc': '',
        'album': '',
        'isrc': '',
        'title': '',
        'duration': '',
        'explicit': '',
        "tracknumber": '',
        'date': '',
        'release_date': '', 
        'totaltracks': '',
        'quality': '',
        'extension': '',
        'lyrics': '',
        'volume': '',
        'totalvolume': '',
        'genre': '',
        'subgenre': '', 
        'publisher': '',
        'provider': '',
        'tracks': [],
        'albums': [],
        'composer': '', 
        'tempfolder': f'{Config.DOWNLOAD_BASE_DIR}/',
        'filepath': '',
        'folderpath': '',
        'poster_msg': None,
        'type': ''
    }


# --- TAMBAHAN BARU: FUNGSI PENGAMBIL DATA UTAMA (Genre & Composer Fix) ---
async def get_track_metadata(track_id, track_data, user_id, cover=None, thumbnail=None, client=None):
    """
    Mengolah data mentah dari Tidal menjadi dictionary metadata standar.
    Mengambil Genre dari Album dan Composer dari Contributors.
    """
    
    # 1. Setup Dasar
    album_data = track_data.get('album', {})
    artist_data = track_data.get('artist', {})
    
    meta = metadata.copy() # Copy template default
    meta['itemid'] = str(track_id)
    meta['title'] = track_data.get('title', 'Unknown Title')
    meta['tracknumber'] = str(track_data.get('trackNumber', '1'))
    meta['totaltracks'] = str(track_data.get('volumeNumber', '1')) # Default sementara
    meta['volume'] = str(track_data.get('volumeNumber', '1'))
    meta['totalvolume'] = '1'
    meta['duration'] = track_data.get('duration', 0)
    meta['explicit'] = track_data.get('explicit', False)
    meta['copyright'] = track_data.get('copyright', '')
    meta['isrc'] = track_data.get('isrc', '')
    meta['upc'] = '' # Biasanya ada di album
    meta['provider'] = 'tidal'
    meta['type'] = 'track'
    
    # URL Cover
    if cover:
        meta['cover'] = cover
    elif album_data.get('cover'):
        meta['cover'] = f"https://resources.tidal.com/images/{album_data['cover'].replace('-', '/')}/1280x1280.jpg"
    
    if thumbnail:
        meta['thumbnail'] = thumbnail
    else:
        meta['thumbnail'] = meta['cover']

    # Artis
    meta['artist'] = artist_data.get('name', 'Unknown Artist')
    
    # Album & Album Artist
    meta['album'] = album_data.get('title', 'Unknown Album')
    # Coba ambil album artist dari list artists jika ada
    if 'artists' in track_data:
        meta['albumartist'] = track_data['artists'][0].get('name', meta['artist'])
    else:
        meta['albumartist'] = meta['artist']

    # Tanggal (Stream Start Date atau Release Date)
    raw_date = track_data.get('streamStartDate', track_data.get('dateAdded', ''))
    if raw_date:
        try:
            date_obj = datetime.strptime(raw_date[:10], '%Y-%m-%d')
            meta['date'] = str(date_obj.year)
            meta['release_date'] = raw_date
        except:
            meta['date'] = ''

    # --- LOGIKA TAMBAHAN (GENRE & COMPOSER) ---
    if client:
        try:
            # A. AMBIL DATA ALBUM LENGKAP (Untuk GENRE, UPC, TOTAL TRACKS)
            if 'id' in album_data:
                full_album = await client.get_album(album_data['id'])
                
                # Genre
                if 'genre' in full_album and 'name' in full_album['genre']:
                    meta['genre'] = full_album['genre']['name']
                
                # UPC
                if 'upc' in full_album:
                    meta['upc'] = full_album['upc']
                
                # Total Tracks (Akurasi)
                if 'numberOfTracks' in full_album:
                    meta['totaltracks'] = str(full_album['numberOfTracks'])
                if 'numberOfVolumes' in full_album:
                    meta['totalvolume'] = str(full_album['numberOfVolumes'])
                
                # Release Date yang lebih akurat
                if 'releaseDate' in full_album:
                    meta['release_date'] = full_album['releaseDate']
                    meta['date'] = full_album['releaseDate'][:4]

            # B. AMBIL CONTRIBUTORS (Untuk COMPOSER)
            credits_data = await client.get_track_contributors(track_id)
            composers = []
            producers = []
            
            if 'items' in credits_data:
                for item in credits_data['items']:
                    role = item.get('role', '').lower()
                    name = item.get('name', '')
                    
                    if 'composer' in role:
                        composers.append(name)
                    if 'producer' in role:
                        producers.append(name)
            
            # Gabungkan nama dengan koma
            if composers:
                meta['composer'] = ', '.join(composers)
            
            # Opsional: Masukkan Producer ke tag Publisher atau Organization jika kosong
            if producers and not meta.get('publisher'):
                meta['publisher'] = ', '.join(producers)

        except Exception as e:
            LOGGER.warning(f"Metadata Enrichment Error (Track {track_id}): {e}")

    # Download Cover ke Temp
    meta['cover'] = await create_cover_file(meta['cover'], meta)
    
    return meta
# ------------------------------------------------------------------------


async def set_metadata(metadata:dict, user_id: int = None):
    audio_path = str(metadata['filepath'])
    
    # --- 1. INISIALISASI MUTAGEN ---
    handle = None
    try:
        # Deteksi otomatis
        handle = File(audio_path)
        
        # Fallback manual jika gagal
        if handle is None:
            ext = os.path.splitext(audio_path)[1].lower().strip()
            if '.wav' in ext: handle = WAVE(audio_path)
            elif '.mp3' in ext: handle = MP3(audio_path)
            elif '.flac' in ext: handle = FLAC(audio_path)
            elif '.ogg' in ext: handle = OggVorbis(audio_path)
            elif ext in ['.m4a', '.mp4', '.m4b']: handle = MP4(audio_path)
                
    except Exception as e:
        LOGGER.error(f"Gagal membuka file {audio_path}: {e}")
        return

    if handle is None:
         LOGGER.error(f"File tidak dikenali formatnya: {audio_path}")
         return
    
    # --- 2. PERBAIKAN DATA DURASI ---
    current_dur = metadata.get('duration', 0)
    if not current_dur:
        try:
            if hasattr(handle, 'info') and hasattr(handle.info, 'length'):
                current_dur = handle.info.length 
        except: pass

    dur_ms = parse_duration_to_ms(current_dur)
    metadata['duration'] = int(dur_ms / 1000)

    # Ambil Lirik (Opsional)
    if lyrics_manager and user_id:
        try:
            lyrics_text = await lyrics_manager.fetch_lyrics(metadata, user_id)
            if lyrics_text: metadata['lyrics'] = lyrics_text
        except Exception as e:
            LOGGER.error(f"Error fetching lyrics: {e}")

    # --- 3. ROUTING KE HANDLER SPESIFIK ---
    try:
        if isinstance(handle, OggVorbis):
            await set_vorbis(metadata, handle, dur_ms)
        elif isinstance(handle, FLAC):
            await set_flac(metadata, handle, dur_ms)
        elif isinstance(handle, MP4): 
            await set_m4a(metadata, handle)
        elif isinstance(handle, WAVE):
            await set_wav(metadata, handle, dur_ms)
        elif isinstance(handle, (MP3, EasyMP3)):
            await set_mp3(metadata, handle, dur_ms)
        else:
            # Fallback terakhir berdasarkan ekstensi
            ext = os.path.splitext(audio_path)[1].lower()
            if ext in ['.m4a', '.mp4']:
                 await set_m4a(metadata, handle)
            else:
                await set_mp3(metadata, handle, dur_ms) 
    except Exception as e:
        LOGGER.error(f"Gagal menulis metadata: {e}")
        import traceback
        traceback.print_exc()


# ==========================================
# HANDLER FLAC (VORBIS COMMENT)
# ==========================================
async def set_flac(data, handle, dur_ms=0):
    if handle.tags is None:
            handle.add_tags()
    
    # --- Standard Basic Tags ---
    handle.tags['TITLE'] = data['title']
    handle.tags['ALBUM'] = data['album']
    handle.tags['ALBUMARTIST'] = data['albumartist']
    handle.tags['ARTIST'] = data['artist']
    
    # --- COPYRIGHT (cpr) ---
    cpr = data.get('copyright') or ''
    if cpr:
        handle.tags['COPYRIGHT'] = cpr
        handle.tags['cpr'] = cpr # Alias khusus MediaInfo
        
    # --- PUBLISHER (pub) ---
    pub = data.get('publisher') or data.get('organization') or ''
    if pub:
        handle.tags['PUBLISHER'] = pub
        handle.tags['ORGANIZATION'] = pub
        handle.tags['LABEL'] = pub
        handle.tags['pub'] = pub # Alias khusus MediaInfo

    # --- TRACKS & DISCS (Part/Total) ---
    # Mengisi semua variasi agar MediaInfo menampilkan format "N/T"
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

    # --- UPC ---
    if data.get('upc'):
        handle.tags['UPC'] = data['upc']
        handle.tags['BARCODE'] = data['upc']
        handle.tags['EAN'] = data['upc']

    # --- ISRC ---
    if data.get('isrc'):
        handle.tags['ISRC'] = data['isrc']

    # --- DATES (Encoded, Tagged) ---
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    if data.get('date'): 
        handle.tags['DATE'] = data['date'] # Year
        handle.tags['YEAR'] = data['date']
    
    if data.get('release_date'): 
        handle.tags['RELEASETIME'] = data['release_date']
        handle.tags['ORIGINALDATE'] = data['release_date']

    handle.tags['TAGGING_TIME'] = now_str
    handle.tags['DATE_TAGGED'] = now_str
    handle.tags['ENCODED_DATE'] = now_str 

    # --- RATING ---
    if data.get('explicit') is True:
        handle.tags['ITUNESADVISORY'] = '1'
        handle.tags['RATING'] = 'Explicit'
    elif data.get('explicit') is False:
        handle.tags['ITUNESADVISORY'] = '2'
        handle.tags['RATING'] = 'Clean'

    # --- MISC ---
    if data.get('genre'): handle.tags['GENRE'] = data['genre']
    if data.get('subgenre'): handle.tags['SUBGENRE'] = data['subgenre']
    if data.get('composer'): handle.tags['COMPOSER'] = data['composer']
    if data.get('lyrics'): handle.tags['LYRICS'] = data['lyrics']
    
    if data.get('bit_depth'):
        handle.tags['BPS'] = str(data['bit_depth'])
    if data.get('sample_rate'):
        handle.tags['SAMPLERATE'] = str(int(data['sample_rate'] * 1000))
    
    # MQA Specifics
    if data.get('mqa_details'):
        mqa_file = data['mqa_details']
        mqa_str = f'MQAEncode v1.1, 2.4.0+0, {now_str}'
        handle.tags['ENCODER'] = mqa_str
        handle.tags['MQAENCODER'] = mqa_str
        handle.tags['ORIGINALSAMPLERATE'] = str(mqa_file.original_sample_rate)
    
    await savePic(handle, data)
    handle.save()
    return True


# ==========================================
# HANDLER M4A (ITUNES ATOMS)
# ==========================================
async def set_m4a(data, handle):
    if handle.tags is None:
        handle.add_tags()
    
    # --- Standard Atoms ---
    handle.tags['\u00a9nam'] = data['title']
    handle.tags['\u00a9alb'] = data['album']
    handle.tags['\u00a9ART'] = data['artist']
    handle.tags['aART'] = data['albumartist']
    
    # --- COPYRIGHT (cpr) ---
    cpr = data.get('copyright') or ''
    if cpr:
        handle.tags['\u00a9cpr'] = cpr
        # Custom atom fallback
        handle.tags['----:com.apple.iTunes:cpr'] = cpr.encode('utf-8')

    # --- PUBLISHER (pub) ---
    pub = data.get('publisher') or data.get('organization') or ''
    if pub:
        handle.tags['\u00a9pub'] = pub # Standard Atom Publisher
        handle.tags['----:com.apple.iTunes:PUBLISHER'] = str(pub).encode('utf-8')
        handle.tags['----:com.apple.iTunes:LABEL'] = str(pub).encode('utf-8')
        handle.tags['----:com.apple.iTunes:pub'] = str(pub).encode('utf-8') # Alias

    # --- GENRE & COMPOSER ---
    if data.get('genre'): 
        handle.tags['\u00a9gen'] = data['genre']
    if data.get('composer'): 
        handle.tags['\u00a9wrt'] = data['composer']

    # --- TRACKS & DISCS (Part/Total) ---
    def safe_int(x):
        try: return int(x)
        except: return 0

    t_num = safe_int(data.get('tracknumber'))
    t_tot = safe_int(data.get('totaltracks'))
    d_num = safe_int(data.get('volume'))
    d_tot = safe_int(data.get('totalvolume'))

    # Hack: Jika total 0 tapi number > 0, set total=number agar MediaInfo menampilkan "1/1"
    if t_tot == 0 and t_num > 0: t_tot = t_num 
    if d_tot == 0 and d_num > 0: d_tot = d_num

    # Penulisan Tuple (Wajib Integer)
    handle.tags['trkn'] = [(t_num, t_tot)]
    handle.tags['disk'] = [(d_num, d_tot)]
    
    # --- UPC ---
    if data.get('upc'):
        handle.tags['----:com.apple.iTunes:UPC'] = str(data['upc']).encode('utf-8')
        handle.tags['----:com.apple.iTunes:BARCODE'] = str(data['upc']).encode('utf-8')

    # --- ISRC ---
    if data.get('isrc'):
         handle.tags['----:com.apple.iTunes:ISRC'] = str(data['isrc']).encode('utf-8')

    # --- DATES ---
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    if data.get('date'): 
        handle.tags['\u00a9day'] = data['date'] # Year
    
    if data.get('release_date'):
        handle.tags['----:com.apple.iTunes:RELEASETIME'] = data.get('release_date').encode('utf-8')

    # Encoded & Tagged Date (Custom Atoms)
    handle.tags['\u00a9too'] = f"Encoded on {now_str}" 
    handle.tags['----:com.apple.iTunes:TAGGING_TIME'] = now_str.encode('utf-8')
    handle.tags['----:com.apple.iTunes:ENCODED_DATE'] = now_str.encode('utf-8')

    # --- RATING ---
    # Atom 'rtng': 0=None, 1=Explicit, 2=Clean
    if data.get('explicit') is True:
        handle.tags['rtng'] = [1] 
    elif data.get('explicit') is False:
        handle.tags['rtng'] = [2]
    else:
        handle.tags['rtng'] = [0]

    # --- MISC ---
    if data.get('subgenre'): handle.tags['----:com.apple.iTunes:SUBGENRE'] = data.get('subgenre').encode('utf-8')
    if data.get('lyrics'): handle.tags['\u00a9lyr'] = data['lyrics']

    if data.get('bit_depth'):
        handle.tags['----:com.apple.iTunes:BITS PER SAMPLE'] = str(data['bit_depth']).encode('utf-8')
    if data.get('sample_rate'):
        handle.tags['----:com.apple.iTunes:SAMPLERATE'] = str(int(data['sample_rate'] * 1000)).encode('utf-8')
    
    await savePic(handle, data)
    handle.save()
    return True


# ==========================================
# HANDLER MP3 (ID3)
# ==========================================
async def set_mp3(data, handle, dur_ms=0):
    if handle.tags is None:
            handle.add_tags()
    
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
    
    pub = data.get('publisher') or data.get('organization') or ''
    if pub:
        handle.tags.add(TPUB(encoding=3, text=pub))

    handle.tags.add(TRCK(encoding=3, text=track_pos)) 
    if disc_pos: 
        handle.tags.add(TPOS(encoding=3, text=disc_pos)) 
    
    if data.get('genre'): handle.tags.add(TCON(encoding=3, text=data['genre'])) 
    if data.get('date'): handle.tags.add(TDRC(encoding=3, text=data['date']))
    if data.get('release_date'): handle.tags.add(TDRL(encoding=3, text=data['release_date']))
    if data.get('subgenre'): handle.tags.add(TXXX(encoding=3, desc='SUBGENRE', text=data['subgenre']))
    
    handle.tags.add(TSRC(encoding=3, text=data['isrc']))
    if data.get('lyrics'):
        handle.tags.add(USLT(encoding=3, lang=u'eng', desc=u'desc', text=data['lyrics']))
    if data.get('composer'): 
        handle.tags.add(TCOM(encoding=3, text=data['composer'])) 
    
    if dur_ms > 0:
         handle.tags.add(TLEN(encoding=3, text=str(dur_ms)))

    if data.get('bit_depth'):
        handle.tags.add(TXXX(encoding=3, desc='BPS', text=str(data['bit_depth'])))
    if data.get('sample_rate'):
        handle.tags.add(TXXX(encoding=3, desc='SAMPLERATE', text=str(int(data['sample_rate'] * 1000))))
    
    await savePic(handle, data)
    handle.save()
    return True


# ==========================================
# HANDLER WAV
# ==========================================
async def set_wav(data, handle, dur_ms=0):
    if not isinstance(handle, WAVE):
        try: handle = WAVE(data['filepath'])
        except Exception: pass 

    if handle.tags is None:
        try: handle.add_tags()
        except Exception: return
    
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
    if data.get('lyrics'):
        tags.add(USLT(encoding=3, lang=u'eng', desc=u'desc', text=data['lyrics']))
    
    await savePic(handle, data)
    handle.save()
    return True


# ==========================================
# HANDLER OGG VORBIS (BARU - KHUSUS SPOTIFY)
# ==========================================
async def set_vorbis(data, handle, dur_ms=0):
    """Handler khusus untuk file OGG (Spotify)"""
    if handle.tags is None:
        try: handle.add_tags()
        except: pass
    
    # Vorbis Comments menggunakan Key-Value list, mirip FLAC
    # Kita bisa reuse logika field yang mirip dengan FLAC
    
    handle.tags['TITLE'] = data['title']
    handle.tags['ALBUM'] = data['album']
    handle.tags['ALBUMARTIST'] = data['albumartist']
    handle.tags['ARTIST'] = data['artist']
    
    cpr = data.get('copyright') or ''
    if cpr: handle.tags['COPYRIGHT'] = cpr
        
    pub = data.get('publisher') or data.get('organization') or ''
    if pub: handle.tags['PUBLISHER'] = pub

    # Tracks & Discs
    handle.tags['TRACKNUMBER'] = str(data.get('tracknumber') or '1')
    handle.tags['TRACKTOTAL'] = str(data.get('totaltracks') or '1')
    handle.tags['DISCNUMBER'] = str(data.get('volume') or '1')
    handle.tags['DISCTOTAL'] = str(data.get('totalvolume') or '1')

    # Codes
    if data.get('upc'): handle.tags['UPC'] = data['upc']
    if data.get('isrc'): handle.tags['ISRC'] = data['isrc']

    # Dates
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if data.get('date'): handle.tags['DATE'] = data['date']
    if data.get('release_date'): handle.tags['ORIGINALDATE'] = data['release_date']
    
    # Misc
    if data.get('genre'): handle.tags['GENRE'] = data['genre']
    if data.get('composer'): handle.tags['COMPOSER'] = data['composer']
    if data.get('lyrics'): handle.tags['LYRICS'] = data['lyrics']
    
    # Cover Art untuk OGG sama dengan FLAC (menggunakan Picture block)
    await savePic(handle, data)
    handle.save()
    return True


# ==========================================
# HELPER UTILS
# ==========================================
async def savePic(handle, metadata):
    # Ambil path cover dari metadata
    album_art = metadata.get('cover')
    
    # [LOGIKA PENGAMAN]: Jika cover masih berupa URL (http...), download dulu!
    # Ini mencegah error "No such file or directory" jika handler lupa mendownload gambar.
    if album_art and album_art.startswith('http'):
        # Kita panggil create_cover_file untuk mengubah URL -> File Lokal
        # Pastikan fungsi create_cover_file sudah didefinisikan di file ini
        album_art = await create_cover_file(album_art, metadata, thumbnail=False)
        metadata['cover'] = album_art # Update variable

    # Validasi: Pastikan sekarang file gambar benar-benar ada di disk
    if not album_art or album_art == './project-siesta.png' or not os.path.exists(album_art):
        return

    try:
        with open(album_art, "rb") as f:
            data = f.read()
    except Exception as e:
        LOGGER.error(f"Error membaca file cover art: {e}")
        return
    
    # --- 1. Handler FLAC ---
    if isinstance(handle, FLAC):
        pic = Picture()
        pic.data = data
        pic.mime = u"image/jpeg"
        handle.clear_pictures()
        handle.add_picture(pic)

    # --- 2. Handler OGG VORBIS (Spotify) ---
    elif isinstance(handle, OggVorbis): 
        try:
            pic = Picture()
            pic.data = data
            pic.mime = u"image/jpeg"
            pic.type = 3 # 3 = Front Cover
            pic.desc = u"Cover"
            
            # Encode gambar ke Base64 (Standard OGG Vorbis Comment)
            # Wajib import base64 di paling atas file!
            pic_data = pic.write()
            encoded_data = base64.b64encode(pic_data).decode("ascii")
            handle["METADATA_BLOCK_PICTURE"] = [encoded_data]
        except Exception as e:
            LOGGER.error(f"Gagal set cover art OGG: {e}")

    # --- 3. Handler MP4 (M4A) ---
    elif isinstance(handle, MP4):
        pic = MP4Cover(data, imageformat=MP4Cover.FORMAT_JPEG)
        handle.tags['covr'] = [pic]

    # --- 4. Handler MP3 / WAVE (ID3) ---
    elif isinstance(handle, (MP3, EasyMP3, WAVE)) or hasattr(handle, 'tags'):
        try:
            handle.tags.delall("APIC")
            handle.tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc=u'Cover', data=data))
        except Exception:
            pass

async def get_audio_extension(path):
    try:
        handle = File(path)
        if handle is None:
             ext = os.path.splitext(path)[1].lower()
             return ext.replace('.', '')
        if isinstance(handle, MP4): return 'm4a'
        if isinstance(handle, FLAC): return 'flac'
        if isinstance(handle, WAVE): return 'wav'
        return 'mp3'
    except:
        return 'mp3'

async def _download_cover_with_headers(url: str, destination: str):
    if not url: return
    
    # User-Agent browser agar tidak diblokir server gambar
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        # Pastikan folder tujuan benar-benar ada
        dir_path = os.path.dirname(destination)
        os.makedirs(dir_path, exist_ok=True)
        
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=30) as resp:
                if resp.status == 200:
                    async with aiofiles.open(destination, 'wb') as f:
                        await f.write(await resp.read())
    except Exception as e:
        LOGGER.error(f"Gagal download cover: {e}")

async def create_cover_file(url:str, meta:dict, thumbnail=False): 
    # 1. Validasi URL
    if not url: return './project-siesta.png'

    # 2. [FIX] Gunakan MD5 Hash dari URL untuk nama file
    # Ini menjamin setiap URL gambar yang beda akan punya file sendiri
    # tanpa tergantung pada itemid yang sering kosong.
    try:
        url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()
        filename = f"{url_hash}.jpg"
    except Exception:
        # Fallback jika error hashing
        filename = f"temp_cover_{datetime.now().timestamp()}.jpg"
    
    # 3. Tentukan Folder Temp
    temp_dir = meta.get('tempfolder', '.')
    
    # 4. Gabungkan Path
    cover_path = os.path.join(temp_dir, filename)
    
    # 5. Download jika file belum ada
    # Logic ini sekarang aman karena nama file berdasarkan konten URL unik
    if not os.path.exists(cover_path):
        await _download_cover_with_headers(url, cover_path)
    
    # 6. Cek hasil download
    if os.path.exists(cover_path) and os.path.getsize(cover_path) > 0:
        return cover_path
        
    return './project-siesta.png'

