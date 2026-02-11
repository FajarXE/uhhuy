import os
import asyncio
import logging
import shutil
from pyrogram.errors import MessageNotModified

# Import internal bot modules
from config import Config
from bot.helpers.utils import format_string, create_simple_text, post_art_poster, fetch_zip_settings
from bot.helpers.message import edit_message, send_message
from bot.helpers.uploder import track_upload, album_upload, playlist_upload, artist_upload, zip_handler
from bot.helpers.metadata import set_metadata, create_cover_file 
from bot.helpers.spotify.manager import spotify_manager
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
    
    parsed_data = client.parse_url(link)
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


async def process_track(client, track_id, user, is_episode=False):
    msg = user.get('bot_msg')
    await edit_message(msg, f"⬇️ **Spotify:** Mengunduh {'Episode' if is_episode else 'Lagu'}...")

    try:
        if is_episode:
             track_info = client.get_episode_info(track_id, "HIGH", None)
        else:
             track_info = client.get_track_info(track_id, "HIGH", None)
             
        if not track_info:
            raise Exception("Gagal mengambil metadata.")

        download_result = None
        if is_episode:
             download_result = client.get_episode_download(track_id=track_id, quality_tier="HIGH")
        else:
             download_result = client.get_track_download(track_id=track_id, quality_tier="HIGH")

        if not download_result or not download_result.temp_file_path:
            raise Exception("Gagal mengunduh stream audio.")

        meta = map_spotify_to_bot_metadata(track_info, user, is_episode)
        
        final_filename = f"{meta['artist']} - {meta['title']}.ogg".replace("/", "_")
        user_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Spotify"
        os.makedirs(user_folder, exist_ok=True)
        
        final_path = os.path.join(user_folder, final_filename)
        shutil.move(download_result.temp_file_path, final_path)
        
        meta['filepath'] = final_path
        meta['folderpath'] = user_folder

        if os.path.getsize(final_path) < 1024:
            raise Exception("File audio korup/kosong (0 bytes).")

        if meta.get('cover'):
            # [FIX] Ganti 'thumb' menjadi 'thumbnail'
            thumb_path = await create_cover_file(meta['cover'], meta, thumbnail=True)
            meta['thumbnail'] = thumb_path
            
        await edit_message(msg, "🏷 **Spotify:** Menulis Metadata...")
        await set_metadata(meta, user['user_id'])

        await edit_message(msg, "⬆️ **Spotify:** Mengunggah...")
        await track_upload(meta, user)

    except Exception as e:
        raise e


