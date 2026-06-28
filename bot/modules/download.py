# [GANTI FILE: bot/modules/download.py]

from pyrogram.types import Message
from pyrogram import Client, filters
import asyncio
import collections
import traceback
import random
import aiohttp
import time

import bot.helpers.utils as utils

USER_SEMAPHORES = collections.defaultdict(lambda: asyncio.Semaphore(1))
BOT_UPTIME = time.time()

from bot import CMD
from bot.logger import LOGGER
import bot.helpers.translations as lang

from bot import BOT_QOBUZ_CLIENTS
from bot.tgclient import aio

# [TAMBAHAN] Import manager untuk cek akun private
try:
    from bot.helpers.qobuz.qopy import qobuz_manager
except ImportError:
    qobuz_manager = None

# --- IMPOR MANAJER LAYANAN ---

# 1. Deezer
try:
    from bot.helpers.deezer.manager import deezer_manager
    from bot.helpers.deezer.manager import DeezerError
except ImportError:
    deezer_manager = None
    class DeezerError(Exception): pass

# 2. Beatport
try:
    from bot.helpers.beatport.manager import beatport_manager
except ImportError:
    beatport_manager = None

# 3. Tidal
try:
    from bot.helpers.tidal.manager import tidal_manager
except ImportError:
    tidal_manager = None

# 4. KKBox
try:
    from bot.helpers.kkbox.manager import kkbox_manager
except ImportError:
    kkbox_manager = None

# 5. Beatsource
try:
    from bot.helpers.beatsource.manager import beatsource_manager
except ImportError:
    beatsource_manager = None

# 6. Soundcloud
try:
    from bot.helpers.soundcloud.manager import soundcloud_manager
except ImportError:
    soundcloud_manager = None

# 7. Moov
try:
    from bot.helpers.moov.manager import moov_manager
except ImportError:
    moov_manager = None

# 8. Idagio
try:
    from bot.helpers.idagio.manager import idagio_manager
except ImportError:
    idagio_manager = None

# 9. Nugs.net
try:
    from bot.helpers.nugs.manager import nugs_manager
except ImportError:
    nugs_manager = None

# 10. Bugs
try:
    from bot.helpers.bugs.manager import bugs_manager
    from bot.helpers.bugs.manager import BugsError
except ImportError:
    bugs_manager = None
    class BugsError(Exception): pass

# 11. HIGHRESAUDIO
try:
    from bot.helpers.highresaudio.manager import highresaudio_manager, HighResAudioError
except ImportError:
    highresaudio_manager = None
    class HighResAudioError(Exception): pass

# 12. JioSaavn
try:
    from bot.helpers.jiosaavn.manager import jiosaavn_manager
except ImportError:
    jiosaavn_manager = None

# 13. Gaana
try:
    from bot.helpers.gaana.manager import gaana_manager
except ImportError:
    gaana_manager = None

# 14. Bandcamp
try:
    from bot.helpers.bandcamp.manager import bandcamp_manager
except ImportError:
    bandcamp_manager = None

# 15. LivePhish
try:
    from bot.helpers.livephish.manager import livephish_manager
except ImportError:
    livephish_manager = None

# 16. BeatStars
try:
    from bot.helpers.beatstars.manager import beatstars_manager
except ImportError:
    beatstars_manager = None

# 17. Khinsider
try:
    from bot.helpers.khinsider.manager import khinsider_manager
except ImportError:
    khinsider_manager = None

# 18. Amazon
try:
    from bot.helpers.amazon.manager import amazon_manager
except ImportError:
    amazon_manager = None

# 19. Genie
try:
    from bot.helpers.genie.manager import genie_manager
except ImportError:
    genie_manager = None


# --- IMPOR HANDLER LAYANAN ---

from ..helpers.soundcloud.handler import start_soundcloud
from ..helpers.utils import cleanup
from ..helpers.qobuz.handler import start_qobuz
from ..helpers.tidal.handler import start_tidal
from ..helpers.deezer.handler import start_deezer
from ..helpers.beatport.handler import start_beatport

# KKBox
try:
    from ..helpers.kkbox.handler import start_kkbox
except ImportError:
    async def start_kkbox(*args, **kwargs):
        raise NotImplementedError("Modul KKBox belum diimplementasikan.")

# Beatsource
from bot.helpers.beatsource.handler import start_beatsource

# Moov
try:
    from ..helpers.moov.handler import start_moov
except ImportError:
    async def start_moov(*args, **kwargs):
        raise NotImplementedError("Modul Moov belum diimplementasikan.")

# Idagio
try:
    from ..helpers.idagio.handler import start_idagio
except ImportError:
    async def start_idagio(*args, **kwargs):
        raise NotImplementedError("Modul Idagio belum diimplementasikan.")

# Nugs.net
try:
    from ..helpers.nugs.handler import start_nugs
except ImportError:
    async def start_nugs(*args, **kwargs):
        raise NotImplementedError("Modul Nugs.net belum diimplementasikan.")

# Bugs
try:
    from ..helpers.bugs.handler import start_bugs
