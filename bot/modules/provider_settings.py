# [GANTI FILE: bot/modules/provider_settings.py]

import bot.helpers.translations as lang
import traceback 

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

from config import Config

from ..logger import LOGGER
from ..settings import bot_set
from ..helpers.buttons.settings import *
from ..helpers.database.mongo_async import database
from ..helpers.tidal.tidal_api import TidalApi
from ..helpers.message import edit_message, check_user

from bot import BOT_QOBUZ_CLIENTS

# --- IMPORT MANAGERS ---
try:
    from ..helpers.beatport.manager import beatport_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor beatport_manager.")
    beatport_manager = None
try:
    from ..helpers.deezer.manager import deezer_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor deezer_manager.")
    deezer_manager = None
try:
    from ..helpers.tidal.manager import tidal_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor tidal_manager.")
    tidal_manager = None
try:
    from ..helpers.kkbox.manager import kkbox_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor kkbox_manager.")
    kkbox_manager = None
try:
    from ..helpers.beatsource.manager import beatsource_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor beatsource_manager.")
    beatsource_manager = None
try:
    from ..helpers.soundcloud.manager import soundcloud_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor soundcloud_manager.")
    soundcloud_manager = None
try:
    from ..helpers.idagio.manager import idagio_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor idagio_manager.")
    idagio_manager = None
try:
    from ..helpers.bugs.manager import bugs_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor bugs_manager.")
    bugs_manager = None
try:
    from ..helpers.moov.manager import moov_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor moov_manager.")
    moov_manager = None

# --- TAMBAHAN BARU: LivePhish Manager ---
try:
    from ..helpers.livephish.manager import livephish_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor livephish_manager.")
    livephish_manager = None

# --- TAMBAHAN BARU: Khinsider Manager ---
try:
    from ..helpers.khinsider.manager import khinsider_manager
except ImportError:
    LOGGER.warning("ProviderSettings: Gagal mengimpor khinsider_manager.")
    khinsider_manager = None
# --- BATAS TAMBAHAN ---


@Client.on_callback_query(filters.regex(pattern=r"^providerPanel"))
async def provider_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        await edit_message(
            cb.message,
            lang.s.PROVIDERS_PANEL,
            providers_button()
        )

#----------------
# QOBUZ
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^qbP"))
async def qobuz_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        # Key harus Integer agar sesuai dengan logika di qopy.py
        quality = {5:'MP3 320', 6:'Lossless', 7:'24B<=96KHZ', 27:'24B>96KHZ'}
        
        if not BOT_QOBUZ_CLIENTS:
            return await edit_message(cb.message, "Layanan Qobuz tidak aktif (tidak ada klien yang login).")
        
        client_to_check = list(BOT_QOBUZ_CLIENTS.values())[0]
        
        # FIX: Pastikan current dibaca sebagai Integer
        try:
            current = int(client_to_check.quality)
        except:
            current = 6 # Fallback default
        
        if current in quality:
            quality[current] = quality[current] + '✅'
        await edit_message(cb.message, lang.s.QOBUZ_QUALITY_PANEL, markup=qb_button(quality))

@Client.on_callback_query(filters.regex(pattern=r"^qbQ"))
async def qobuz_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qobuz = {5:'MP3 320', 6:'Lossless', 7:'24B<=96KHZ', 27:'24B>96KHZ'}
        to_set = cb.data.split('_')[1]
        
        # Ambil Key Integer
        qobuz_qual = list(filter(lambda x: qobuz[x] == to_set, qobuz))[0]
        
        if not BOT_QOBUZ_CLIENTS:
            return await edit_message(cb.message, "Layanan Qobuz tidak aktif (tidak ada klien yang login).")
        
        for client in BOT_QOBUZ_CLIENTS.values():
            # FIX: Paksa simpan sebagai Integer
            client.quality = int(qobuz_qual)
            
        # Simpan ke DB sebagai Integer
        await database.set_variable('QOBUZ_QUALITY', int(qobuz_qual))
        await qobuz_cb(c, cb)


