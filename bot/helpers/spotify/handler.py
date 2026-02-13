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


def fetch_artist_genre(client, artist_id):
    """Helper untuk mengambil Genre dari Artist ID"""
    try:
        if not artist_id: return None
        
        # Ambil info artis dari API (gunakan fungsi yang sudah ada di spotify_api.py)
        # Note: Kita ambil raw dict atau object ArtistInfo
        # get_artist_info di spotify_api.py mengembalikan object ArtistInfo, 
        # tapi kita butuh akses ke raw genres yang mungkin tidak terekspos di object tersebut
        # atau kita perlu modifikasi sedikit cara panggilnya.
        
        # Kita panggil get_artist_info, lalu cek atributnya atau panggil API manual jika perlu.
        # Namun, cara termudah dan teraman sesuai kode Anda:
        
        # Gunakan client.get_artist_info yang sudah Anda punya
        artist_obj = client.get_artist_info(artist_id)
        
        # Karena class ArtistInfo di spotify_api.py tidak menyimpan field 'genres',
        # kita harus sedikit 'mengintip' atau memodifikasi.
        # TAPI, ada cara lain: pakai get_several_artists (raw json) jika hanya butuh genre.
        
        raw_artists = client.get_several_artists([artist_id])
        if raw_artists and raw_artists[0]:
            genres = raw_artists[0].get('genres', [])
            if genres:
                # Ambil genre pertama dan ubah jadi Title Case (misal: "indie pop" -> "Indie Pop")
                return genres[0].title()
                
    except Exception as e:
        LOGGER.warning(f"Gagal mengambil genre: {e}")
    
    return None


async def process_track(client, track_id, user, is_episode=False):
    msg = user.get('bot_msg')
    await edit_message(msg, f"⬇️ **Spotify:** Mengunduh {'Episode' if is_episode else 'Lagu'}...")

    try:
        # 1. Ambil Info Track/Episode
        if is_episode:
             track_info = client.get_episode_info(track_id, "HIGH", None)
        else:
             track_info = client.get_track_info(track_id, "HIGH", None)
             
        if not track_info:
            raise Exception("Gagal mengambil metadata.")

        # 2. Download Audio Stream
        download_result = None
        if is_episode:
             download_result = client.get_episode_download(track_id=track_id, quality_tier="HIGH")
        else:
             download_result = client.get_track_download(track_id=track_id, quality_tier="HIGH")

        if not download_result or not download_result.temp_file_path:
            raise Exception("Gagal mengunduh stream audio.")

        # 3. [FIX GENRE] Ambil Genre dari Artis (Jika bukan episode)
        fetched_genre = None
        if not is_episode and track_info.artist_id:
            fetched_genre = fetch_artist_genre(client, track_info.artist_id)

        # 4. Map Metadata (Pass fetched_genre)
        meta = map_spotify_to_bot_metadata(track_info, user, is_episode, custom_genre=fetched_genre)
        
        # 5. Setup Nama File & Folder
        # Bersihkan karakter ilegal pada nama file
        clean_artist = meta['artist'].replace("/", "_")
        clean_title = meta['title'].replace("/", "_")
        final_filename = f"{clean_artist} - {clean_title}.ogg"
        
        # Gunakan .get() untuk r_id agar aman
        r_id = user.get('r_id', 'unknown')
        user_folder = f"{Config.DOWNLOAD_BASE_DIR}/{r_id}/Spotify"
        os.makedirs(user_folder, exist_ok=True)
        
        final_path = os.path.join(user_folder, final_filename)
        shutil.move(download_result.temp_file_path, final_path)
        
        meta['filepath'] = final_path
        meta['folderpath'] = user_folder

        if os.path.getsize(final_path) < 1024:
            raise Exception("File audio korup/kosong (0 bytes).")

        # 6. Buat Thumbnail
        if meta.get('cover'):
            thumb_path = await create_cover_file(meta['cover'], meta, thumbnail=True)
            meta['thumbnail'] = thumb_path
            
        await edit_message(msg, "🏷 **Spotify:** Menulis Metadata...")
        
        # 7. [FIX LYRICS] Kirim User ID yang Valid
        # Penting: lyrics_manager butuh user_id untuk fetch lirik
        user_id_val = user.get('user_id') or user.get('id')
        await set_metadata(meta, user_id_val)

        await edit_message(msg, "⬆️ **Spotify:** Mengunggah...")
        await track_upload(meta, user)

    except Exception as e:
        raise e


