# [GANTI SELURUH FILE: bot/helpers/bandcamp/metadata.py]

import asyncio
from mutagen.mp3 import MP3
from mutagen.id3 import (
    ID3, APIC, TIT2, TPE1, TALB, TRCK, TDRC, TCON, TPUB, TPE2, 
    USLT, TCOP, TCOM, TSRC
)
from bot.logger import LOGGER

async def set_bandcamp_metadata(filepath, track_meta):
    """
    track_meta dictionary berisi:
    title, artist, album, track_num, total_tracks, cover_path, 
    date (YYYY-MM-DD), genre, label, album_artist,
    lyrics, copyright, composer, isrc
    """
    def _write_tags():
        try:
            try:
                audio = MP3(filepath, ID3=ID3)
            except Exception:
                audio = MP3(filepath)

            if audio.tags is None:
                try:
                    audio.add_tags()
                except Exception:
                    audio.tags = ID3()
            
            # --- TAGS UTAMA ---
            if track_meta.get('title'):
                audio.tags.add(TIT2(encoding=3, text=track_meta['title']))
                
            if track_meta.get('artist'):
                audio.tags.add(TPE1(encoding=3, text=track_meta['artist']))
                
            if track_meta.get('album'):
                audio.tags.add(TALB(encoding=3, text=track_meta['album']))
                
            if track_meta.get('track_num') and track_meta.get('total_tracks'):
                audio.tags.add(TRCK(encoding=3, text=f"{track_meta['track_num']}/{track_meta['total_tracks']}"))

            # --- TAGS TAMBAHAN ---
            if track_meta.get('date'):
                audio.tags.add(TDRC(encoding=3, text=str(track_meta['date'])))

            if track_meta.get('genre'):
                audio.tags.add(TCON(encoding=3, text=track_meta['genre']))

            if track_meta.get('label'):
                audio.tags.add(TPUB(encoding=3, text=track_meta['label']))

            if track_meta.get('album_artist'):
                audio.tags.add(TPE2(encoding=3, text=track_meta['album_artist']))

            if track_meta.get('copyright'):
                audio.tags.add(TCOP(encoding=3, text=track_meta['copyright']))

            if track_meta.get('composer'):
                audio.tags.add(TCOM(encoding=3, text=track_meta['composer']))

            if track_meta.get('isrc'):
                audio.tags.add(TSRC(encoding=3, text=track_meta['isrc']))
                
            if track_meta.get('lyrics'):
                audio.tags.add(USLT(encoding=3, lang='eng', desc='', text=track_meta['lyrics']))

            # Cover Art (I/O disk)
            if track_meta.get('cover_path'):
                try:
                    with open(track_meta['cover_path'], 'rb') as f:
                        audio.tags.add(APIC(
                            encoding=3,
                            mime='image/jpeg',
                            type=3,
                            desc=u'Cover',
                            data=f.read()
                        ))
                except Exception as e:
                    LOGGER.warning(f"Gagal embed cover art: {e}")
            
            audio.save()
            return True
            
        except Exception as e:
            LOGGER.error(f"Bandcamp Tagging Error: {e}")
            return False

    # Lemparkan tugas disk I/O ini ke thread terpisah!
    return await asyncio.to_thread(_write_tags)
