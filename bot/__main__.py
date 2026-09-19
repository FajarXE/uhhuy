# [FILE: bot/__main__.py]

import os
import signal
import asyncio
import sys
import logging
import traceback

# --- [FIX] SETUP EVENT LOOP HARUS DI ATAS SEBELUM IMPORT MODUL BOT ---
# Ini memastikan Motor, Pyrogram, dan uvloop berjalan di loop yang sama.
try:
    import uvloop
    uvloop.install()
    logging.info("Main: 🚀 Mesin turbo uvloop berhasil dipasang!")
except ImportError:
    logging.warning("Main: uvloop tidak ditemukan. Menggunakan asyncio standar.")

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
# --------------------------------------------------------------------

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
soundcloud_manager = safe_import('bot.helpers.soundcloud.manager', 'soundcloud_manager')
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
amazon_manager = safe_import('bot.helpers.amazon.manager', 'amazon_manager')
genie_manager = safe_import('bot.helpers.genie.manager', 'genie_manager')


# --- [DEBUG] EXCEPTION HANDLER ---
def handle_exception(loop, context):
    msg = context.get("exception", context["message"])
    msg_str = str(msg)
    
    if "SSL shutdown timed out" in msg_str:
        return 

    if "Connection lost" in msg_str and "RemoteDisconnected" in msg_str:
        return

    logging.error(f"⚠️ EXCEPTION TIDAK TERTANGANI: {msg}")
    
    if "exception" in context:
        if "Non-thread-safe operation" in str(context["exception"]):
            return
        traceback.print_exception(type(context["exception"]), context["exception"], context["exception"].__traceback__)


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


async def periodic_garbage_collector():
    """
    Tugas latar belakang untuk membersihkan file yatim (orphan files) 
    di DOWNLOAD_BASE_DIR yang berumur lebih dari 24 jam.
    Berjalan otomatis setiap 6 jam.
    """
    import time
    import shutil
    import os
    
    while True:
        # Tunggu 6 jam (21600 detik) sebelum setiap siklus
        await asyncio.sleep(21600)
        
        logging.info("GC: Memulai pembersihan sampah berkala...")
        if not os.path.isdir(Config.DOWNLOAD_BASE_DIR):
            continue
            
        now = time.time()
        deleted_count = 0
        
        try:
            for filename in os.listdir(Config.DOWNLOAD_BASE_DIR):
                file_path = os.path.join(Config.DOWNLOAD_BASE_DIR, filename)
                
                # Abaikan file sistem tersembunyi
                if filename.startswith('.'):
                    continue
                    
                try:
                    # Ambil waktu modifikasi terakhir file/folder
                    mtime = os.path.getmtime(file_path)
                    age_seconds = now - mtime
                    
                    # Jika umur melampaui 24 jam (86400 detik)
                    if age_seconds > 86400:
                        if os.path.isfile(file_path) or os.path.islink(file_path):
                            os.remove(file_path)
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                            
                        deleted_count += 1
                        logging.debug(f"GC: Menghapus file yatim -> {filename}")
                except Exception as e:
                    logging.warning(f"GC: Gagal memeriksa/menghapus {file_path}: {e}")
                    
            if deleted_count > 0:
                logging.info(f"GC Selesai: Berhasil menghapus {deleted_count} item lama dari penyimpanan.")
        except Exception as e:
            logging.error(f"GC Fatal Error: {e}")


