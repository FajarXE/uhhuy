# [GANTI SELURUH FILE: bot/helpers/spotify/handler.py]

import os
import asyncio
import logging
import shutil
import random
from pyrogram.errors import MessageNotModified

# Import internal bot modules
from config import Config
from bot.helpers.utils import format_string, post_art_poster, fetch_zip_settings, run_concurrent_tasks
from bot.helpers.message import edit_message, send_message
from bot.helpers.uploder import track_upload, album_upload, playlist_upload, zip_handler
from bot.helpers.metadata import set_metadata, create_cover_file 
from bot.helpers.spotify.manager import spotify_manager
from bot.helpers.database.mongo_async import database # <-- [BARU] Import database
import bot.helpers.translations as lang

LOGGER = logging.getLogger("SpotifyHandler")

async def start_spotify(link: str, user: dict):
    client = spotify_manager.get_client()
    if not client:
        await spotify_manager.initialize_clients()
        client = spotify_manager.get_client()
        if not client:
            await send_message(user, "❌ **Spotify Gagal:** Bot belum login.", 'text')
            return

    msg = user.get('bot_msg')
    await edit_message(msg, "🔍 **Spotify:** Menganalisis Link...")
    
    parsed_data = await asyncio.to_thread(client.parse_url, link)
    if not parsed_data:
        await edit_message(msg, "❌ Link Spotify tidak valid.")
        return

    item_type_enum, item_id = parsed_data
    item_type = item_type_enum.name.lower() if hasattr(item_type_enum, 'name') else str(item_type_enum).lower()

    LOGGER.info(f"Spotify Processing: Type={item_type}, ID={item_id}")

    try:
        if item_type == 'track':
            await process_track(client, item_id, user)
        elif item_type == 'album':
            await process_album(client, item_id, user)
        elif item_type == 'playlist':
            await process_playlist(client, item_id, user)
        elif item_type == 'artist':
            await process_artist(client, item_id, user)
        elif item_type == 'episode':
            await process_track(client, item_id, user, is_episode=True)
        else:
            await edit_message(msg, f"❌ Tipe konten '{item_type}' belum didukung.")
            
    except Exception as e:
        LOGGER.error(f"Spotify Handler Error: {e}", exc_info=True)
        await edit_message(msg, f"❌ **Error:** {str(e)}")


async def fetch_artist_genre(client, artist_id):
    try:
        if not artist_id: return None
        raw_artists = await asyncio.to_thread(client.get_several_artists, [artist_id])
        if raw_artists and raw_artists[0]:
            genres = raw_artists[0].get('genres', [])
            if genres:
                return genres[0].title()
    except Exception as e:
        LOGGER.warning(f"Gagal mengambil genre: {e}")
    return None

def map_spotify_to_bot_metadata(track_info, user, is_episode=False, custom_genre=None):
    cover_url = track_info.cover_url
    explicit_val = track_info.explicit if track_info.explicit is not None else False
    
    rel_date = "Unknown"
    if track_info.tags and hasattr(track_info.tags, 'release_date') and track_info.tags.release_date:
        rel_date = str(track_info.tags.release_date)
    elif hasattr(track_info, 'release_year') and track_info.release_year:
        rel_date = str(track_info.release_year)
        
    tags = track_info.tags
    final_genre = custom_genre if custom_genre else "Pop"

    isrc = getattr(track_info, 'isrc', '')
    upc = getattr(track_info, 'upc', '')
    label = getattr(track_info, 'label', '')
    copyright_txt = getattr(track_info, 'copyright', '')
    
    composer_val = track_info.artists[0] if track_info.artists else "Unknown"

    meta = {
        'title': track_info.name,
        'artist': track_info.artists[0] if track_info.artists else "Unknown",
        'album': track_info.album,
        'albumartist': getattr(tags, 'album_artist', "Unknown") if tags else "Unknown",
        'date': str(track_info.release_year) if track_info.release_year else "",
        'release_date': rel_date,
        'tracknumber': str(getattr(tags, 'track_number', '1')),
        'totaltracks': str(getattr(tags, 'total_tracks', '1')),
        'discnumber': str(getattr(tags, 'disc_number', '1')),
        'volume': str(getattr(tags, 'disc_number', '1')), 
        'totalvolumes': "1",
        'totalvolume': "1",
        'genre': final_genre,
        'duration': track_info.duration, 
        'quality': getattr(track_info, 'quality', "High (320kbps)"), # <-- [BARU] Ambil dari track_info
        'provider': "Spotify",
        'explicit': explicit_val,
        'isrc': isrc,
        'upc': upc,
        'copyright': copyright_txt,
        'publisher': label,
        'organization': label,
        'composer': composer_val,
        'producer': composer_val,
        'lyrics': None, 
        'type': 'track',
        'cover': cover_url,
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{user.get('r_id', 'unknown')}-temp/"
    }
    
    if is_episode:
        meta['type'] = 'episode'
        meta['album'] = track_info.album 
        meta['artist'] = track_info.artists[0] if track_info.artists else "Unknown"
        
    return meta