#----------------
# TIDAL
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^tdP"))
async def tidal_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        await edit_message(
            cb.message,
            lang.s.TIDAL_PANEL,
            tidal_buttons() 
        )
    
@Client.on_callback_query(filters.regex(pattern=r"^tdQ"))
async def tidal_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qualities = {
            'LOW': 'LOW',
            'HIGH': 'HIGH',
            'LOSSLESS': 'LOSSLESS'
        }
        
        # 1. Cek kemampuan Hi-Res pada Akun Admin
        # Pastikan tidal_manager.clients tidak kosong dan ada yang support HiRes
        if tidal_manager.clients and any(c.mobile_hires for c in tidal_manager.clients):
            qualities['HI_RES'] = 'MAX'
            
        current_q = tidal_manager.quality
        
        # 2. Safety Check: Paksa munculkan tombol MAX jika sedang terpilih
        # (Mengantisipasi jika kualitas tersimpan HI_RES tapi deteksi akun gagal/logout)
        if current_q == 'HI_RES' and 'HI_RES' not in qualities:
             qualities['HI_RES'] = 'MAX'
        
        # 3. Beri tanda centang
        if current_q in qualities:
            qualities[current_q] += '✅'
        else:
            if 'LOSSLESS' in qualities:
                qualities['LOSSLESS'] += '✅'

        # 4. Teks Judul Menu (Diubah agar lebih jelas)
        panel_text = "Choose Tidal Audio Quality below:"

        await edit_message(
            cb.message,
            panel_text, # Gunakan teks baru, bukan lang.s.TIDAL_PANEL
            tidal_quality_button(qualities, spatial=tidal_manager.spatial) 
        )

@Client.on_callback_query(filters.regex(pattern=r"^tdSQ"))
async def tidal_set_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        to_set = cb.data.split('_')[1]
        if to_set == 'spatial':
            options = ['OFF', 'ATMOS AC3 JOC']
            if any(c.mobile_atmos for c in tidal_manager.clients):
                options.append('ATMOS AC4')
            if any(c.mobile_atmos or c.mobile_hires for c in tidal_manager.clients):
                options.append('Sony 360RA')
            try:
                current = options.index(tidal_manager.spatial)
            except:
                current = 0
            nexti = (current + 1) % len(options) 
            tidal_manager.spatial = options[nexti]
            await database.set_variable('TIDAL_SPATIAL', options[nexti])
        else:
            qualities = {'LOW':'LOW','HIGH':'HIGH','LOSSLESS':'LOSSLESS','HI_RES':'MAX'}
            to_set = list(filter(lambda x: qualities[x] == to_set, qualities))[0]
            tidal_manager.quality = to_set
            await database.set_variable('TIDAL_QUALITY', to_set)
        await tidal_quality_cb(c, cb)

@Client.on_callback_query(filters.regex(pattern=r"^tdAuth"))
async def tidal_auth_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        # Ambil daftar klien aktif dari manager
        clients = tidal_manager.clients
        
        text = f"🔐 **PENGATURAN AKUN TIDAL (GLOBAL)**\n\n"
        
        if not clients:
            text += "❌ **Tidak ada akun aktif.**\nSilakan login menggunakan tombol di bawah agar bot bisa digunakan oleh semua user."
        else:
            text += f"✅ **{len(clients)} Akun Aktif**\n"
            text += "Bot akan menggunakan akun-akun ini secara bergantian (Load Balancing).\n\n"
            
            # Loop untuk menampilkan detail setiap akun di pesan teks
            for i, client in enumerate(clients):
                sub_type = client.sub_type or "Unknown"
                country = client.country_code or "??"
                uid = client.user_id or "N/A"
                hires = "✅" if client.mobile_hires else "❌"
                atmos = "✅" if client.mobile_atmos else "❌"
                
                text += f"**{i+1}. User ID:** `{uid}`\n"
                text += f"   🏳️ Region: `{country}` | 💎 Plan: `{sub_type}`\n"
                text += f"   🔊 Hires: {hires} | 🎧 Atmos: {atmos}\n\n"
                
            text += "👇 **Klik tombol sampah (🗑️) di bawah untuk menghapus akun tertentu.**"

        # PENTING: Pass 'clients' ke fungsi buttons agar tombol hapus muncul
        await edit_message(cb.message, text, tidal_auth_buttons(clients))