except ImportError:
    async def start_bugs(*args, **kwargs):
        raise NotImplementedError("Modul Bugs belum diimplementasikan.")

# HIGHRESAUDIO
try:
    from bot.helpers.highresaudio.handler import start_highresaudio
except ImportError:
    async def start_highresaudio(*args, **kwargs):
        raise NotImplementedError("Modul HIGHRESAUDIO belum diimplementasikan.")

# JioSaavn
try:
    from ..helpers.jiosaavn.handler import start_jiosaavn
except ImportError as e:
    err_jio = str(e)
    LOGGER.error(f"Gagal Import JioSaavn Handler: {err_jio}")
    async def start_jiosaavn(*args, **kwargs):
        raise NotImplementedError(f"Modul JioSaavn Rusak: {err_jio}")

# Gaana
try:
    from ..helpers.gaana.handler import start_gaana
except ImportError as e:
    err_gaana = str(e)
    LOGGER.error(f"Gagal Import Gaana Handler: {err_gaana}")
    async def start_gaana(*args, **kwargs):
        raise NotImplementedError(f"Modul Gaana Rusak: {err_gaana}")

# Bandcamp
try:
    from ..helpers.bandcamp.handler import start_bandcamp
except ImportError as e:
    err_bc = str(e)
    LOGGER.error(f"Gagal Import Bandcamp Handler: {err_bc}")
    async def start_bandcamp(*args, **kwargs):
        raise NotImplementedError(f"Modul Bandcamp Rusak: {err_bc}")

# LivePhish
try:
    from ..helpers.livephish.handler import start_livephish
except Exception as e:
    LOGGER.error(f"GAGAL IMPORT LIVEPHISH: {e}") 
    import traceback
    LOGGER.error(traceback.format_exc())
    async def start_livephish(*args, **kwargs):
        raise NotImplementedError("Modul LivePhish belum diimplementasikan.")

# BeatStars
try:
    from ..helpers.beatstars.handler import start_beatstars
except ImportError as e:
    err_bs = str(e)
    LOGGER.error(f"Gagal Import BeatStars Handler: {err_bs}")
    async def start_beatstars(*args, **kwargs):
        raise NotImplementedError(f"Modul BeatStars Rusak: {err_bs}")

# Khinsider
try:
    from ..helpers.khinsider.handler import start_khinsider
except ImportError:
    async def start_khinsider(*args, **kwargs):
        raise NotImplementedError("Modul Khinsider belum diimplementasikan.")

# Amazon
try:
    from bot.helpers.amazon.handler import start_amazon
except Exception as e:
    from bot.logger import LOGGER
    LOGGER.error(f"Gagal memuat modul Amazon Handler: {e}")
    async def start_amazon(*args, **kwargs):
        raise NotImplementedError(f"Modul Amazon Music gagal dimuat karena: {e}")

# Genie
try:
    from ..helpers.genie.handler import start_genie
except ImportError as e:
    from bot.logger import LOGGER
    LOGGER.error(f"Gagal memuat modul Genie Handler: {e}")
    async def start_genie(*args, **kwargs):
        raise NotImplementedError(f"Modul Genie gagal dimuat.")


from ..helpers.message import send_message, check_user, fetch_user_details, edit_message


# --- FUNGSI UNTUK MEMBUKA SHORTLINK ---
async def resolve_shortlink(link: str) -> str:
    """
    Membuka shortlink dengan penanganan Manual Redirect untuk menangkap fragment (#) URL.
    """
    # --- UPDATE: MENAMBAHKAN 'bsta.rs' KE DAFTAR DOMAIN TARGET ---
    target_domains = [
        "2nu.gs", "app.moov.hk", "moov.hk/r/", "bit.ly", "t.co", 
        "youtu.be", "bandcamp.com", "livephi.sh", "bsta.rs"
    ]
    # -------------------------------------------------------------
    
    if any(d in link for d in target_domains) or "bandcamp.com" in link or "livephi.sh" in link:
        try:
            # Gunakan User-Agent Desktop
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            # --- [FIX TIMEOUT] BATASI HANYA 15 DETIK ---
            timeout = aiohttp.ClientTimeout(total=15.0)
            async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                current_url = link
                # Lakukan Loop Redirect Manual (Max 5 kali)
                for _ in range(5):
                    async with session.get(current_url, allow_redirects=False) as resp:
                        if 'Location' in resp.headers:
                            new_url = resp.headers['Location']
                            
                            # Logika Khusus Moov
                            if "moov.hk" in new_url and ("/album/" in new_url or "/song/" in new_url):
                                LOGGER.info(f"Shortlink Detected Target: {link} -> {new_url}")
                                return new_url
                            
                            # Handle Relative URL
                            if new_url.startswith("/"):
                                from urllib.parse import urljoin
                                new_url = urljoin(current_url, new_url)
                            
                            current_url = new_url
                        else:
                            break
                
                LOGGER.info(f"Shortlink Final: {link} -> {current_url}")
                return current_url

        except Exception as e:
            LOGGER.error(f"Gagal me-resolve shortlink {link}: {e}")
            return link 
    return link