async def process_track(client, track_id, user, is_episode=False):
    msg = user.get('bot_msg')
    await edit_message(msg, f"⬇️ **Spotify:** Mengunduh {'Episode' if is_episode else 'Lagu'}...")

    try:
        # --- [BARU] Mengambil kualitas Spotify dari database user ---
        user_id_val = user.get('user_id') or user.get('id')
        spotify_quality = user.get("spotify_qual", "VERY_HIGH")
        
        if is_episode:
             track_info = await asyncio.to_thread(client.get_episode_info, track_id, spotify_quality, None)
        else:
             track_info = await asyncio.to_thread(client.get_track_info, track_id, spotify_quality, None)
             
        if not track_info: raise Exception("Gagal mengambil metadata.")

        download_result = None
        if is_episode:
             download_result = await asyncio.to_thread(client.get_episode_download, track_id=track_id, quality_tier=spotify_quality)
        else:
             download_result = await asyncio.to_thread(client.get_track_download, track_id=track_id, quality_tier=spotify_quality)

        if not download_result or not download_result.temp_file_path:
            raise Exception("Gagal mengunduh stream audio.")

        fetched_genre = None
        if not is_episode and track_info.artist_id:
            fetched_genre = await fetch_artist_genre(client, track_info.artist_id)

        meta = map_spotify_to_bot_metadata(track_info, user, is_episode, custom_genre=fetched_genre)
        
        clean_artist = meta['artist'].replace("/", "_")
        clean_title = meta['title'].replace("/", "_")
        
        # Ekstensi menyesuaikan codec (FLAC/OGG)
        file_ext = ".flac" if spotify_quality == "LOSSLESS" and download_result.temp_file_path.endswith('.flac') else ".ogg"
        final_filename = f"{clean_artist} - {clean_title}{file_ext}"
        
        r_id = user.get('r_id', 'unknown')
        user_folder = f"{Config.DOWNLOAD_BASE_DIR}/{r_id}/Spotify"
        os.makedirs(user_folder, exist_ok=True)
        
        final_path = os.path.join(user_folder, final_filename)
        shutil.move(download_result.temp_file_path, final_path)
        
        meta['filepath'] = final_path
        meta['folderpath'] = user_folder

        if os.path.getsize(final_path) < 1024:
            raise Exception("File audio korup/kosong (0 bytes).")

        if meta.get('cover'):
            thumb_path = await create_cover_file(meta['cover'], meta, thumbnail=True)
            meta['thumbnail'] = thumb_path
            
        await edit_message(msg, "🏷 **Spotify:** Menulis Metadata...")
        await set_metadata(meta, user_id_val)

        await edit_message(msg, "⬆️ **Spotify:** Mengunggah...")
        await track_upload(meta, user)

    except Exception as e:
        raise e