async def process_album(client, album_id, user):
    msg = user.get('bot_msg')
    await edit_message(msg, "🔍 **Spotify:** Mengambil Info Album...")

    # 1. Ambil Info Album Global (Label, Copyright, UPC ada di sini)
    album_info = client.get_album_info(album_id)
    if not album_info:
        raise Exception("Album tidak ditemukan.")

    tracks = album_info.tracks
    total = len(tracks)
    
    await edit_message(msg, f"⬇️ **Spotify:** Album ditemukan: {album_info.name}\nJumlah Lagu: {total}")
    
    # 2. Ambil Genre dari Artis Utama (Cukup 1x request untuk efisiensi)
    album_genre = None
    try:
        if tracks and tracks[0].artist_id:
            album_genre = fetch_artist_genre(client, tracks[0].artist_id)
            if album_genre: LOGGER.info(f"Genre ditemukan: {album_genre}")
    except Exception as e:
        LOGGER.warning(f"Gagal mengambil genre album: {e}")

    playlist_zip, album_zip, artist_zip, art_poster = fetch_zip_settings(user)

    # 3. Setup Metadata Album & Folder
    r_id = user.get('r_id', 'unknown')
    
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
        'genre': album_genre if album_genre else "Pop",
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{r_id}-temp/"
    }
    
    # 4. Siapkan Thumbnail Album
    if meta_album.get('cover'):
         poster_path = await create_cover_file(meta_album['cover'], meta_album, thumbnail=False)
         meta_album['thumbnail'] = poster_path

    poster_key = f'poster_album_{album_id}'
    if user.get(poster_key):
        meta_album['poster_msg'] = user[poster_key]
    else:
        meta_album['poster_msg'] = await post_art_poster(user, meta_album)
        user[poster_key] = meta_album['poster_msg']

    processed_tracks = []
    user_folder = f"{Config.DOWNLOAD_BASE_DIR}/{r_id}/Spotify/{album_info.name}"
    os.makedirs(user_folder, exist_ok=True)
    meta_album['folderpath'] = user_folder

    upload_per_track = not album_zip

    # 5. Looping Download Track
    for i, track in enumerate(tracks):
        try:
            current_num = i + 1
            await edit_message(msg, f"⬇️ **Spotify Album:** ({current_num}/{total})\n`{track.name}`")
            
            download_result = client.get_track_download(track_id=track.id, quality_tier="HIGH")
            
            if download_result and download_result.temp_file_path:
                
                # [FIX UTAMA: ISRC ALBUM]
                # API Album tidak memberikan ISRC di list track.
                # Kita wajib request Full Track Info untuk mendapatkan ISRC-nya.
                full_track_info = None
                try:
                    full_track_info = client.get_track_info(track.id, "HIGH", None)
                except Exception as e:
                    LOGGER.warning(f"Gagal fetch full track info untuk {track.name}: {e}")

                # Gunakan info lengkap jika berhasil, jika gagal pakai info sederhana dari album
                target_track = full_track_info if full_track_info else track
                
                # Pass genre album yang sudah diambil di awal
                meta = map_spotify_to_bot_metadata(target_track, user, custom_genre=album_genre)
                
                # Pastikan Metadata Album konsisten (karena get_track_info single kadang meleset di totaltracks)
                meta['totaltracks'] = str(total)
                meta['album'] = album_info.name # Paksa nama album agar rapi sesuai folder
                
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
                    
                    # [FIX LYRICS] Kirim User ID Valid ke set_metadata
                    user_id_val = user.get('user_id') or user.get('id')
                    await set_metadata(meta, user_id_val)
                    
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
    
    # 7. Handling Upload ZIP (Jika Mode Album)
    if album_zip:
        await edit_message(user['bot_msg'], f"🗜️ **Zipping:** Menyiapkan {len(processed_tracks)} lagu...")
        
        # Gunakan cover kecil (small_cover_url) untuk thumbnail ZIP agar ringan
        thumb_url = getattr(album_info, 'small_cover_url', None) or meta_album.get('cover')
        
        if thumb_url:
             zip_thumb_path = await create_cover_file(thumb_url, meta_album, thumbnail=True)
             meta_album['thumbnail'] = zip_thumb_path
             
             # Simpan cover.jpg HD di dalam ZIP
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
    r_id = user.get('r_id', 'unknown')

    meta_playlist = {
        'title': playlist_info.name,
        'artist': playlist_info.creator,
        'cover': playlist_info.cover_url,
        'type': 'playlist',
        'provider': 'Spotify',
        'totaltracks': str(total),
        'totalvolumes': "1",
        'quality': "High (320kbps)",
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

    processed_tracks = []
    upload_per_track = not playlist_zip

    for i, track in enumerate(tracks):
        try:
            if not track or not track.id: continue
            
            current_num = i + 1
            await edit_message(msg, f"⬇️ **Spotify Playlist:** ({current_num}/{total})\n`{track.name}`")
            
            download_result = client.get_track_download(track_id=track.id, quality_tier="HIGH")
            
            if download_result and download_result.temp_file_path:
                
                # [FIX UTAMA PLAYLIST]
                # Panggil Full Track Info agar Label/UPC/Copyright terambil dari Album
                full_track_info = client.get_track_info(track.id, "HIGH", None)
                
                # Gunakan info lengkap jika berhasil, jika gagal pakai info sederhana dari playlist
                target_info = full_track_info if full_track_info else track
                
                # Mapping Metadata
                meta = map_spotify_to_bot_metadata(target_info, user)
                
                # Proses File
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
                        meta['thumbnail'] = t_path
                    
                    user_id_val = user.get('user_id') or user.get('id')
                    await set_metadata(meta, user_id_val)
                    
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
    
    # ... (Sisa kode zip upload sama)
    meta_playlist['tracks'] = processed_tracks
    
    if playlist_zip:
        await edit_message(user['bot_msg'], f"🗜️ **Zipping:** Menyiapkan {len(processed_tracks)} lagu...")
        thumb_url = getattr(playlist_info, 'small_cover_url', None) or meta_playlist.get('cover')
        if thumb_url:
             zip_thumb_path = await create_cover_file(thumb_url, meta_playlist, thumbnail=True)
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


def map_spotify_to_bot_metadata(track_info, user, is_episode=False, custom_genre=None):
    cover_url = track_info.cover_url
    
    # Handling Explicit
    explicit_val = track_info.explicit if track_info.explicit is not None else False
    
    # Handling Release Date
    rel_date = "Unknown"
    if track_info.tags and hasattr(track_info.tags, 'release_date') and track_info.tags.release_date:
        rel_date = str(track_info.tags.release_date)
    elif hasattr(track_info, 'release_year') and track_info.release_year:
        rel_date = str(track_info.release_year)
        
    tags = track_info.tags
    final_genre = custom_genre if custom_genre else "Pop"

    # Persiapan Data Metadata (Safe Get)
    # Menggunakan getattr agar aman jika field belum ada di TrackInfo
    isrc = getattr(track_info, 'isrc', '')
    upc = getattr(track_info, 'upc', '')
    label = getattr(track_info, 'label', '')
    copyright_txt = getattr(track_info, 'copyright', '')
    
    # [FIX COMPOSER] Gunakan Nama Artis sebagai Composer (Fallback)
    # Karena Spotify API Track tidak menyediakan Composer secara langsung.
    composer_val = track_info.artists[0] if track_info.artists else "Unknown"

    meta = {
        'title': track_info.name,
        'artist': track_info.artists[0] if track_info.artists else "Unknown",
        'album': track_info.album,
        'albumartist': getattr(tags, 'album_artist', "Unknown") if tags else "Unknown",
        
        # Date & Year
        'date': str(track_info.release_year) if track_info.release_year else "",
        'release_date': rel_date,
        
        # Tracks & Discs
        'tracknumber': str(getattr(tags, 'track_number', '1')),
        'totaltracks': str(getattr(tags, 'total_tracks', '1')),
        'discnumber': str(getattr(tags, 'disc_number', '1')),
        'volume': str(getattr(tags, 'disc_number', '1')), 
        'totalvolumes': "1",
        'totalvolume': "1", # Tambahan agar kompatibel dengan metadata.py
        
        # Genre
        'genre': final_genre,
        
        # Technical
        'duration': track_info.duration, 
        'quality': "High (320kbps)",
        'provider': "Spotify",
        
        # [FIX] METADATA LENGKAP
        'explicit': explicit_val,
        'isrc': isrc,
        'upc': upc,
        'copyright': copyright_txt,
        'publisher': label,
        'organization': label,
        
        # [FIX COMPOSER]
        'composer': composer_val,
        'producer': composer_val, # Producer juga kita isi Artist agar tidak kosong
        
        # [FIX LYRICS] Inisialisasi None, nanti diisi oleh metadata.py -> lyrics_manager
        'lyrics': None, 

        'type': 'track',
        'cover': cover_url,
        # Menggunakan .get() agar lebih aman daripada user['r_id']
        'tempfolder': f"{Config.DOWNLOAD_BASE_DIR}/{user.get('r_id', 'unknown')}-temp/"
    }
    
    if is_episode:
        meta['type'] = 'episode'
        meta['album'] = track_info.album 
        meta['artist'] = track_info.artists[0] 
        
    return meta