@Client.on_callback_query(filters.regex(pattern=r"^tdLogin"))
async def tidal_login_cb(c:Client, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        temp_client = TidalApi() 
        try:
            # Simpan list klien saat ini agar tombol 'Back' & list hapus tidak hilang saat proses login
            current_clients = tidal_manager.clients
            
            auth_url, err = await temp_client.get_tv_login_url()
            if err:
                # Tutup sesi temp jika error
                if hasattr(temp_client, 'close'): await temp_client.close()
                elif hasattr(temp_client, 'session') and temp_client.session: await temp_client.session.close()
                return await c.answer_callback_query(cb.id, str(err), True)
            
            await edit_message(
                cb.message, 
                lang.s.TIDAL_AUTH_URL.format(auth_url), 
                tidal_auth_buttons(current_clients) 
            )
            
            sub, err = await temp_client.login_tv()
            if err:
                if hasattr(temp_client, 'close'): await temp_client.close()
                elif hasattr(temp_client, 'session') and temp_client.session: await temp_client.session.close()
                return await edit_message(cb.message, lang.s.ERR_LOGIN_TIDAL_TV_FAILED.format(err), tidal_auth_buttons(current_clients))
            
            if sub:
                auth_data = {
                    'refresh_token': temp_client.tv_session.refresh_token,
                    'country_code': temp_client.tv_session.country_code,
                    'user_id': temp_client.tv_session.user_id
                }
                
                # Load settings lama
                all_settings = await database.get_variable()
                if not all_settings:
                    all_settings = {}
                accounts_list = all_settings.get("TIDAL_ACCOUNTS_LIST", [])
                
                # --- LOGIKA BARU: Cek Duplikasi ---
                # Jangan tambah jika ID sudah ada di database
                if not any(str(acc.get('user_id')) == str(auth_data['user_id']) for acc in accounts_list):
                    accounts_list.append(auth_data)
                    await database.set_variable('TIDAL_ACCOUNTS_LIST', accounts_list)
                    
                    # Reload Manager agar akun baru langsung aktif
                    await tidal_manager.initialize_clients()
                    
                    # Bersihkan sesi temp
                    if hasattr(temp_client, 'close'): await temp_client.close()
                    elif hasattr(temp_client, 'session') and temp_client.session: await temp_client.session.close()
                    
                    await c.answer_callback_query(cb.id, f"✅ Login Berhasil! Akun {sub} ditambahkan.", True)
                    # Refresh Menu Auth
                    await tidal_auth_cb(c, cb)
                else:
                    await c.answer_callback_query(cb.id, "⚠️ Akun ini sudah ada di database.", True)
                    if hasattr(temp_client, 'close'): await temp_client.close()
                    elif hasattr(temp_client, 'session') and temp_client.session: await temp_client.session.close()
                    await tidal_auth_cb(c, cb)

        except Exception as e:
            LOGGER.error(f"Gagal login Tidal: {traceback.format_exc()}")
            if hasattr(temp_client, 'close'): await temp_client.close()
            elif hasattr(temp_client, 'session') and temp_client.session: await temp_client.session.close()
            await c.answer_callback_query(cb.id, f"Error: {e}", True)

@Client.on_callback_query(filters.regex(pattern=r"^tdRemove_(.+)"))
async def tidal_remove_specific_cb(c: Client, cb: CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        # Ambil User ID target dari regex (contoh: tdRemove_12345 -> 12345)
        target_uid = cb.matches[0].group(1) 
        
        # Panggil fungsi remove spesifik di manager (yang sudah kita buat sebelumnya)
        success = await tidal_manager.remove_specific_account(target_uid)
        
        if success:
            await c.answer_callback_query(cb.id, f"✅ Akun {target_uid} berhasil dihapus.", True)
        else:
            await c.answer_callback_query(cb.id, f"❌ Gagal: Akun {target_uid} tidak ditemukan.", True)
        
        # Refresh tampilan menu untuk update daftar
        await tidal_auth_cb(c, cb)


#----------------
# BEATPORT
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^bpP"))
async def beatport_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "lossless": "Lossless (FLAC)",
            "high": "High (AAC 256)",
            "medium": "Medium (AAC 128)"
        }
        if not beatport_manager or not beatport_manager.clients:
            return await edit_message(cb.message, "Layanan Beatport tidak aktif (tidak ada klien yang login).")
        current = beatport_manager.quality 
        if current in quality:
            quality[current] = quality[current] + '✅'
        await edit_message(cb.message, "Pilih kualitas default untuk Beatport:", markup=bp_button(quality))

@Client.on_callback_query(filters.regex(pattern=r"^bpQ"))
async def beatport_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qual_map_display = {
            "Lossless (FLAC)": "lossless",
            "High (AAC 256)": "high",
            "Medium (AAC 128)": "medium"
        }
        to_set_display = cb.data.split('_')[1]
        to_set = qual_map_display.get(to_set_display)
        if not to_set:
            return await c.answer_callback_query(cb.id, "Kualitas tidak valid.", True)
        if not beatport_manager or not beatport_manager.clients:
            return await edit_message(cb.message, "Layanan Beatport tidak aktif (tidak ada klien yang login).")
        beatport_manager.quality = to_set
        await database.set_variable('BEATPORT_QUALITY', to_set)
        await beatport_cb(c, cb)


#----------------
# BEATSOURCE
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^bsP")) 
async def beatsource_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "lossless": "Lossless (FLAC)",
            "high": "High (AAC 256)",
            "medium": "Medium (AAC 128)"
        }
        if not beatsource_manager or not beatsource_manager.clients:
            return await edit_message(cb.message, "Layanan Beatsource tidak aktif (tidak ada klien yang login).")
        
        current = beatsource_manager.quality 
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        await edit_message(
            cb.message,
            "Pilih kualitas default untuk Beatsource:\n(Klien non-Pro akan tetap di 128k)",
            markup=bs_button(quality) 
        )