# --- HELPER WORKER (DIPANGGIL OLEH RUN_CONCURRENT_TASKS) ---
async def process_single_track(client, track, user, parent_info, user_folder, custom_genre, is_playlist, upload_per_track):
    try:
        if not track or not track.id: return None
        
        # Jeda anti-ban khusus Spotify agar koneksi TCP tidak dicurigai
        await asyncio.sleep(random.uniform(1.0, 3.5))
        
        # --- [BARU] Mengambil kualitas Spotify dari database user ---
        user_id_val = user.get('user_id') or user.get('id')
        spotify_quality = user.get("spotify_qual", "VERY_HIGH")

        download_result = await asyncio.to_thread(client.get_track_download, track_id=track.id, quality_tier=spotify_quality)
        if not download_result or not download_result.temp_file_path: return None

        full_track_info = None
        try:
            full_track_info = await asyncio.to_thread(client.get_track_info, track.id, spotify_quality, None)
        except: pass

        target_info = full_track_info if full_track_info else track
        
        if not is_playlist and track.tags and target_info.tags:
            target_info.tags.track_number = track.tags.track_number
            target_info.tags.disc_number = track.tags.disc_number
            target_info.tags.total_tracks = track.tags.total_tracks

        meta = map_spotify_to_bot_metadata(target_info, user, custom_genre=custom_genre)
        
        # Ekstensi menyesuaikan
        file_ext = ".flac" if spotify_quality == "LOSSLESS" and download_result.temp_file_path.endswith('.flac') else ".ogg"
        
        if not is_playlist:
            meta['totaltracks'] = str(len(parent_info.tracks))
            meta['album'] = parent_info.name
            meta['cover'] = parent_info.all_track_cover_jpg_url
            clean_title = meta['title'].replace("/", "_")
            track_str = str(meta['tracknumber']).zfill(2)
            filename = f"{track_str} - {clean_title}{file_ext}"
        else:
            clean_artist = meta['artist'].replace("/", "_")
            clean_title = meta['title'].replace("/", "_")
            track_str = str(meta['tracknumber']).zfill(2)
            filename = f"{track_str} - {clean_artist} - {clean_title}{file_ext}"
            
        final_path = os.path.join(user_folder, filename)
        shutil.move(download_result.temp_file_path, final_path)
        
        meta['filepath'] = final_path
        meta['folderpath'] = user_folder
        
        if os.path.exists(final_path) and os.path.getsize(final_path) > 1024:
            thumb_source = parent_info.all_track_cover_jpg_url if not is_playlist else (meta.get('cover') or parent_info.cover_url)
            if thumb_source:
                t_path = await create_cover_file(thumb_source, meta, thumbnail=True)
                meta['thumbnail'] = t_path
            
            # --- [FIX OGG/FLAC HEADER ERROR] ---
            # Kita bungkus set_metadata dengan try-except agar jika file korup (0x00),
            # proses tidak menghentikan lagu lain di album!
            try:
                await set_metadata(meta, user_id_val)
            except Exception as e:
                LOGGER.error(f"Gagal menulis metadata (File audio mungkin korup dari Spotify): {e}")
                os.remove(final_path)
                return None
            # -------------------------------
            
            if upload_per_track:
                await track_upload(meta, user)
                
            return meta
        else:
            try: os.remove(final_path)
            except: pass
            return None
    except Exception as e:
        LOGGER.error(f"Skip Spotify track: {e}")
        return None

