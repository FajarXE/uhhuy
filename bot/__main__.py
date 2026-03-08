# [FILE: bot/__main__.py]

import os
import signal
import asyncio
import sys
import logging
import traceback

# Hapus import idle dari pyrogram karena tidak thread-safe di Python 3.12
# from pyrogram import idle 

from bot import Config
from .tgclient import aio
from .settings import bot_set

# --- Blok Impor Qobuz ---
try:
    from .helpers.qobuz.qopy import QoClient
except ImportError:
    logging.critical("Gagal mengimpor QoClient!")
    sys.exit(1)
from bot import BOT_QOBUZ_CLIENTS

try:
    from .helpers.database.mongo_async import database
except ImportError:
    logging.critical("Gagal mengimpor 'database'!")
    sys.exit(1)

# --- Impor Manajer Layanan (Safe Imports) ---
def safe_import(module_path, class_name):
    try:
        mod = __import__(module_path, fromlist=[class_name])
        return getattr(mod, class_name)
    except (ImportError, AttributeError):
        return None

deezer_manager = safe_import('bot.helpers.deezer.manager', 'deezer_manager')
beatport_manager = safe_import('bot.helpers.beatport.manager', 'beatport_manager')
tidal_manager = safe_import('bot.helpers.tidal.manager', 'tidal_manager')
kkbox_manager = safe_import('bot.helpers.kkbox.manager', 'kkbox_manager')
beatsource_manager = safe_import('bot.helpers.beatsource.manager', 'beatsource_manager')
soundcloud_manager = safe_import('bot.helpers.soundcloud.manager', 'soundcloud_manager')
napster_manager = safe_import('bot.helpers.napster.manager', 'napster_manager')
idagio_manager = safe_import('bot.helpers.idagio.manager', 'idagio_manager')
nugs_manager = safe_import('bot.helpers.nugs.manager', 'nugs_manager')
bugs_manager = safe_import('bot.helpers.bugs.manager', 'bugs_manager')
highresaudio_manager = safe_import('bot.helpers.highresaudio.manager', 'highresaudio_manager')
moov_manager = safe_import('bot.helpers.moov.manager', 'moov_manager')
jiosaavn_manager = safe_import('bot.helpers.jiosaavn.manager', 'jiosaavn_manager')
gaana_manager = safe_import('bot.helpers.gaana.manager', 'gaana_manager')
bandcamp_manager = safe_import('bot.helpers.bandcamp.manager', 'bandcamp_manager')
livephish_manager = safe_import('bot.helpers.livephish.manager', 'livephish_manager')
beatstars_manager = safe_import('bot.helpers.beatstars.manager', 'beatstars_manager')
khinsider_manager = safe_import('bot.helpers.khinsider.manager', 'khinsider_manager')
spotify_manager = safe_import('bot.helpers.spotify.manager', 'spotify_manager')


# --- [DEBUG] EXCEPTION HANDLER (DIPERBAIKI) ---
def handle_exception(loop, context):
    # Ambil pesan error
    msg = context.get("exception", context["message"])
    msg_str = str(msg)
    
    # 1. Heningkan Error SSL Shutdown (Tidak berbahaya)
    if "SSL shutdown timed out" in msg_str:
        return 

    # 2. Heningkan Error Connection Lost biasa
    if "Connection lost" in msg_str and "RemoteDisconnected" in msg_str:
        return

    # Log error lain yang benar-benar penting
    logging.error(f"⚠️ EXCEPTION TIDAK TERTANGANI: {msg}")
    
    if "exception" in context:
        # Jangan print traceback jika errornya adalah RuntimeError thread-safe yang sudah kita tangani
        if "Non-thread-safe operation" in str(context["exception"]):
            return
        traceback.print_exception(type(context["exception"]), context["exception"], context["exception"].__traceback__)
# ---------------------------------

async def load_all_user_settings_into_managers():
    logging.info("Main: Sinkronisasi pengaturan pengguna ke cache manajer...")
    try:
        count = 0
        settings_map = {
            'deezer_qual': deezer_manager,
            'beatport_qual': beatport_manager,
            'kkbox_qual': kkbox_manager,
            'beatsource_qual': beatsource_manager,
            'soundcloud_qual': soundcloud_manager,
            'napster_qual': napster_manager,
            'idagio_qual': idagio_manager,
            'bugs_qual': bugs_manager,
            'moov_qual': moov_manager,
            'livephish_qual': livephish_manager,
            'khinsider_qual': khinsider_manager,
        }

        if not bot_set.user_data:
            logging.warning("Main: bot_set.user_data kosong/belum dimuat.")
            return

        qobuz_interface = None
        if BOT_QOBUZ_CLIENTS:
            qobuz_interface = list(BOT_QOBUZ_CLIENTS.values())[0]

        for user_id, user_data in bot_set.user_data.items():
            if not user_id: continue
            
            for key, manager in settings_map.items():
                quality_val = user_data.get(key)
                if quality_val and manager:
                    try:
                        await manager.setup_quality(user_id, quality_val)
                        count += 1
                    except Exception: pass
            
            if qobuz_interface and user_data.get('qobuz_qual'):
                try:
                    await qobuz_interface.setup_quality(user_id, user_data['qobuz_qual'])
                    count += 1
                except Exception: pass

        logging.info(f"Main: Berhasil menyinkronkan {count} pengaturan.")
    except Exception as e:
        logging.error(f"Main: Gagal sinkronisasi pengaturan pengguna: {e}")