@Client.on_callback_query(filters.regex(pattern=r"^bsQ")) 
async def beatsource_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qual_map_display = {
            "Lossless (FLAC)": "lossless",
            "High (AAC 256)": "high",
            "Medium (AAC 128)": "medium"
        }
        to_set_display = cb.data.split('_')[1]
        to_set = qual_map_display.get(to_set_display)
        if not to_set:
            return await c.answer_callback_query(cb.id, "Kualitas tidak valid.", True)
        if not beatsource_manager or not beatsource_manager.clients:
            return await edit_message(cb.message, "Layanan Beatsource tidak aktif (tidak ada klien yang login).")
        
        beatsource_manager.quality = to_set
        await database.set_variable('BEATSOURCE_QUALITY', to_set)
        
        await beatsource_cb(c, cb)


#----------------
# SOUNDCLOUD
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^scP")) 
async def soundcloud_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "original": "Original (Jika Ada)",
            "stream": "Stream (Default AAC/MP3)"
        }
        if not soundcloud_manager or not soundcloud_manager.get_client():
            return await edit_message(cb.message, "Layanan Soundcloud tidak aktif (Token salah/hilang).")
        
        current = soundcloud_manager.quality 
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        await edit_message(
            cb.message,
            "Pilih kualitas default untuk Soundcloud:",
            markup=sc_button(quality) 
        )