async def process_album(client, album_id, user):
    msg = user.get('bot_msg')
    await edit_message(msg, "🔍 **Spotify:** Mengambil Info Album...")

    album_info = await asyncio.to_thread(client.get_album_info, album_id)
    if not album_info: raise Exception("Album tidak ditemukan.")

    tracks = album_info.tracks
    total = len(tracks)
    
    album_genre = None
    try:
        if tracks and tracks[0].artist_id:
            album_genre = await fetch_artist_genre(client, tracks[0].artist_id)
    except: pass

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    r_id = user.get('r_id', 'unknown')
    
    # Ambil kualitas user untuk album info text (Opsional)
    user_id_val = user.get('user_id') or user.get('id')
    spotify_quality = user.get("spotify_qual", "VERY_HIGH")
    
    meta_album = {
        'title': album_info.name,
        'artist': album_info.artist,
        'cover': album_info.all_track_cover_jpg_url,
        'type': 'album',
        'provider': 'Spotify',
        'date': str(album_info.release_year),
        'release_date': str(album_info.release_year),
        'quality': "Lossless/FLAC" if spotify_quality == "LOSSLESS" else "High (320kbps)",
        'totaltracks': str(total),
        'totalvolumes': "1",
        'explicit': False,
        'genre': album_genre if album_genre else "Pop",
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{r_id}-temp/"
    }
    
    if meta_album.get('cover'):
         poster_path = await create_cover_file(meta_album['cover'], meta_album, thumbnail=False)
         meta_album['thumbnail'] = poster_path

    poster_key = f'poster_album_{album_id}'
    if user.get(poster_key):
        meta_album['poster_msg'] = user[poster_key]
    else:
        meta_album['poster_msg'] = await post_art_poster(user, meta_album)
        user[poster_key] = meta_album['poster_msg']

    user_folder = f"{Config.DOWNLOAD_BASE_DIR}/{r_id}/Spotify/{album_info.name}"
    os.makedirs(user_folder, exist_ok=True)
    meta_album['folderpath'] = user_folder

    upload_per_track = not album_zip
    tasks = []

    for track in tracks:
        tasks.append(process_single_track(
            client, track, user, album_info, user_folder, album_genre, 
            is_playlist=False, upload_per_track=upload_per_track
        ))

    # --- [FIX PROGRESS BAR & CANCEL] ---
    # Memanggil antarmuka bawaan bot agar bisa dicancel,
    # tetapi MENGUNCI limit=1 agar koneksi Spotify tidak tabrakan/banned!
    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': msg, 
        'title': album_info.name, 
        'type': 'Album'
    }
    task_results = await run_concurrent_tasks(tasks, update_details, limit=1)
    processed_tracks = [res for res in task_results if isinstance(res, dict)]
    # ------------------------------------

    if not processed_tracks: raise Exception("Gagal mengunduh semua lagu dalam album.")
    meta_album['tracks'] = processed_tracks
    
    # --- MODIFIKASI: Pastikan Cover menjadi path lokal sebelum uploader mengambil alih ---
    thumb_url = getattr(album_info, 'small_cover_url', None) or meta_album.get('cover')
    if thumb_url and str(thumb_url).startswith('http'):
         zip_thumb_path = await create_cover_file(thumb_url, meta_album, thumbnail=True)
         meta_album['thumbnail'] = zip_thumb_path if zip_thumb_path and os.path.exists(zip_thumb_path) else None
         
    if meta_album.get('cover') and str(meta_album['cover']).startswith('http'):
         try:
             large_cover = await create_cover_file(meta_album['cover'], meta_album, thumbnail=False)
             if large_cover and os.path.exists(large_cover):
                 shutil.copy(large_cover, os.path.join(user_folder, "cover.jpg"))
                 meta_album['cover'] = large_cover
             else:
                 meta_album['cover'] = None
         except: 
             meta_album['cover'] = None
    # -----------------------------------------------------------------------------------

    # Zipping dan upload (baik Zip maupun Batch per-lagu) diurus otomatis oleh uploader.py
    # agar Papan Global menampilkan transisi yang mulus tanpa kedipan!
    await album_upload(meta_album, user)