async def run_download_task(link: str, user: dict):
    chat_id = user['chat_id']
    notif_msg = None
    
    # --- [FITUR ANTI-SPAM] ANTREAN PRIBADI PER-USER ---
    user_sem = USER_SEMAPHORES[chat_id]
    
    # Jika 2 slot pengguna ini sudah penuh, beri tahu bahwa dia masuk antrean pribadi
    if user_sem.locked():
        notif_msg = await send_message(user, f"⏳ **Entering Personal Queue...**\nYou are currently performing 1 task. This link will be automatically processed afterward.\n`{link}`")
    
    # Menunggu slot pribadi kosong (User lain TIDAK akan terpengaruh)
    async with user_sem:
        # Hapus pesan "Masuk Antrean" ketika tugas ini akhirnya mulai berjalan
        if notif_msg:
            try: await notif_msg.delete()
            except: pass
            
        task_successful = False
        
        try:
            user['bot_msg'] = await send_message(user, 'Mempersiapkan tugas...')
            
            # --- PUSATKAN PESAN STATUS ---
            import bot.helpers.utils as utils
            if chat_id in utils.GLOBAL_UI_MSG:
                try: 
                    # --- [FIX GHOST PANEL] HAPUS BRUTAL VIA CLIENT ---
                    from bot.tgclient import aio
                    await aio.delete_messages(chat_id, utils.GLOBAL_UI_MSG[chat_id].id)
                except Exception: 
                    pass
            utils.GLOBAL_UI_MSG[chat_id] = user['bot_msg']
            # -----------------------------------------------------------------
            
            import hashlib
            import time
            cancel_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
            
            if cancel_id in utils.GLOBAL_CANCEL_DICT:
                raise asyncio.CancelledError("DIBATALKAN_PENGGUNA")

            # --- DAFTARKAN KE PAPAN GLOBAL SECARA LANGSUNG ---
            utils.GLOBAL_TASKS[cancel_id] = {
                'action': 'Processing',
                'type': 'Task',
                'title': link,
                'since': '', 
                'progress_bar': '', 
                'percentage': '',
                'processed_label': 'Status',
                'processed': 'Fetching metadata...',
                'speed': '',
                'machine': 'Initializing',
                'mode': '',
                'cancel_id': cancel_id,
                'dl_speed': '0B/s',
                'ul_speed': '0B/s',
                'speed_dl_raw': 0,
                'speed_ul_raw': 0,
                'user_id': chat_id,
                'timestamp': time.time(),
                'is_queue': False
            }

            await edit_message(user['bot_msg'], '🚀 Starting task...')
            
            # 1. Lindungi resolve_shortlink dengan tambahan pengaman
            try:
                resolved = await asyncio.wait_for(resolve_shortlink(link), timeout=20.0)
                if resolved != link:
                     link = resolved
                     user['link'] = link
            except asyncio.TimeoutError:
                LOGGER.warning(f"Timeout saat me-resolve shortlink: {link}, lanjut pakai link asli.")

            # --- [FIX SEMAPHORE] BATAS WAKTU DIPERPANJANG UNTUK PLAYLIST RAKSASA ---
            try:
                # Memaksa agar tugas seberat apa pun tidak boleh berjalan lebih dari 6 jam (21600 detik)
                await asyncio.wait_for(start_link(link, user), timeout=21600.0)
                task_successful = True
            except asyncio.TimeoutError:
                # Melemparkan error ke blok 'except Exception as e:' agar diproses dengan rapi
                raise Exception("Tugas memakan waktu terlalu lama (> 6 Jam) dan diputus paksa oleh sistem agar tidak memblokir antrean.")
            # -----------------------------------------------------------------------
                
        except asyncio.CancelledError:
            # HAPUS BARIS INI: from bot.logger import LOGGER
            LOGGER.info(f"Tugas untuk {user['user_id']} dibatalkan.")
            try: await edit_message(user['bot_msg'], "🛑 Tugas dibatalkan.")
            except: pass
            await asyncio.sleep(5) 
                
        except Exception as e:
            # HAPUS BARIS INI: from bot.logger import LOGGER
            import traceback
            error_str = str(e)
            is_handled_error = False
            
            if "not available in any" in error_str or \
               "Maaf, tidak ada akun" in error_str or \
               "NotImplementedError" in error_str or \
               "URL Deezer tidak valid" in error_str or \
               "Item tidak tersedia di semua" in error_str or \
               "Track not available" in error_str or \
               "Stream key kosong" in error_str or \
               "Region Locked" in error_str or \
               "Link Bandcamp tidak valid" in error_str or \
               "Link tidak valid" in error_str or \
               "Link tidak dikenali" in error_str or \
               "halaman sistem" in error_str or \
               "Gagal mengambil profil artis" in error_str or \
               "404" in error_str or \
               "HighResAudioError" in error_str or \
               "DeezerError" in error_str or \
               "BugsError" in error_str: 
                is_handled_error = True
            
            error_message = f"Tugas Gagal: {e}" if is_handled_error else f"Tugas Gagal: Terjadi error.\n`{e}`"

            if is_handled_error:
                 LOGGER.warning(f"Download Task Ditolak (Handled): {e}")
            else:
                 LOGGER.error(f"Error fatal di run_download_task: {e}\n{traceback.format_exc()}")

            try: await edit_message(user['bot_msg'], error_message)
            except: pass 
                
        finally:
            import bot.helpers.utils as utils
            # Catatan: Pastikan fungsi cleanup ada di file/import Anda
            await cleanup(user)
            try:
                if 'bot_msg' in user:
                    import hashlib
                    final_task_id = hashlib.md5(str(user['bot_msg'].id).encode()).hexdigest()[:16]
                    
                    utils.GLOBAL_TASKS.pop(final_task_id, None)

                    # --- [PERBAIKAN ERROR TERTEMPA RADAR] ---
                    # Keluarkan pesan ini dari memori Radar LEBIH AWAL jika tugas gagal,
                    # agar pesan error tidak tertimpa oleh teks status Radar ("Tidak ada task...").
                    current_radar = utils.GLOBAL_UI_MSG.get(user['chat_id'])
                    if current_radar and current_radar.id == user['bot_msg'].id:
                        if not task_successful:
                            utils.GLOBAL_UI_MSG.pop(user['chat_id'], None)
                            utils.GLOBAL_UI_PAGES.pop(user['chat_id'], None)
                    # ----------------------------------------
                    
                    # Update radar terakhir kali untuk semua orang (Pesan error tidak ikut ter-update)
                    for cid, m in list(utils.GLOBAL_UI_MSG.items()):
                        c_page = utils.GLOBAL_UI_PAGES.get(cid, 1)
                        g_text, g_markup = utils.get_status_text(page=c_page)
                        try: await edit_message(m, g_text, g_markup, False)
                        except: pass

                    # --- [FIX GHOST PANEL] PASTIKAN PESAN TELEGRAM DIHAPUS ---
                    try: 
                        # Hapus pesan otomatis HANYA JIKA prosesnya sukses 100%
                        if task_successful:
                            await user['bot_msg'].delete()
                    except: 
                        pass
                    
                    # Bersihkan sisa memori radar jika tugas sukses
                    if current_radar and current_radar.id == user['bot_msg'].id:
                        if task_successful:
                            utils.GLOBAL_UI_MSG.pop(user['chat_id'], None)
                            utils.GLOBAL_UI_PAGES.pop(user['chat_id'], None)
                    # ---------------------------------------------------------
            except:
                pass