@Client.on_callback_query(filters.regex(pattern=r"^scQ")) 
async def soundcloud_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qual_map_display = {
            "Original (Jika Ada)": "original",
            "Stream (Default AAC/MP3)": "stream"
        }
        to_set_display = cb.data.split('_')[1]
        to_set = qual_map_display.get(to_set_display)
        if not to_set:
            return await c.answer_callback_query(cb.id, "Kualitas tidak valid.", True)
        if not soundcloud_manager or not soundcloud_manager.get_client():
            return await edit_message(cb.message, "Layanan Soundcloud tidak aktif.")
        
        soundcloud_manager.quality = to_set
        await database.set_variable('SOUNDCLOUD_QUALITY', to_set)
        
        await soundcloud_cb(c, cb)


#----------------
# DEEZER
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^dzP"))
async def deezer_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "FLAC": "FLAC",
            "MP3_320": "MP3 320",
            "MP3_128": "MP3 128"
        }
        if not deezer_manager or not deezer_manager.clients:
            return await edit_message(cb.message, "Layanan Deezer tidak aktif (tidak ada klien yang login).")
        current = deezer_manager.quality
        if current in quality:
            quality[current] = quality[current] + '✅'
        await edit_message(cb.message, "Pilih kualitas default untuk Deezer:", markup=dz_button(quality))

@Client.on_callback_query(filters.regex(pattern=r"^dzQ"))
async def deezer_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qual_map_display = {
            "FLAC": "FLAC",
            "MP3 320": "MP3_320",
            "MP3 128": "MP3_128"
        }
        to_set_display = cb.data.split('_')[1]
        to_set = qual_map_display.get(to_set_display)
        if not to_set:
            return await c.answer_callback_query(cb.id, "Kualitas tidak valid.", True)
        if not deezer_manager or not deezer_manager.clients:
            return await edit_message(cb.message, "Layanan Deezer tidak aktif (tidak ada klien yang login).")
        deezer_manager.quality = to_set
        await database.set_variable('DEEZER_QUALITY', to_set)
        await deezer_cb(c, cb)


#----------------
# KKBOX
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^kkbP"))
async def kkbox_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "128k": "MP3 128k",
            "192k": "MP3 192k",
            "320k": "AAC 320k",
            "hifi": "FLAC 16-bit",
            "hires": "FLAC 24-bit"
        }
        if not kkbox_manager or not kkbox_manager.clients:
            return await edit_message(cb.message, "Layanan KKBox tidak aktif (tidak ada klien yang login).")
        current = kkbox_manager.quality 
        if current in quality:
            quality[current] = quality[current] + '✅'
        await edit_message(cb.message, "Pilih kualitas default untuk KKBox:", markup=kk_button(quality))

@Client.on_callback_query(filters.regex(pattern=r"^kkbQ"))
async def kkbox_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qual_map_display = {
            "MP3 128k": "128k",
            "MP3 192k": "192k",
            "AAC 320k": "320k",
            "FLAC 16-bit": "hifi",
            "FLAC 24-bit": "hires"
        }
        to_set_display = cb.data.split('_')[1]
        to_set = qual_map_display.get(to_set_display)
        if not to_set:
            return await c.answer_callback_query(cb.id, "Kualitas tidak valid.", True)
        if not kkbox_manager or not kkbox_manager.clients:
            return await edit_message(cb.message, "Layanan KKBox tidak aktif (tidak ada klien yang login).")
        kkbox_manager.quality = to_set
        await database.set_variable('KKBOX_QUALITY', to_set)
        await kkbox_cb(c, cb)


#----------------
# IDAGIO
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^idP")) 
async def idagio_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "FLAC": "FLAC",
            "MP3_320": "AAC 320k",
            "MP3_160": "AAC 160k"
        }
        if not idagio_manager or not idagio_manager.clients:
            return await edit_message(cb.message, "Layanan Idagio tidak aktif (tidak ada klien yang login).")
        
        current = idagio_manager.quality 
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        await edit_message(
            cb.message,
            "Pilih kualitas default untuk Idagio:\n(Semua akun bot diasumsikan Premium+)",
            markup=id_button(quality)
        )