async def process_album(client, album_id, user):
    msg = user.get('bot_msg')
    await edit_message(msg, "🔍 **Spotify:** Mengambil Info Album...")

    album_info = client.get_album_info(album_id)
    if not album_info:
        raise Exception("Album tidak ditemukan.")

    tracks = album_info.tracks
    total = len(tracks)
    
    await edit_message(msg, f"⬇️ **Spotify:** Album ditemukan: {album_info.name}\nJumlah Lagu: {total}")
    
    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

    meta_album = {
        'title': album_info.name,
        'artist': album_info.artist,
        'cover': album_info.all_track_cover_jpg_url,
        'type': 'album',
        'provider': 'Spotify',
        'date': str(album_info.release_year),
        'release_date': str(album_info.release_year),
        'quality': "High (320kbps)",
        'totaltracks': str(total),
        'totalvolumes': "1",
        'explicit': False,
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/"
    }
    
    if meta_album.get('cover'):
         poster_path = await create_cover_file(meta_album['cover'], meta_album, thumbnail=False)
         # [FIX] Ganti 'thumb' menjadi 'thumbnail'
         meta_album['thumbnail'] = poster_path

    poster_key = f'poster_album_{album_id}'
    if user.get(poster_key):
        meta_album['poster_msg'] = user[poster_key]
    else:
        meta_album['poster_msg'] = await post_art_poster(user, meta_album)
        user[poster_key] = meta_album['poster_msg']

    processed_tracks = []
    user_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Spotify/{album_info.name}"
    os.makedirs(user_folder, exist_ok=True)
    meta_album['folderpath'] = user_folder

    upload_per_track = not album_zip

    for i, track in enumerate(tracks):
        try:
            current_num = i + 1
            await edit_message(msg, f"⬇️ **Spotify Album:** ({current_num}/{total})\n`{track.name}`")
            
            download_result = client.get_track_download(track_id=track.id, quality_tier="HIGH")
            
            if download_result and download_result.temp_file_path:
                meta = map_spotify_to_bot_metadata(track, user)
                meta['totaltracks'] = str(total)
                
                clean_title = meta['title'].replace("/", "_")
                track_str = str(meta['tracknumber']).zfill(2)
                filename = f"{track_str} - {clean_title}.ogg"
                
                final_path = os.path.join(user_folder, filename)
                shutil.move(download_result.temp_file_path, final_path)
                
                meta['filepath'] = final_path
                meta['folderpath'] = user_folder
                meta['cover'] = album_info.all_track_cover_jpg_url
                
                if os.path.exists(final_path) and os.path.getsize(final_path) > 1024:
                    if meta_album.get('thumbnail'):
                        meta['thumbnail'] = meta_album['thumbnail']
                    else:
                        t_path = await create_cover_file(meta['cover'], meta, thumbnail=True)
                        meta['thumbnail'] = t_path
                    
                    await set_metadata(meta, user['user_id'])
                    processed_tracks.append(meta)

                    if upload_per_track:
                        await track_upload(meta, user)
                else:
                    try: os.remove(final_path)
                    except: pass
                
        except Exception as e:
            LOGGER.error(f"Gagal download track {track.name}: {e}")
            continue

    if not processed_tracks:
        raise Exception("Gagal mengunduh semua lagu dalam album.")

    meta_album['tracks'] = processed_tracks
    
    if album_zip:
        await edit_message(user['bot_msg'], f"🗜️ **Zipping:** Menyiapkan {len(processed_tracks)} lagu...")
        
        thumb_url = getattr(album_info, 'small_cover_url', None) or meta_album.get('cover')
        
        if thumb_url:
             zip_thumb_path = await create_cover_file(thumb_url, meta_album, thumbnail=True)
             # [FIX] Ganti 'thumb' menjadi 'thumbnail'
             meta_album['thumbnail'] = zip_thumb_path
             
             if meta_album.get('cover'):
                 try:
                     large_cover = await create_cover_file(meta_album['cover'], meta_album, thumbnail=False)
                     shutil.copy(large_cover, os.path.join(user_folder, "cover.jpg"))
                 except: pass

        zip_path = await zip_handler(user_folder)
        meta_album['zip_path'] = zip_path
        
        await edit_message(user['bot_msg'], "⬆️ **Uploading Zip...**")
        await album_upload(meta_album, user)
    
    elif not album_zip:
        await edit_message(user['bot_msg'], "✅ **Album Upload Complete!**")


