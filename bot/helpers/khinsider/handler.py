# [GANTI TOTAL ISI FILE: bot/helpers/khinsider/handler.py]

import os
import aiohttp
import aiofiles
import time
import asyncio
from datetime import datetime
from mutagen.mp3 import MP3
from mutagen.id3 import (
    ID3, APIC, TYER, TDRC, TPOS, TRCK, TIT2, TALB,
    TPE1, TPE2, TOPE, TCON, TPUB, TCOP, TCOM, TXXX, TDTG
)
from mutagen.flac import FLAC, Picture

from bot.settings import bot_set
from bot.helpers.utils import (
    download_file,
    run_concurrent_tasks,
    fetch_zip_settings,
    post_art_poster
)
from bot.helpers.uploder import album_upload
from bot.helpers.message import edit_message
from config import Config
from .manager import khinsider_manager
from bot.logger import LOGGER

# --- FUNGSI TAGGING LENGKAP & MEDIAINFO COMPATIBLE ---
def set_file_tags(filepath, meta, cover_path, fmt):
    """Menanamkan Cover + Metadata lengkap yang terbaca di MediaInfo."""
    if not os.path.exists(filepath):
        return

    try:
        title = meta.get('title', '')
        album = meta.get('album', '')
        artist = meta.get('artist', 'Game Soundtrack')
        year = meta.get('date', '')
        if year == 'N/A':
            year = ''
            
        track_num = str(meta.get('tracknumber', '1'))
        total_tracks = str(meta.get('totaltracks', '1'))
        track_pos = f"{track_num}/{total_tracks}"

        disc_num = str(meta.get('disc_number', '1'))
        total_discs = str(meta.get('totalvolumes', '1'))
        disc_pos = f"{disc_num}/{total_discs}"

        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if fmt == 'mp3':
            try:
                audio = MP3(filepath, ID3=ID3)
            except Exception:
                audio = MP3(filepath)
                audio.add_tags()

            if audio.tags is None:
                audio.add_tags()

            # Metadata Standar
            if title:
                audio.tags.add(TIT2(encoding=3, text=title))
            if album:
                audio.tags.add(TALB(encoding=3, text=album))
            if artist:
                audio.tags.add(TPE1(encoding=3, text=artist))
                audio.tags.add(TPE2(encoding=3, text=artist))
                audio.tags.add(TOPE(encoding=3, text=artist))

            # Posisi Track & Part
            audio.tags.add(TRCK(encoding=3, text=track_pos))
            audio.tags.add(TPOS(encoding=3, text=disc_pos))
            audio.tags.add(TXXX(encoding=3, desc='Part', text=track_pos))
            audio.tags.add(TXXX(encoding=3, desc='PART', text=track_pos))

            # Publisher / Label
            pub = "Khinsider"
            audio.tags.add(TPUB(encoding=3, text=pub))
            audio.tags.add(TXXX(encoding=3, desc='Label', text=pub))
            audio.tags.add(TXXX(encoding=3, desc='LABEL', text=pub))
            audio.tags.add(TXXX(encoding=3, desc='pub', text=pub))

            # Producer & Composer
            audio.tags.add(TXXX(encoding=3, desc='Producer', text=artist))
            audio.tags.add(TXXX(encoding=3, desc='PRODUCER', text=artist))
            audio.tags.add(TCOM(encoding=3, text=artist))
            audio.tags.add(TXXX(encoding=3, desc='Composer', text=artist))

            # Copyright
            cpr = f"© {year or datetime.now().year} {pub}"
            audio.tags.add(TCOP(encoding=3, text=cpr))
            audio.tags.add(TXXX(encoding=3, desc='Copyright', text=cpr))
            audio.tags.add(TXXX(encoding=3, desc='cpr', text=cpr))

            # Genre & Rating
            audio.tags.add(TCON(encoding=3, text="Soundtrack"))
            audio.tags.add(TXXX(encoding=3, desc='Genre', text="Soundtrack"))
            audio.tags.add(TXXX(encoding=3, desc='Rating', text="Clean"))
            audio.tags.add(TXXX(encoding=3, desc='ITUNESADVISORY', text="2"))

            # Dates
            if year:
                audio.tags.add(TDRC(encoding=3, text=str(year)))
                audio.tags.add(TYER(encoding=3, text=str(year)))

            audio.tags.add(TDTG(encoding=3, text=now_str))
            audio.tags.add(TXXX(encoding=3, desc='TAGGING_TIME', text=now_str))
            audio.tags.add(TXXX(encoding=3, desc='DATE_TAGGED', text=now_str))
            audio.tags.add(TXXX(encoding=3, desc='ENCODED_DATE', text=now_str))

            # Cover Art
            if cover_path and os.path.exists(cover_path):
                audio.tags.delall("APIC")
                with open(cover_path, 'rb') as albumart:
                    audio.tags.add(APIC(
                        encoding=3,
                        mime='image/jpeg',
                        type=3,
                        desc='Cover',
                        data=albumart.read()
                    ))
            audio.save()

        elif fmt == 'flac':
            audio = FLAC(filepath)
            if audio.tags is None:
                audio.add_tags()

            if title:
                audio['TITLE'] = title
            if album:
                audio['ALBUM'] = album
            if artist:
                audio['ARTIST'] = artist
                audio['ALBUMARTIST'] = artist
                audio['COMPOSER'] = artist

            audio['TRACKNUMBER'] = str(track_num)
            audio['TOTALTRACKS'] = str(total_tracks)
            audio['TRACKTOTAL'] = str(total_tracks)
            audio['DISCNUMBER'] = str(disc_num)
            audio['TOTALDISCS'] = str(total_discs)
            audio['DISCTOTAL'] = str(total_discs)

            audio['GENRE'] = "Soundtrack"
            audio['PUBLISHER'] = "Khinsider"
            audio['LABEL'] = "Khinsider"
            audio['pub'] = "Khinsider"
            audio['COPYRIGHT'] = f"© {year or datetime.now().year} Khinsider"
            audio['cpr'] = audio['COPYRIGHT']
            audio['RATING'] = "Clean"
            audio['ITUNESADVISORY'] = "2"

            if year:
                audio['DATE'] = str(year)
                audio['YEAR'] = str(year)

            audio['TAGGING_TIME'] = now_str
            audio['DATE_TAGGED'] = now_str
            audio['ENCODED_DATE'] = now_str

            if cover_path and os.path.exists(cover_path):
                image = Picture()
                image.type = 3
                image.mime = 'image/jpeg'
                image.desc = 'Cover'
                with open(cover_path, 'rb') as f:
                    image.data = f.read()
                audio.clear_pictures()
                audio.add_picture(image)

            audio.save()

    except Exception as e:
        LOGGER.error(f"Gagal set tags untuk {filepath}: {e}")