@Client.on_message(filters.command(CMD.DOWNLOAD))
async def download_track(c, msg:Message):
    if await check_user(msg=msg):
        
        text_content = msg.reply_to_message.text if msg.reply_to_message else msg.text

        link = ""
        booklet_only = False # <-- Inisialisasi flag
        
        try:
            parts = text_content.split()
            
            # --- DETEKSI FLAG -b ---
            if "-b" in parts:
                booklet_only = True
                parts.remove("-b") # Hapus dari array agar tidak mengganggu parser link
            # -----------------------

            for part in parts:
                if part.startswith("http://") or part.startswith("https://"):
                    link = part 
                    break 

            if not link:
                raise IndexError
                
        except IndexError:
            return await send_message(msg, lang.s.ERR_NO_LINK)

        if not link:
            return await send_message(msg, lang.s.ERR_LINK_RECOGNITION)
        
        user = await fetch_user_details(msg, reply=bool(msg.reply_to_message))
        
        try:
            resolved_link = await resolve_shortlink(link)
            if resolved_link != link:
                link = resolved_link 
        except Exception: pass 
        
        user['link'] = link
        user['booklet_only'] = booklet_only # <-- Simpan flag ke dalam user dict
        
        asyncio.create_task(run_download_task(link, user))
        

async def start_link(link: str, user: dict) -> None:
    tidal = ["https://tidal.com", "https://listen.tidal.com", "http://www.tidal.com", "tidal.com", "listen.tidal.com"]
    deezer = ["https://link.deezer.com", "https://deezer.com", "deezer.com", "https://www.deezer.com", "link.deezer.com"]
    qobuz = ["https://play.qobuz.com", "https://open.qobuz.com", "https://www.qobuz.com"]
    spotify = ["https://open.spotify.com"]
    beatport = ["https://www.beatport.com", "http://www.beatport.com", "beatport.com"]
    beatsource = ["https://www.beatsource.com", "beatsource.com"]
    
    soundcloud = [
        "https://soundcloud.com", "soundcloud.com", 
        "https://on.soundcloud.com", "on.soundcloud.com",
        "https://m.soundcloud.com", "m.soundcloud.com"
    ]
    
    kkbox = ["https://play.kkbox.com", "https://www.kkbox.com", "kkbox.com"]
    
    moov = ["https://moov.hk", "https://app.moov.hk", "moov.hk", "app.moov.hk"]
    
    idagio = ["https://www.idagio.com", "idagio.com", "https://app.idagio.com"]
    
    nugs = ["https://play.nugs.net", "play.nugs.net", "https://streamapi.nugs.net"]

    bugs = ["https://music.bugs.co.kr", "music.bugs.co.kr", "https://m.bugs.co.kr", "m.bugs.co.kr"]

    highresaudio = ["https://www.highresaudio.com", "highresaudio.com"]

    jiosaavn = ["https://www.jiosaavn.com", "jiosaavn.com"]

    gaana = ["https://gaana.com", "gaana.com"]

    livephish = ["https://plus.livephish.com", "https://www.livephish.com", "https://streamapi.livephish.com"]

    beatstars = ["https://www.beatstars.com", "beatstars.com", "https://main.v2.beatstars.com", "https://bsta.rs", "bsta.rs"]

    khinsider = ["https://downloads.khinsider.com", "downloads.khinsider.com", "http://downloads.khinsider.com"]

    amazon = ["https://music.amazon.com", "https://music.amazon.co.jp", "https://music.amazon.co.uk", "https://music.amazon.fr", "https://music.amazon.com.mx", "https://music.amazon.com.br", "https://music.amazon.de", "https://music.amazon.com.au", "https://music.amazon.ca", "https://music.amazon.it", "https://music.amazon.es", "https://music.amazon.com.ar", "https://music.amazon.com/es-ar", "https://music.amazon.com/en-ar", "https://music.amazon.in", "music.amazon"]

    genie = ["https://www.genie.co.kr", "genie.co.kr", "https://app.genie.co.kr"]
    
    # Blok TIDAL
    if link.startswith(tuple(tidal)):
        user['provider'] = 'Tidal'
        
        user_client = await tidal_manager.get_user_client(user['user_id'])
        
        if user_client:
            LOGGER.info(f"Tidal: Menggunakan akun PRIVATE untuk User {user['user_id']}")
            try:
                # --- [FIX] CEGAT AKUN FREE/INTRO PADA AKUN PRIVATE ---
                sub_type_upper = (user_client.sub_type or "").upper()
                if "FREE" in sub_type_upper or "INTRO" in sub_type_upper:
                    raise Exception(f"Akun Private berstatus {user_client.sub_type} (Limitasi). Harap gunakan akun langganan aktif.")
                # -----------------------------------------------------
                
                user['tidal_api'] = user_client
                await start_tidal(link, user)
                return 
            except Exception as e:
                LOGGER.warning(f"Tidal Private User {user['user_id']} gagal: {e}. Mencoba fallback ke Akun Global.")

        if not tidal_manager.clients:
            raise Exception("Maaf, tidak ada akun Tidal Global yang aktif dan Anda tidak memiliki akun Private.")

        clients_list = list(tidal_manager.clients)
        if len(clients_list) > 1:
            random.shuffle(clients_list)
            
        last_error = None
        
        for client in clients_list:
            try:
                # --- [FIX] BLOKIR AKUN FREE & INTRO ---
                sub_type_upper = (client.sub_type or "").upper()
                if "FREE" in sub_type_upper or "INTRO" in sub_type_upper:
                    raise Exception(f"Akun berstatus {client.sub_type} (Limitasi). Beralih ke akun Premium...")
                # --------------------------------------
                
                user['tidal_api'] = client
                await start_tidal(link, user)
                LOGGER.info(f"Tidal: Unduhan berhasil menggunakan akun Global User ID {client.user_id}")
                return 
            except Exception as e:
                error_str = str(e).lower()
                
                if 'asset is not ready' in error_str or \
                   'not available in your region' in error_str or \
                   'region-locked' in error_str or \
                   'berstatus' in error_str:
                    
                    LOGGER.warning(f"Tidal: Akun Global {client.user_id} gagal (Region Lock / Free): {e}. Mencoba akun berikutnya...")
                    last_error = e
                    continue 
                else:
                    LOGGER.error(f"Tidal: Akun Global {client.user_id} gagal (Fatal): {e}")
                    raise e

        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun Tidal Global yang dicoba (Region Lock). Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh Tidal karena alasan yang tidak diketahui.")
        
    # Blok DEEZER
    elif link.startswith(tuple(deezer)):
        user['provider'] = 'Deezer'
        
        # 1. Ambil Akun User (Prioritas)
        user_clients = []
        if deezer_manager.has_private_session(user['user_id']):
            try:
                user_clients = await deezer_manager.get_user_clients(user['user_id'])
            except Exception as e:
                LOGGER.error(f"Gagal memuat akun user Deezer: {e}")

        # 2. Ambil Akun Global
        global_clients = deezer_manager.clients or []
        
        # Gabungkan (User dulu, baru Global)
        all_clients = user_clients + list(global_clients) # Convert ke list jika perlu
        
        if not all_clients:
            raise Exception("Maaf, tidak ada akun Deezer (Bot/Pribadi) yang aktif.")
        
        # Jika hanya global, acak. Jika ada user, biarkan urut (User 1, User 2, Global...)
        if not user_clients and len(global_clients) > 1:
            random.shuffle(all_clients)

        last_error = None
        for client in all_clients:
            try:
                user['deezer_api'] = client 
                await start_deezer(link, user)
                
                # Info Log
                u_label = client.user.get('USER', {}).get('BLOG_NAME', 'Unknown')
                LOGGER.info(f"Deezer: Unduhan berhasil menggunakan akun {u_label}")
                return 
            except Exception as e:
                error_str = str(e).lower()
                is_retryable = False
                
                if isinstance(e, DeezerError) or \
                   "not available" in error_str or \
                   "country" in error_str or \
                   "track token" in error_str: # Region lock usually
                    is_retryable = True

                if is_retryable:
                    LOGGER.warning(f"Deezer: Akun gagal (Region/Lock): {e}. Mencoba akun berikutnya...")
                    last_error = e
                    continue 
                else:
                    LOGGER.error(f"Deezer: Akun gagal (Fatal): {e}")
                    raise e 
                    
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(all_clients)}) akun Deezer. Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh Deezer karena alasan yang tidak diketahui setelah mencoba semua akun.")
        
    # Blok QOBUZ
    elif link.startswith(tuple(qobuz)):
        user['provider'] = 'Qobuz'

        # Cek apakah ada akun Global ATAU akun Private User
        has_private = False
        if qobuz_manager and qobuz_manager.has_private_session(user['user_id']):
            has_private = True
            
        if not BOT_QOBUZ_CLIENTS and not has_private:
            raise Exception("Maaf, tidak ada akun Qobuz bot yang aktif saat ini.")
        
        # Kumpulkan akun global (jika ada) untuk dikirim ke handler
        clients_list = []
        if BOT_QOBUZ_CLIENTS:
            clients_list = list(BOT_QOBUZ_CLIENTS.values())
            random.shuffle(clients_list)
            
        user['qobuz_clients_list'] = clients_list
        await start_qobuz(link, user)

    # Blok BEATPORT
    elif link.startswith(tuple(beatport)):
        user['provider'] = 'Beatport'
        
        if not beatport_manager.clients:
            raise Exception("Maaf, tidak ada akun Beatport bot yang aktif saat ini.")

        clients_list = random.sample(beatport_manager.clients, len(beatport_manager.clients))
        last_error = None
        for client in clients_list:
            try:
                user['beatport_api'] = client 
                await start_beatport(link, user)
                LOGGER.info(f"Beatport: Unduhan berhasil menggunakan akun.") 
                return 
            except Exception as e:
                error_str = str(e).lower()
                if "not available in your country" in error_str or \
                   "subscription" in error_str or \
                   "region locked" in error_str or \
                   "not available for streaming" in error_str or \
                   "tidak streamable" in error_str:
                    LOGGER.warning(f"Beatport: Akun gagal (Region/Sub Lock/Tidak Streamable): {e}. Mencoba akun berikutnya...")
                    last_error = e 
                    continue 
                else:
                    LOGGER.error(f"Beatport: Akun gagal (Fatal): {e}")
                    raise e 
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun Beatport yang dicoba. Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh Beatport karena alasan yang tidak diketahui setelah mencoba semua akun.")

    # Blok BEATSOURCE
    elif link.startswith(tuple(beatsource)):
        user['provider'] = 'Beatsource'
        
        if not beatsource_manager.clients:
            raise Exception("Maaf, tidak ada akun Beatsource bot yang aktif saat ini.")

        clients_list = random.sample(beatsource_manager.clients, len(beatsource_manager.clients))
        last_error = None

        for client in clients_list:
            try:
                user['beatsource_api'] = client 
                await start_beatsource(link, user)
                
                LOGGER.info(f"Beatsource: Unduhan berhasil menggunakan akun.") 
                return 
                
            except Exception as e:
                error_str = str(e).lower()
                if "not available in your country" in error_str or \
                   "subscription" in error_str or \
                   "region locked" in error_str or \
                   "not available for streaming" in error_str or \
                   "tidak streamable" in error_str or \
                   "login gagal" in error_str:
                    LOGGER.warning(f"Beatsource: Akun gagal (Region/Sub Lock/Auth/Tidak Streamable): {e}. Mencoba akun berikutnya...")
                    last_error = e 
                    continue 
                else:
                    LOGGER.error(f"Beatsource: Akun gagal (Fatal): {e}")
                    raise e 
                    
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun Beatsource yang dicoba. Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh Beatsource karena alasan yang tidak diketahui setelah mencoba semua akun.")
    
    # Blok SOUNDCLOUD
    elif link.startswith(tuple(soundcloud)):
        user['provider'] = 'Soundcloud'
        
        client = soundcloud_manager.get_client()
        if not client:
            raise Exception("Maaf, modul Soundcloud bot tidak aktif saat ini (Token salah atau hilang).")

        try:
            user['soundcloud_api'] = client
            await start_soundcloud(link, user)
            LOGGER.info(f"Soundcloud: Unduhan berhasil.") 
            return 
            
        except Exception as e:
            LOGGER.error(f"Soundcloud: Tugas gagal (Fatal): {e}")
            raise e 
    
    # Blok KKBOX
    elif link.startswith(tuple(kkbox)):
        user['provider'] = 'KKBox'
        
        if not kkbox_manager.clients:
            raise Exception("Maaf, tidak ada akun KKBox bot yang aktif saat ini.")

        clients_list = random.sample(kkbox_manager.clients, len(kkbox_manager.clients))
        last_error = None
        for client in clients_list:
            try:
                user['kkbox_api'] = client
                await start_kkbox(link, user)
                LOGGER.info(f"KKBox: Unduhan berhasil menggunakan akun.") 
                return
            except Exception as e:
                error_str = str(e).lower()
                if "unsupported region" in error_str or \
                   "account expired" in error_str or \
                   "quality not available" in error_str or \
                   "incorrect password" in error_str or \
                   "email not found" in error_str:
                    LOGGER.warning(f"KKBox: Akun gagal (Region/Sub/Auth): {e}. Mencoba akun berikutnya...")
                    last_error = e 
                    continue
                else:
                    LOGGER.error(f"KKBox: Akun gagal (Fatal): {e}")
                    raise e
        if last_error:
            raise Exception(f"Item tidak tersedia di semua ({len(clients_list)}) akun KKBox yang dicoba. Error terakhir: {last_error}")
        else:
            raise Exception("Gagal mengunduh KKBox karena alasan yang tidak diketahui setelah mencoba semua akun.")

    # Blok MOOV
    elif link.startswith(tuple(moov)):
        user['provider'] = 'Moov'
        
        if not moov_manager or not moov_manager.clients:
            raise Exception("Maaf, tidak ada akun Moov bot yang aktif saat ini.")

        client = moov_manager.get_client()
        if not client:
             raise Exception("Tidak ada klien Moov yang tersedia (semua gagal login?).")

        try:
            user['moov_api'] = client
            await start_moov(link, user)
            LOGGER.info(f"Moov: Unduhan berhasil menggunakan akun.")
            return
        except Exception as e:
            LOGGER.error(f"Moov: Tugas gagal (Fatal): {e}")
            raise e

    # Blok IDAGIO
    elif link.startswith(tuple(idagio)):
        user['provider'] = 'Idagio'
        
        if not idagio_manager or not idagio_manager.clients:
            raise Exception("Maaf, tidak ada akun Idagio bot yang aktif saat ini.")

        client = idagio_manager.get_client()
        if not client:
             raise Exception("Tidak ada klien Idagio yang tersedia (semua gagal login?).")

        try:
            user['idagio_api'] = client
            await start_idagio(link, user)
            LOGGER.info(f"Idagio: Unduhan berhasil menggunakan akun.")
            return
        except Exception as e:
            LOGGER.error(f"Idagio: Tugas gagal (Fatal): {e}")
            raise e
    
    # Blok NUGS.NET
    elif link.startswith(tuple(nugs)):
        user['provider'] = 'Nugs.net'
        
        if not nugs_manager or not nugs_manager.clients:
            raise Exception("Maaf, tidak ada akun Nugs.net bot yang aktif saat ini.")

        client = nugs_manager.get_client()
        if not client:
             raise Exception("Tidak ada klien Nugs.net yang tersedia (semua gagal login?).")

        try:
            user['nugs_api'] = client
            await start_nugs(link, user)
            LOGGER.info(f"Nugs.net: Unduhan berhasil menggunakan akun.")
            return
        except Exception as e:
            LOGGER.error(f"Nugs.net: Tugas gagal (Fatal): {e}")
            raise e

    # Blok BUGS
    elif link.startswith(tuple(bugs)):
        user['provider'] = 'Bugs'
        
        if not bugs_manager or not bugs_manager.clients:
            raise Exception("Maaf, tidak ada akun Bugs bot yang aktif saat ini.")

        client = bugs_manager.get_client()
        if not client:
             raise Exception("Tidak ada klien Bugs yang tersedia (semua gagal login?).")

        try:
            user['bugs_api'] = client
            await start_bugs(link, user)
            LOGGER.info(f"Bugs: Unduhan berhasil menggunakan akun.")
            return
        except Exception as e:
            error_str = str(e).lower()
            if isinstance(e, BugsError) or "tidak ditemukan" in error_str or "tidak tersedia" in error_str:
                LOGGER.error(f"Bugs: Tugas gagal (Dapat Ditangani): {e}")
                raise e 
            else:
                LOGGER.error(f"Bugs: Tugas gagal (Fatal): {e}")
                raise e 

    # Blok HIGHRESAUDIO
    elif link.startswith(tuple(highresaudio)):
        user['provider'] = 'HIGHRESAUDIO'
        
        # [MODIFIKASI] Matikan pengecekan akun global di sini agar Akun Private bisa lewat
        # if not highresaudio_manager or not highresaudio_manager.clients:
        #    raise Exception("Maaf, tidak ada akun HIGHRESAUDIO bot yang aktif saat ini.")

        # client = highresaudio_manager.get_client()
        # if not client:
        #      raise Exception("Tidak ada klien HIGHRESAUDIO yang tersedia (semua gagal login?).")

        try:
            # user['highresaudio_api'] = client  <-- Jangan set ini, biarkan handler mengambilnya sendiri
            
            # Langsung panggil handler
            await start_highresaudio(link, user)
            
            LOGGER.info(f"HIGHRESAUDIO: Unduhan berhasil.")
            return
        except Exception as e:
            if isinstance(e, HighResAudioError):
                LOGGER.error(f"HIGHRESAUDIO: Tugas gagal (Dapat Ditangani): {e}")
                raise e 
            else:
                LOGGER.error(f"HIGHRESAUDIO: Tugas gagal (Fatal): {e}")
                raise e 

    # Blok JIOSAAVN
    elif link.startswith(tuple(jiosaavn)):
        user['provider'] = 'JioSaavn'
        if not jiosaavn_manager:
             raise Exception("Modul JioSaavn tidak dimuat (Folder/file helper hilang).")
        
        try:
            await start_jiosaavn(link, user)
            LOGGER.info("JioSaavn: Unduhan berhasil.")
            return
        except Exception as e:
            LOGGER.error(f"JioSaavn Gagal: {e}")
            raise e

    # Blok GAANA
    elif link.startswith(tuple(gaana)):
        user['provider'] = 'Gaana'
        if not gaana_manager:
             raise Exception("Modul Gaana tidak dimuat (Folder/file helper hilang).")
        
        try:
            await start_gaana(link, user)
            LOGGER.info("Gaana: Unduhan berhasil.")
            return
        except Exception as e:
            LOGGER.error(f"Gaana Gagal: {e}")
            raise e

    # Blok BANDCAMP
    elif "bandcamp.com" in link:
        user['provider'] = 'Bandcamp'
        if not bandcamp_manager:
             raise Exception("Modul Bandcamp tidak dimuat (Folder/file helper hilang).")
        
        try:
            await start_bandcamp(link, user)
            LOGGER.info("Bandcamp: Unduhan berhasil.")
            return
        except Exception as e:
            LOGGER.error(f"Bandcamp Gagal: {e}")
            raise e

    # Blok LIVEPHISH
    elif link.startswith(tuple(livephish)):
        user['provider'] = 'LivePhish'
        
        if not livephish_manager or not livephish_manager.clients:
            raise Exception("Maaf, tidak ada akun LivePhish bot yang aktif.")
            
        # Gunakan klien pertama (biasanya cukup)
        client = livephish_manager.get_client()
        
        try:
            user['livephish_api'] = client
            await start_livephish(link, user)
            LOGGER.info("LivePhish: Unduhan berhasil.")
            return
        except Exception as e:
            LOGGER.error(f"LivePhish Gagal: {e}")
            raise e

    # Blok BEATSTARS
    elif link.startswith(tuple(beatstars)):
        user['provider'] = 'BeatStars'
        if not beatstars_manager:
             raise Exception("Modul BeatStars tidak dimuat (Folder/file helper hilang).")
        
        try:
            await start_beatstars(link, user)
            LOGGER.info("BeatStars: Unduhan berhasil.")
            return
        except Exception as e:
            LOGGER.error(f"BeatStars Gagal: {e}")
            raise e

    # Blok KHINSIDER
    elif link.startswith(tuple(khinsider)):
        user['provider'] = 'Khinsider'
        if not khinsider_manager:
            raise Exception("Modul Khinsider tidak dimuat (Folder/file helper hilang).")
        
        try:
            await start_khinsider(link, user)
            LOGGER.info("Khinsider: Unduhan berhasil.")
            return
        except Exception as e:
            LOGGER.error(f"Khinsider Gagal: {e}")
            raise e

    # Blok AMAZON MUSIC
    elif any(d in link for d in amazon):
        user['provider'] = 'Amazon Music'
        user_id = user.get('user_id')
        
        # Cek apakah ada akun Global atau akun Private milik user yang aktif
        has_global = len(getattr(amazon_manager, 'clients', [])) > 0 if amazon_manager else False
        has_private = amazon_manager.has_private_session(user_id) if amazon_manager else False

        # Jika keduanya tidak ada, baru tolak unduhan
        if not amazon_manager or (not has_global and not has_private):
            raise Exception("Maaf, tidak ada akun Amazon Music bot (Global maupun Private) yang aktif untuk Anda saat ini.")
            
        try:
            await start_amazon(link, user)
            # HAPUS BARIS INI: from bot.logger import LOGGER
            LOGGER.info("Amazon Music: Unduhan berhasil.")
            return
        except Exception as e:
            # HAPUS BARIS INI: from bot.logger import LOGGER
            LOGGER.error(f"Amazon Music Gagal: {e}")
            raise e

    # Blok GENIE
    elif any(d in link for d in genie):
        user['provider'] = 'Genie'
        if not genie_manager:
            raise Exception("Modul Genie tidak dimuat (Folder/file helper hilang).")
        
        try:
            await start_genie(link, user)
            LOGGER.info("Genie: Unduhan berhasil.")
            return
        except Exception as e:
            LOGGER.error(f"Genie Gagal: {e}")
            raise e

    else:
        LOGGER.warning(f"Link tidak dikenali: {link}")
        raise Exception(f"Link tidak dikenali. Bot tidak tahu cara mengunduh dari: {link}")