async def process_playlist(client, playlist_id, user):
    msg = user.get('bot_msg')
    await edit_message(msg, "🔍 **Spotify:** Mengambil Info Playlist...")

    playlist_info = client.get_playlist_info(playlist_id)
    if not playlist_info:
        raise Exception("Playlist tidak ditemukan / Privat.")

    tracks = playlist_info.tracks
    total = len(tracks)
    
    await edit_message(msg, f"⬇️ **Spotify:** Playlist: {playlist_info.name}\nTotal: {total} Lagu")

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

    meta_playlist = {
        'title': playlist_info.name,
        'artist': playlist_info.creator,
        'cover': playlist_info.cover_url,
        'type': 'playlist',
        'provider': 'Spotify',
        'totaltracks': str(total),
        'totalvolumes': "1",
        'quality': "High (320kbps)",
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/"
    }
    
    if meta_playlist.get('cover'):
         p_path = await create_cover_file(meta_playlist['cover'], meta_playlist, thumbnail=False)
         # [FIX] Ganti 'thumb' menjadi 'thumbnail'
         meta_playlist['thumbnail'] = p_path
    
    poster_key = f'poster_playlist_{playlist_id}'
    if user.get(poster_key):
        meta_playlist['poster_msg'] = user[poster_key]
    else:
        meta_playlist['poster_msg'] = await post_art_poster(user, meta_playlist)
        user[poster_key] = meta_playlist['poster_msg']

    user_folder = f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}/Spotify/{playlist_info.name}"
    os.makedirs(user_folder, exist_ok=True)
    meta_playlist['folderpath'] = user_folder

    processed_tracks = []
    upload_per_track = not playlist_zip

    for i, track in enumerate(tracks):
        try:
            if not track or not track.id: continue
            
            current_num = i + 1
            await edit_message(msg, f"⬇️ **Spotify Playlist:** ({current_num}/{total})\n`{track.name}`")
            
            download_result = client.get_track_download(track_id=track.id, quality_tier="HIGH")
            
            if download_result and download_result.temp_file_path:
                meta = map_spotify_to_bot_metadata(track, user)
                
                clean_artist = meta['artist'].replace("/", "_")
                clean_title = meta['title'].replace("/", "_")
                
                orig_track_num = str(meta['tracknumber']).zfill(2)
                filename = f"{orig_track_num} - {clean_artist} - {clean_title}.ogg"
                
                final_path = os.path.join(user_folder, filename)
                shutil.move(download_result.temp_file_path, final_path)
                
                meta['filepath'] = final_path
                meta['folderpath'] = user_folder
                
                if os.path.exists(final_path) and os.path.getsize(final_path) > 1024:
                    if meta.get('cover'):
                        t_path = await create_cover_file(meta['cover'], meta, thumbnail=True)
                        # [FIX] Ganti 'thumb' menjadi 'thumbnail'
                        meta['thumbnail'] = t_path
                    
                    await set_metadata(meta, user['user_id'])
                    processed_tracks.append(meta)

                    if upload_per_track:
                        await track_upload(meta, user)
                else:
                    try: os.remove(final_path)
                    except: pass

        except Exception as e:
            LOGGER.error(f"Skip track playlist ({i}): {e}")
            continue

    if not processed_tracks:
        raise Exception("Gagal mengunduh isi playlist (Semua lagu gagal).")

    meta_playlist['tracks'] = processed_tracks
    
    if playlist_zip:
        await edit_message(user['bot_msg'], f"🗜️ **Zipping:** Menyiapkan {len(processed_tracks)} lagu...")
        
        thumb_url = getattr(playlist_info, 'small_cover_url', None) or meta_playlist.get('cover')
        
        if thumb_url:
             zip_thumb_path = await create_cover_file(thumb_url, meta_playlist, thumbnail=True)
             # [FIX] Ganti 'thumb' menjadi 'thumbnail'
             meta_playlist['thumbnail'] = zip_thumb_path
             
             if meta_playlist.get('cover'):
                 try:
                     large_cover = await create_cover_file(meta_playlist['cover'], meta_playlist, thumbnail=False)
                     shutil.copy(large_cover, os.path.join(user_folder, "cover.jpg"))
                 except: pass

        zip_path = await zip_handler(user_folder)
        meta_playlist['zip_path'] = zip_path
        
        await edit_message(user['bot_msg'], "⬆️ **Uploading Zip...**")
        await playlist_upload(meta_playlist, user)
    
    elif not playlist_zip:
        await edit_message(user['bot_msg'], "✅ **Playlist Upload Complete!**")


async def process_artist(client, artist_id, user):
    msg = user.get('bot_msg')
    await edit_message(msg, "⚠️ **Info:** Download Artis belum didukung penuh. Silakan download per Album.")


# --- HELPER MAPPING ---
def map_spotify_to_bot_metadata(track_info, user, is_episode=False):
    # Ambil Cover
    cover_url = track_info.cover_url
    
    # Ambil Tanggal
    rel_date = track_info.release_date or ""
    year = rel_date[:4] if rel_date else ""
    
    # Ambil Tags
    tags = track_info.tags
    t_num = getattr(tags, 'track_number', "1")
    t_tot = getattr(tags, 'total_tracks', "1")
    d_num = getattr(tags, 'disc_number', "1")
    alb_artist = getattr(tags, 'album_artist', ["Unknown"])[0] if getattr(tags, 'album_artist') else "Unknown"

    # --- PERBAIKAN GENRE ---
    # Jika genres ada isinya, gabung dengan koma.
    # Jika kosong, baru fallback ke "Pop" atau "Unknown"
    genre_str = "Pop"
    if track_info.genres and len(track_info.genres) > 0:
        genre_str = ", ".join(track_info.genres)
    
    meta = {
        'title': track_info.name,
        'artist': track_info.artists[0] if track_info.artists else "Unknown",
        'album': track_info.album,
        'albumartist': alb_artist,
        'date': year,
        'release_date': rel_date,
        'tracknumber': str(t_num),
        'totaltracks': str(t_tot),
        'discnumber': str(d_num),
        'totalvolumes': "1",
        
        # Metadata Dinamis
        'genre': genre_str,           # <--- Genre Asli
        'label': track_info.label,    # <--- Label Asli
        'copyright': track_info.copyright, # <--- Copyright Asli
        'isrc': track_info.isrc,      # <--- ISRC Asli
        'organization': track_info.label, # Backup untuk Label
        
        'duration': track_info.duration, 
        'quality': "High (320kbps)",
        'provider': "Spotify",
        'explicit': track_info.explicit,
        'type': 'track',
        'cover': cover_url,
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{user['r_id']}-temp/"
    }
    
    if is_episode:
        meta['type'] = 'episode'
        meta['genre'] = "Podcast"
        
    return meta