async def start_services():
    logging.info("------------------------------------------------")
    logging.info("Main: Memulai Inisialisasi Layanan...")
    
    try:
        from bot.helpers.aria2_helper import aria2_purge_all
        await aria2_purge_all()
        logging.info("Main: Berhasil membersihkan sisa task Aria2 lama.")
    except Exception as e:
        logging.warning(f"Main: Gagal membersihkan Aria2: {e}")
    
    await bot_set.set_language()
    await load_all_bot_qobuz_clients()

    managers = [
        (deezer_manager, "Deezer"), (beatport_manager, "Beatport"), 
        (tidal_manager, "Tidal"), (kkbox_manager, "KKBox"),
        (soundcloud_manager, "Soundcloud"),
        (idagio_manager, "Idagio"), (nugs_manager, "Nugs"), (bugs_manager, "Bugs"),
        (highresaudio_manager, "HIGHRESAUDIO"), (moov_manager, "Moov"),
        (jiosaavn_manager, "JioSaavn"), (gaana_manager, "Gaana"), 
        (bandcamp_manager, "Bandcamp"), (livephish_manager, "LivePhish"), 
        (beatstars_manager, "BeatStars"), (khinsider_manager, "Khinsider"), (amazon_manager, "Amazon Music"), (genie_manager, "Genie")
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

    logging.info("Main: Menyiapkan TTL Index MongoDB untuk manajemen memori...")
    await database.setup_ttl_indexes()

    logging.info("Main: Memuat Database Pengguna...")
    await bot_set.initialize_users()
    
    # --- [FIX] PERBAIKAN IMPORT utils KE ui_manager ---
    logging.info("Main: Memuat State Sinyal Batal dari Database...")
    import bot.helpers.ui_manager as ui_manager
    try:
        saved_cancels = await database.load_all_cancels()
        if saved_cancels:
            ui_manager.GLOBAL_CANCEL_DICT.update(saved_cancels)
            logging.info(f"Main: Berhasil memulihkan {len(saved_cancels)} sinyal batal dari memori.")
    except Exception as e:
        logging.warning(f"Main: Gagal memuat sinyal batal: {e}")
    # --------------------------

    logging.info("Main: Menghubungkan ke Telegram...")
    await aio.start()
    
    me = await aio.get_me()
    logging.info(f"------------------------------------------------")
    logging.info(f"BOT BERHASIL START SEBAGAI: @{me.username}")
    logging.info(f"------------------------------------------------")

    # --- [FIX] PERBAIKAN IMPORT utils KE ui_manager ---
    logging.info("Main: Memuat State Radar UI dari Database...")
    try:
        ui_states = await database.load_all_ui_states()
        logging.info(f"Main: Ditemukan {len(ui_states)} memori Radar UI di MongoDB.")
        
        restored_count = 0
        for chat_id, data in ui_states.items():
            msg_id = data['message_id']
            page = data['page']
            try:
                # 1. Siapkan teks status kosong
                g_text, g_markup = await ui_manager.get_status_text(page=page)
                
                # 2. BLIND EDIT (Paksa edit tanpa mengambil/membaca pesan dulu)
                msg = None
                try:
                    msg = await aio.edit_message_text(chat_id, msg_id, g_text, reply_markup=g_markup)
                except Exception as edit_err:
                    if "MESSAGE_NOT_MODIFIED" in str(edit_err).upper():
                        # Jika gagal karena teksnya sama persis (sudah kosong), buat wujud pesan bohongan (Dummy)
                        class DummyMsg:
                            def __init__(self, c_id, m_id):
                                self.chat = type('DummyChat', (), {'id': c_id})()
                                self.id = m_id
                                self._client = None # Memaksa bot menggunakan fallback edit
                        msg = DummyMsg(chat_id, msg_id)
                    else:
                        raise edit_err # Lempar error jika pesan memang benar-benar dihapus oleh user
                
                # 3. Masukkan ke memori RAM
                if msg:
                    ui_manager.GLOBAL_UI_MSG[chat_id] = msg
                    ui_manager.GLOBAL_UI_PAGES[chat_id] = page
                    restored_count += 1
                    logging.info(f"Main: Berhasil me-refresh Radar {msg_id} di chat {chat_id}.")
                    
            except Exception as e:
                logging.warning(f"Main: Pesan Radar {msg_id} gagal diedit ({e}), mencabut dari DB.")
                await database.remove_ui_state(chat_id)
        
        if restored_count > 0:
            logging.info(f"Main: Berhasil memulihkan total {restored_count} panel Radar UI dari memori.")
        else:
            logging.info("Main: Tidak ada panel Radar UI yang dipulihkan.")
            
    except Exception as e:
        logging.error(f"Main: Gagal memuat Radar UI (Fatal): {e}")
    # --------------------------------------------

    asyncio.create_task(periodic_garbage_collector())

    # --- [FIX] PERBAIKAN IMPORT utils KE ui_manager ---
    from bot.helpers.ui_manager import dedicated_ui_worker
    asyncio.create_task(dedicated_ui_worker())
    logging.info("Main: Dedicated UI Worker (Daemon) berhasil dijalankan.")
    # --------------------------------------------
    
    stop_event = asyncio.Event()
    
    def signal_handler_callback():
        logging.info("Main: Sinyal Stop Diterima. Memulai shutdown...")
        stop_event.set()

    current_loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            current_loop.add_signal_handler(sig, signal_handler_callback)
        except NotImplementedError:
            logging.warning(f"Sistem tidak mendukung loop.add_signal_handler untuk {sig}")

    await stop_event.wait()
    
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
        soundcloud_manager, idagio_manager, nugs_manager, bugs_manager, highresaudio_manager, moov_manager,
        jiosaavn_manager, gaana_manager, bandcamp_manager, livephish_manager, beatstars_manager, khinsider_manager, amazon_manager, genie_manager
    ]
    for mgr in managers_list:
        if mgr and hasattr(mgr, 'shutdown'):
            tasks.append(mgr.shutdown())
            
    # --- PENAMBAHAN GRACEFUL SHUTDOWN ARIA2 ---
    try:
        from bot.helpers.aria2_helper import close_aria2_session
        tasks.append(close_aria2_session())
    except Exception as e:
        logging.warning(f"Main: Peringatan saat mengatur penutupan Aria2: {e}")
    # ---------------------------------------------

    # --- PENAMBAHAN GRACEFUL SHUTDOWN CLOUD UPLOADER ---
    try:
        from bot.modules.direct_uploader import close_upload_session
        tasks.append(close_upload_session())
    except Exception as e:
        logging.warning(f"Main: Peringatan penutupan Cloud Uploader: {e}")
    # ---------------------------------------------------------

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    # --- PENAMBAHAN GRACEFUL SHUTDOWN DATABASE ---
    try:
        from bot.helpers.database.mongo_async import database
        import inspect
        
        # Opsi 1: Jika objek database mengekspos client Motor langsung
        if hasattr(database, 'client'):
            database.client.close()
            logging.info("Main: Koneksi pool MongoDB berhasil ditutup dengan aman.")
            
        # Opsi 2: Jika objek database memiliki metode close() khusus
        elif hasattr(database, 'close'):
            if inspect.iscoroutinefunction(database.close):
                await database.close()
            else:
                database.close()
            logging.info("Main: Koneksi pool MongoDB berhasil ditutup dengan aman.")
            
    except Exception as e:
        logging.error(f"Main: Peringatan saat menutup koneksi MongoDB: {e}")
    # ---------------------------------------------

    # --- PENAMBAHAN GRACEFUL SHUTDOWN GUNICORN ---
    try:
        from bot import gunicorn_process
        gunicorn_process.terminate()
        logging.info("Main: Proses Gunicorn berhasil dimatikan.")
    except Exception: 
        pass
    # ---------------------------------------------


if __name__ == "__main__":
    import shutil

    if os.path.isdir(Config.DOWNLOAD_BASE_DIR):
        logging.info(f"Main: 🧹 Membersihkan isi folder {Config.DOWNLOAD_BASE_DIR}...")
        try:
            for filename in os.listdir(Config.DOWNLOAD_BASE_DIR):
                file_path = os.path.join(Config.DOWNLOAD_BASE_DIR, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.remove(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    logging.warning(f"Main: Gagal menghapus {file_path}: {e}")
            logging.info("Main: ✅ Folder sampah bersih!")
        except Exception as e:
            logging.error(f"Main: ❌ Gagal pembersihan: {e}")
    else:
        os.makedirs(Config.DOWNLOAD_BASE_DIR)
    
    # Debugging
    loop.set_debug(True)
    loop.set_exception_handler(handle_exception)
    loop.slow_callback_duration = 1.0
    
    try:
        loop.run_until_complete(start_services())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Main: Dipaksa berhenti.")
    except Exception as e:
        logging.critical(f"Main: ERROR FATAL UTAMA: {e}")
        traceback.print_exc()
    finally:
        logging.info("Main: Selesai.")