@Client.on_callback_query(filters.regex(pattern=r"^idQ")) 
async def idagio_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qual_map_display = {
            "FLAC": "FLAC",
            "AAC 320k": "MP3_320",
            "AAC 160k": "MP3_160"
        }
        to_set_display = cb.data.split('_')[1]
        to_set = qual_map_display.get(to_set_display)
        if not to_set:
            return await c.answer_callback_query(cb.id, "Kualitas tidak valid.", True)
        if not idagio_manager or not idagio_manager.clients:
            return await edit_message(cb.message, "Layanan Idagio tidak aktif.")
        
        idagio_manager.quality = to_set
        await database.set_variable('IDAGIO_QUALITY', to_set)
        
        await idagio_cb(c, cb)


#----------------
# BUGS
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^bgP")) 
async def bugs_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "flac": "FLAC 16-bit",
            "aac256": "AAC 320k",
            "320k": "MP3 320k",
            "aac": "AAC 128k"
        }
        
        if not bugs_manager or not bugs_manager.clients:
            return await edit_message(cb.message, "Layanan Bugs tidak aktif (tidak ada klien yang login).")
        
        current = bugs_manager.quality 
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        await edit_message(
            cb.message,
            "Pilih kualitas default untuk Bugs:\n(Kualitas FLAC tergantung langganan akun bot)",
            markup=bugs_button(quality)
        )

@Client.on_callback_query(filters.regex(pattern=r"^bgQ")) 
async def bugs_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qual_map_display = {
            "FLAC 16-bit": "flac",
            "AAC 320k": "aac256", 
            "MP3 320k": "320k",
            "AAC 128k": "aac"
        }
        
        to_set_display = cb.data.split('_')[1]
        to_set = qual_map_display.get(to_set_display)
        if not to_set:
            return await c.answer_callback_query(cb.id, "Kualitas tidak valid.", True)
        if not bugs_manager or not bugs_manager.clients:
            return await edit_message(cb.message, "Layanan Bugs tidak aktif.")
        
        bugs_manager.quality = to_set
        await database.set_variable('BUGS_QUALITY', to_set)
        
        await bugs_cb(c, cb)


#----------------
# MOOV
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^mvP")) 
async def moov_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "FLAC": "Max (24bit/HR)",
            "MP3_320": "Std (16bit/LL)"
        }
        
        if not moov_manager or not moov_manager.clients:
            return await edit_message(cb.message, "Layanan Moov tidak aktif (tidak ada akun).")
        
        current = moov_manager.quality 

        if current in quality:
            quality[current] = quality[current] + '✅'
        
        acc_info = f"{len(moov_manager.clients)} akun aktif."
        
        await edit_message(
            cb.message,
            f"**MOOV PANEL**\n\n{acc_info}\nProxy aktif: {bool(moov_manager.clients[0].proxy)}\n\nPilih kualitas default bot:",
            markup=mv_button(quality)
        )

@Client.on_callback_query(filters.regex(pattern=r"^mvQ")) 
async def moov_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        to_set = cb.data.split('_')[1] # FLAC atau MP3_320
        
        if not moov_manager:
            return await edit_message(cb.message, "Layanan Moov tidak aktif.")
        
        moov_manager.quality = to_set
        await database.set_variable('MOOV_QUALITY', to_set)
        
        await moov_cb(c, cb)


#----------------
# LIVEPHISH
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^lpP")) 
async def livephish_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "FLAC": "FLAC (16-bit)",
            "ALAC": "ALAC (16-bit)",
            "AAC": "AAC"
        }
        if not livephish_manager or not livephish_manager.clients:
            return await edit_message(cb.message, "Layanan LivePhish tidak aktif.")
            
        current = livephish_manager.quality
        if current in quality:
            quality[current] += '✅'
            
        await edit_message(cb.message, "**LIVEPHISH PANEL**\nPilih kualitas LivePhish:", markup=lp_button(quality))

@Client.on_callback_query(filters.regex(pattern=r"^lpQ")) 
async def livephish_qual_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        to_set = cb.data.split('_')[1]
        livephish_manager.quality = to_set
        await database.set_variable("LIVEPHISH_QUALITY", to_set)
        await livephish_cb(c, cb)


