# [GANTI SELURUH FILE: bot/helpers/jiosaavn/metadata.py]

import asyncio
from mutagen.mp4 import MP4, MP4Cover
from bot.logger import LOGGER

async def set_jiosaavn_metadata(file_path, track_data, album_art_path, lyrics=None):
    def _write_tags():
        duration = 0
        try:
            audio = MP4(file_path)
            
            # --- Basic Tags ---
            audio["\xa9nam"] = track_data.get("song", "Unknown Title")
            audio["\xa9alb"] = track_data.get("album", "Unknown Album")
            audio["\xa9ART"] = track_data.get("primary_artists", "Unknown Artist")
            audio["aART"] = track_data.get("primary_artists", "Unknown Artist")
            audio["\xa9day"] = str(track_data.get("year", ""))
            audio["\xa9wrt"] = track_data.get("music", "") # Composer
            
            # --- Fix Genre ---
            genre = track_data.get("genre") or track_data.get("language", "").title()
            if genre:
                audio["\xa9gen"] = genre

            # --- Fix Track Number & Total ---
            try:
                t_num = int(track_data.get("track_number", 0))
                t_total = int(track_data.get("total_tracks", 0))
                if t_num > 0:
                    audio["trkn"] = [(t_num, t_total)]
            except: pass

            # --- Fix ContentType ---
            audio["stik"] = [1] 

            # --- Advanced Tags ---
            if track_data.get("label"):
                audio["----:TXXX:Record label"] = bytes(track_data["label"], 'utf-8')
                audio["cprt"] = track_data.get("copyright_text", track_data["label"])
            
            if track_data.get("language"):
                audio["----:TXXX:Language"] = bytes(track_data["language"].title(), 'utf-8')
                audio["----:com.apple.iTunes:LANGUAGE"] = bytes(track_data["language"].title(), 'utf-8')
                
            if "explicit_content" in track_data:
                audio["rtng"] = [4 if str(track_data["explicit_content"]) == "1" else 2]

            if track_data.get("singers"):
                 audio["----:TXXX:Singers"] = bytes(track_data["singers"], 'utf-8')
            if track_data.get("starring"):
                 audio["----:TXXX:Starring"] = bytes(track_data["starring"], 'utf-8')
            if track_data.get("featured_artists"):
                 audio["----:TXXX:Featured artists"] = bytes(track_data["featured_artists"], 'utf-8')

            if lyrics:
                clean_lyrics = lyrics.replace("<br>", "\n")
                audio["\xa9lyr"] = clean_lyrics

            if album_art_path:
                with open(album_art_path, "rb") as f:
                    audio["covr"] = [MP4Cover(f.read(), imageformat=MP4Cover.FORMAT_JPEG)]
            
            audio.pop("©too", None) 
            audio.save()
            
            audio = MP4(file_path)
            duration = int(audio.info.length)

        except Exception as e:
            LOGGER.error(f"Gagal set metadata JioSaavn: {e}")
        
        return duration

    # Lemparkan tugas berat disk I/O ini ke background thread!
    return await asyncio.to_thread(_write_tags)