async def login_single_client(creds: dict):
    creds_copy = creds.copy()
    account_id = creds_copy.pop("id", "Unknown")
    
    try:
        client = await asyncio.to_thread(QoClient, **creds_copy)
        await client.login()
        BOT_QOBUZ_CLIENTS[account_id] = client
        logging.info(f"Main: Qobuz #{account_id} LOGIN SUKSES.")
    except Exception as e:
        logging.error(f"Main: Qobuz #{account_id} GAGAL: {e}")
        if 'client' in locals() and hasattr(client, 'close_session'):
            await client.close_session()

async def load_all_bot_qobuz_clients():
    if not Config.QOBUZ_ACCOUNTS: return
    logging.info(f"Main: Mencoba login {len(Config.QOBUZ_ACCOUNTS)} akun Qobuz...")
    tasks = [login_single_client(acc) for acc in Config.QOBUZ_ACCOUNTS]
    await asyncio.gather(*tasks)


async def start_services():
    logging.info("------------------------------------------------")
    logging.info("Main: Memulai Inisialisasi Layanan...")
    
    # --- ANTI INFINITE CRASH LOOP: BERSIHKAN ARIA2 SAAT BOOTING ---
    try:
        from bot.helpers.aria2_helper import aria2_purge_all
        await aria2_purge_all()
        logging.info("Main: Berhasil membersihkan sisa task Aria2 lama di background.")
    except Exception as e:
        logging.warning(f"Main: Gagal membersihkan Aria2: {e}")
    
    await bot_set.set_language()
    await load_all_bot_qobuz_clients()

    managers = [
        (deezer_manager, "Deezer"), (beatport_manager, "Beatport"), 
        (tidal_manager, "Tidal"), (kkbox_manager, "KKBox"),
        (beatsource_manager, "Beatsource"), (soundcloud_manager, "Soundcloud"),
        (napster_manager, "Napster"), (idagio_manager, "Idagio"),
        (nugs_manager, "Nugs"), (bugs_manager, "Bugs"),
        (highresaudio_manager, "HIGHRESAUDIO"), (moov_manager, "Moov"),
        (jiosaavn_manager, "JioSaavn"), (gaana_manager, "Gaana"), 
        (bandcamp_manager, "Bandcamp"), (livephish_manager, "LivePhish"), 
        (beatstars_manager, "BeatStars"), (khinsider_manager, "Khinsider"), (spotify_manager, "Spotify")
    ]

    for mgr, name in managers:
        if mgr:
            logging.info(f"Main: Menginisialisasi {name}...")
            try: 
                await asyncio.wait_for(mgr.initialize_clients(), timeout=45.0)
                logging.info(f"Main: {name} OK.")
            except asyncio.TimeoutError:
                logging.error(f"Main: {name} TIMEOUT (Melewati...)")
            except Exception as e: 
                logging.error(f"Main: Gagal init {name}: {e}")

    if deezer_manager and deezer_manager.clients: bot_set.deezer = True 
    if beatport_manager and beatport_manager.clients: bot_set.beatport = True 

    logging.info("Main: Memuat Database Pengguna...")
    await bot_set.initialize_users()
    await load_all_user_settings_into_managers()

    logging.info("Main: Menghubungkan ke Telegram...")
    await aio.start()
    
    me = await aio.get_me()
    logging.info(f"------------------------------------------------")
    logging.info(f"BOT BERHASIL START SEBAGAI: @{me.username}")
    logging.info(f"------------------------------------------------")
    
    # --- [FIX] PENGGANTI IDLE() ---
    # Kita menggunakan asyncio.Event() untuk menahan bot agar tetap jalan
    # sampai sinyal stop diterima.
    stop_event = asyncio.Event()
    
    def signal_handler_callback():
        logging.info("Main: Sinyal Stop Diterima. Memulai shutdown...")
        stop_event.set()

    # Daftarkan handler sinyal ke event loop (Thread-Safe untuk Python 3.12)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler_callback)
        except NotImplementedError:
            # Fallback untuk sistem yang tidak support add_signal_handler (jarang di Linux)
            logging.warning(f"Sistem tidak mendukung loop.add_signal_handler untuk {sig}")

    # Tunggu sampai event diset (bot berjalan di sini)
    await stop_event.wait()
    # ------------------------------
    
    logging.info("Main: Menerima sinyal stop, mematikan layanan...")
    await aio.stop()
    await shutdown_all_services()


async def shutdown_all_services():
    tasks = []
    for client in BOT_QOBUZ_CLIENTS.values():
        if client and hasattr(client, 'close_session'):
            tasks.append(client.close_session())
    
    managers_list = [
        deezer_manager, beatport_manager, tidal_manager, kkbox_manager,
        beatsource_manager, soundcloud_manager, napster_manager, idagio_manager,
        nugs_manager, bugs_manager, highresaudio_manager, moov_manager,
        jiosaavn_manager, gaana_manager, bandcamp_manager, livephish_manager, beatstars_manager, khinsider_manager
    ]
    for mgr in managers_list:
        if mgr and hasattr(mgr, 'shutdown'):
            tasks.append(mgr.shutdown())

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    if not os.path.isdir(Config.DOWNLOAD_BASE_DIR):
        os.makedirs(Config.DOWNLOAD_BASE_DIR)
    
    loop = asyncio.get_event_loop()
    
    # Debugging
    loop.set_debug(True)
    loop.set_exception_handler(handle_exception)
    loop.slow_callback_duration = 1.0
    
    try:
        loop.run_until_complete(start_services())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Main: Dipaksa berhenti oleh pengguna.")
    except Exception as e:
        logging.critical(f"Main: ERROR FATAL UTAMA: {e}")
        traceback.print_exc()
    finally:
        logging.info("Main: Selesai.")