# --- HANDLER UTAMA ---
async def start_khinsider(url, user):
    msg = user['bot_msg']
    await edit_message(msg, "🚀 Starting task...")

    try:
        album_meta = await khinsider_manager.get_album(url)
    except Exception as e:
        await edit_message(msg, f"❌ Gagal mengambil info album: {e}")
        return

    album_folder_path = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/{album_meta['title']}"
    os.makedirs(album_folder_path, exist_ok=True)

    cover_path = None
    if album_meta.get('images'):
        for i, img_url in enumerate(album_meta['images']):
            try:
                ext = img_url.split('.')[-1].split('?')[0]
                if i == 0:
                    filename = f"cover.{ext}"
                    filepath = f"{album_folder_path}/{filename}"
                    cover_path = filepath
                else:
                    filename = f"artwork_{i}.{ext}"
                    filepath = f"{album_folder_path}/{filename}"

                # Download gambar dengan menyertakan Referer album untuk bypass proteksi 403
                img_headers = khinsider_manager.headers.copy()
                img_headers["Referer"] = album_meta.get('album_url', khinsider_manager.base_referer)
                await download_file(img_url, filepath, details={'msg': None, 'headers': img_headers})
            except Exception:
                pass

    track_total = len(album_meta['tracks'])

    album_data = {
        'title': album_meta['title'],
        'album': album_meta['title'],
        'artist': 'Game Soundtrack',
        'albumartist': 'Game Soundtrack',
        'type': 'album',
        'provider': 'Khinsider',
        'tracks': [],
        'cover': cover_path,
        'thumbnail': cover_path,
        'folderpath': album_folder_path,
        'totaltracks': str(track_total),
        'date': album_meta['date'],
        'totalvolumes': album_meta['totalvolumes'],
        'explicit': str(album_meta['explicit']),
        'quality': bot_set.user_data.get(user['user_id'], {}).get('khinsider_qual', 'FLAC').upper()
    }

    try:
        album_data['poster_msg'] = await post_art_poster(user, album_data)
    except Exception as e:
        LOGGER.error(f"Gagal mengirim poster Khinsider: {e}")

    async def _process_track(track):
        try:
            # 1. Scrape Direct Link dengan Referer album
            dl_url, fmt = await khinsider_manager.get_track_download_url(
                track['url'],
                preferred_formats=[bot_set.user_data.get(user['user_id'], {}).get('khinsider_qual', 'flac'), 'mp3'],
                album_url=album_meta.get('album_url')
            )

            if int(album_meta['totalvolumes']) > 1:
                filename = f"{track['disc_number']}-{track['track_number'].zfill(2)}. {track['title']}.{fmt}"
            else:
                filename = f"{track['track_number'].zfill(2)}. {track['title']}.{fmt}"

            filename = filename.replace("/", "_").replace("\\", "_")
            filepath = f"{album_folder_path}/{filename}"

            # 2. Download via Aria2 + aiohttp fallback (menyertakan track['url'] sebagai Referer)
            headers_dict = khinsider_manager.headers.copy()
            headers_dict["Referer"] = track['url']

            details_aria = {'msg': None, 'headers': headers_dict}
            err = await download_file(dl_url, filepath, retries=1, details=details_aria)

            if err:
                LOGGER.warning(f"Khinsider: Aria2 gagal/ditolak. Mengaktifkan AIOHTTP Fallback untuk {filename}")
                timeout = aiohttp.ClientTimeout(total=300)
                async with aiohttp.ClientSession(headers=headers_dict, timeout=timeout) as session:
                    async with session.get(dl_url) as r:
                        r.raise_for_status()
                        async with aiofiles.open(filepath, 'wb') as f:
                            async for chunk in r.content.iter_chunked(256 * 1024):
                                if chunk:
                                    await f.write(chunk)

            # 3. Tagging Metadata Audio
            track_meta_for_tag = {
                'title': track['title'],
                'album': album_meta['title'],
                'artist': 'Game Soundtrack',
                'tracknumber': track['track_number'],
                'totaltracks': str(track_total),
                'date': album_meta['date'],
                'disc_number': track['disc_number'],
                'totalvolumes': album_meta['totalvolumes']
            }
            if cover_path and os.path.exists(cover_path):
                await asyncio.to_thread(set_file_tags, filepath, track_meta_for_tag, cover_path, fmt)

            # 4. Ambil Durasi Audio
            duration = 0
            try:
                if fmt == 'flac':
                    audio = FLAC(filepath)
                    duration = int(audio.info.length)
                elif fmt == 'mp3':
                    audio = MP3(filepath)
                    duration = int(audio.info.length)
            except Exception as e:
                LOGGER.error(f"Gagal baca durasi {filename}: {e}")

            meta = {
                'title': track['title'],
                'album': album_meta['title'],
                'artist': 'Game Soundtrack',
                'tracknumber': track['track_number'],
                'totaltracks': str(track_total),
                'filepath': filepath,
                'cover': cover_path,
                'provider': 'Khinsider',
                'type': 'album',
                'quality': fmt.upper(),
                'duration': duration,
                'extension': fmt
            }
            return meta
        except Exception as e:
            LOGGER.error(f"Khinsider track error: {e}")
            return None

    tasks = [_process_track(t) for t in album_meta['tracks']]
    update_details = {
        'msg': msg,
        'title': album_meta['title'],
        'type': 'Album',
        'action': 'Download'
    }

    results = await run_concurrent_tasks(tasks, update_details, limit=4)
    successful_tracks = [r for r in results if r]

    if not successful_tracks:
        await edit_message(msg, "❌ Gagal mengunduh semua lagu Khinsider.")
        return

    album_data['tracks'] = successful_tracks
    album_data['albums'] = [{'tracks': successful_tracks}]

    # 5. Upload Album
    await album_upload(album_data, user)