async def process_playlist(client, playlist_id, user):
    msg = user.get('bot_msg')
    await edit_message(msg, "🔍 **Spotify:** Mengambil Info Playlist...")

    playlist_info = await asyncio.to_thread(client.get_playlist_info, playlist_id)
    if not playlist_info: raise Exception("Playlist tidak ditemukan / Privat.")

    tracks = playlist_info.tracks
    total = len(tracks)
    
    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)
    r_id = user.get('r_id', 'unknown')

    user_id_val = user.get('user_id') or user.get('id')
    spotify_quality = user.get("spotify_qual", "VERY_HIGH")
    
    meta_playlist = {
        'title': playlist_info.name,
        'artist': playlist_info.creator,
        'cover': playlist_info.cover_url,
        'type': 'playlist',
        'provider': 'Spotify',
        'totaltracks': str(total),
        'totalvolumes': "1",
        'quality': "Lossless/FLAC" if spotify_quality == "LOSSLESS" else "High (320kbps)",
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{r_id}-temp/"
    }
    
    if meta_playlist.get('cover'):
         p_path = await create_cover_file(meta_playlist['cover'], meta_playlist, thumbnail=False)
         meta_playlist['thumbnail'] = p_path
    
    poster_key = f'poster_playlist_{playlist_id}'
    if user.get(poster_key):
        meta_playlist['poster_msg'] = user[poster_key]
    else:
        meta_playlist['poster_msg'] = await post_art_poster(user, meta_playlist)
        user[poster_key] = meta_playlist['poster_msg']

    user_folder = f"{Config.DOWNLOAD_BASE_DIR}/{r_id}/Spotify/{playlist_info.name}"
    os.makedirs(user_folder, exist_ok=True)
    meta_playlist['folderpath'] = user_folder

    upload_per_track = not playlist_zip
    tasks = []

    for track in tracks:
        tasks.append(process_single_track(
            client, track, user, playlist_info, user_folder, None, 
            is_playlist=True, upload_per_track=upload_per_track
        ))

    # --- [FIX PROGRESS BAR & CANCEL] ---
    update_details = {
        'text': lang.s.DOWNLOAD_PROGRESS,
        'msg': msg, 
        'title': playlist_info.name, 
        'type': 'Playlist'
    }
    task_results = await run_concurrent_tasks(tasks, update_details, limit=1)
    processed_tracks = [res for res in task_results if isinstance(res, dict)]
    # ------------------------------------

    if not processed_tracks: raise Exception("Gagal mengunduh isi playlist (Semua lagu gagal).")
    meta_playlist['tracks'] = processed_tracks
    
    # --- MODIFIKASI: Pastikan Cover menjadi path lokal sebelum uploader mengambil alih ---
    thumb_url = getattr(playlist_info, 'small_cover_url', None) or meta_playlist.get('cover')
    if thumb_url and str(thumb_url).startswith('http'):
         zip_thumb_path = await create_cover_file(thumb_url, meta_playlist, thumbnail=True)
         meta_playlist['thumbnail'] = zip_thumb_path if zip_thumb_path and os.path.exists(zip_thumb_path) else None
         
    if meta_playlist.get('cover') and str(meta_playlist['cover']).startswith('http'):
         try:
             large_cover = await create_cover_file(meta_playlist['cover'], meta_playlist, thumbnail=False)
             if large_cover and os.path.exists(large_cover):
                 shutil.copy(large_cover, os.path.join(user_folder, "cover.jpg"))
                 meta_playlist['cover'] = large_cover
             else:
                 meta_playlist['cover'] = None
         except: 
             meta_playlist['cover'] = None
    # -----------------------------------------------------------------------------------

    # Zipping dan upload (baik Zip maupun Batch per-lagu) diurus otomatis oleh uploader.py
    # agar Papan Global menampilkan transisi yang mulus tanpa kedipan!
    await playlist_upload(meta_playlist, user)


async def process_artist(client, artist_id, user):
    msg = user.get('bot_msg')
    await edit_message(msg, "⚠️ **Info:** Download Artis belum didukung penuh. Silakan download per Album.")