#----------------
# KHINSIDER
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^khiP")) 
async def khinsider_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        # HANYA FLAC DAN MP3 SEPERTI PERMINTAAN
        quality = {
            "flac": "FLAC",
            "mp3": "MP3"
        }
        if not khinsider_manager:
            return await edit_message(cb.message, "Layanan Khinsider tidak aktif.")
            
        current = khinsider_manager.quality
        if current in quality:
            quality[current] += '✅'
            
        await edit_message(cb.message, "**KHINSIDER PANEL**\nPilih prioritas format:", markup=khi_button(quality))

@Client.on_callback_query(filters.regex(pattern=r"^khiQ")) 
async def khinsider_qual_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        to_set = cb.data.split('_')[1]
        khinsider_manager.quality = to_set
        await database.set_variable("KHINSIDER_QUALITY", to_set)
        await khinsider_cb(c, cb)


#----------------
# AMAZON MUSIC (GLOBAL ADMIN)
#----------------
@Client.on_callback_query(filters.regex(pattern=r"^amzP"))
async def amazon_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        quality = {
            "UHD": "UHD (Hi-Res)",
            "HD": "HD (Lossless/FLAC)",
            "SD": "SD (Standard MP3/AAC)"
        }
        if not amazon_manager:
            return await edit_message(cb.message, "Layanan Amazon Music tidak aktif.")
        
        current = getattr(amazon_manager, 'quality', 'HD')
        if current in quality:
            quality[current] = quality[current] + '✅'
        
        await edit_message(
            cb.message,
            "**AMAZON MUSIC PANEL (GLOBAL)**\n\nPilih kualitas default bot:",
            markup=amz_button(quality)
        )

@Client.on_callback_query(filters.regex(pattern=r"^amzQ"))
async def amazon_quality_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        qual_map_display = {
            "UHD (Hi-Res)": "UHD",
            "HD (Lossless/FLAC)": "HD",
            "SD (Standard MP3/AAC)": "SD"
        }
        to_set_display = cb.data.split('_')[1]
        to_set = qual_map_display.get(to_set_display)
        if not to_set:
            return await c.answer_callback_query(cb.id, "Kualitas tidak valid.", True)
        
        amazon_manager.quality = to_set
        await database.set_variable('AMAZON_QUALITY', to_set)
        await amazon_cb(c, cb)

@Client.on_callback_query(filters.regex(pattern=r"^amzAuth"))
async def amazon_auth_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        clients = getattr(amazon_manager, 'clients', [])
        text = f"🔐 **PENGATURAN AKUN AMAZON (GLOBAL)**\n\n"
        
        if not clients:
            text += "❌ **Tidak ada akun aktif.**\nSilakan tambahkan akun dengan mengirimkan perintah:\n`/amazon_global <region>`\nContoh: `/amazon_global jp`"
        else:
            text += f"✅ **{len(clients)} Akun Aktif**\n"
            for i, client in enumerate(clients):
                region = client.region.upper()
                uid = client.tokens.get('customerId', 'Unknown')
                text += f"**{i+1}. Region:** `{region}` | **ID:** `{uid}`\n"
            
            text += "\n👇 **Klik tombol di bawah untuk menghapus akun.**\n*(Gunakan perintah /amazon_global <region> untuk menambah akun baru)*"
        
        from bot.helpers.buttons.settings import amazon_global_auth_buttons
        await edit_message(cb.message, text, markup=amazon_global_auth_buttons(clients))

@Client.on_callback_query(filters.regex(pattern=r"^amzRemove_(.+)"))
async def amazon_remove_cb(c, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        target_uid = cb.matches[0].group(1)
        
        all_settings = await database.get_variable()
        accounts_list = all_settings.get("AMAZON_ACCOUNTS_LIST", [])
        new_list = [acc for acc in accounts_list if acc.get('tokens', {}).get('customerId') != target_uid]
        
        await database.set_variable('AMAZON_ACCOUNTS_LIST', new_list)
        await amazon_manager.initialize_clients()
        
        await c.answer_callback_query(cb.id, f"✅ Akun {target_uid} dihapus.", True)
        await amazon_auth_cb(c, cb)

PENDING_AMAZON_GLOBAL_AUTH = {}

@Client.on_message(filters.command("amazon_global"))
async def amz_global_auth_cmd(client, message):
    if not await check_user(message.from_user.id, restricted=True): return
    
    args = message.text.split()
    region = args[1].lower() if len(args) > 1 else "us"
    valid_regions = ["us", "jp", "uk", "de", "fr", "mx", "br"]
    if region not in valid_regions:
        return await message.reply_text(f"❌ Region tidak valid. Pilih salah satu: {', '.join(valid_regions)}")
        
    msg = await message.reply_text("🔄 **Meminta kode TV dari Amazon (GLOBAL)...**")
    from bot.helpers.amazon.amazon_api import AmazonApi
    amz_api = AmazonApi(region=region)
    
    try:
        public_code, register_code, activation_url = await amz_api.get_tv_device_code()
        PENDING_AMAZON_GLOBAL_AUTH[message.from_user.id] = {
            "api": amz_api,
            "register_code": register_code,
            "region": region
        }
        
        text = (
            f"🔐 **AMAZON MUSIC TV LOGIN (GLOBAL - {region.upper()})**\n\n"
            f"1️⃣ Buka tautan: {activation_url}\n"
            f"2️⃣ Masukkan kode ini: <code>{public_code}</code>\n"
            f"3️⃣ Tekan tombol **Allow / Izinkan** di web Amazon\n"
            f"4️⃣ Jika sudah selesai, tekan tombol di bawah ini."
        )
        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        buttons = [[InlineKeyboardButton("✅ Selesai (Simpan Global)", callback_data="amz_global_verify")]]
        await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        await amz_api.close()
        await msg.edit_text(f"❌ **Error:**\n`{str(e)[:400]}`")

@Client.on_callback_query(filters.regex("^amz_global_verify"))
async def amz_global_verify_cb(client, query):
    if not await check_user(query.from_user.id, restricted=True): return
    user_id = query.from_user.id
    
    if user_id not in PENDING_AMAZON_GLOBAL_AUTH:
        return await query.answer("Sesi kadaluarsa. Ketik ulang /amazon_global", show_alert=True)
        
    await query.answer("Memverifikasi login Global...", show_alert=False)
    auth_data = PENDING_AMAZON_GLOBAL_AUTH[user_id]
    amz_api = auth_data["api"]
    
    try:
        tokens = await amz_api.poll_tv_auth(auth_data["register_code"])
        if not tokens:
            return await query.message.reply_text("❌ Verifikasi gagal. Anda belum menekan Allow.")
            
        await amz_api.close()
        account_data = {"region": auth_data["region"], "tokens": tokens}
        
        all_settings = await database.get_variable()
        accounts_list = all_settings.get("AMAZON_ACCOUNTS_LIST", [])
        
        if not any(acc.get('tokens', {}).get('customerId') == tokens.get('customerId') for acc in accounts_list):
            accounts_list.append(account_data)
            await database.set_variable('AMAZON_ACCOUNTS_LIST', accounts_list)
            await amazon_manager.initialize_clients() # Refresh Manager
            await query.message.edit_text(f"✅ **Login Global Berhasil!**\nAkun Region {auth_data['region'].upper()} ditambahkan ke Database Pusat.\n\nKini semua pengguna bot bisa menikmati unduhan melalui akun ini.")
        else:
            await query.message.edit_text("⚠️ Akun ini sudah ada di daftar Global bot.")
            
        del PENDING_AMAZON_GLOBAL_AUTH[user_id]
    except Exception as e:
        if not amz_api.session.closed: await amz_api.close()
        if user_id in PENDING_AMAZON_GLOBAL_AUTH: del PENDING_AMAZON_GLOBAL_AUTH[user_id]
        await query.message.reply_text(f"❌ **Error:** {str(e)[:400]}")
