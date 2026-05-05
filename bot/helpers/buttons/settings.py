# [FILE: bot/helpers/buttons/settings.py]

import bot.helpers.translations as lang

from bot.settings import bot_set
from bot import BOT_QOBUZ_CLIENTS
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# --- PENAMBAHAN IMPORT UNTUK WARNA TOMBOL ---
from pyrogram.enums import ButtonStyle
# --------------------------------------------

try:
    from bot.helpers.qobuz.qopy import qobuz_manager
except ImportError:
    qobuz_manager = None

class _DummyManager:
    def __init__(self):
        self.clients = []
        self.quality = None
        self.global_clients = []
        self.user_clients = {}
    
    def get_client(self, *args, **kwargs):
        return None
    
    def has_private_session(self, *args):
        return False
        
    async def setup_quality(self, *args, **kwargs):
        pass

# Impor manager Beatport
try:
    from bot.helpers.beatport.manager import beatport_manager
except ImportError:
    beatport_manager = _DummyManager()

# Impor manager Deezer
try:
    from bot.helpers.deezer.manager import deezer_manager
except ImportError:
    deezer_manager = _DummyManager()

# Impor manager Tidal
try:
    from bot.helpers.tidal.manager import tidal_manager
except ImportError:
    tidal_manager = _DummyManager()

# Impor Manajer KKBox
try:
    from bot.helpers.kkbox.manager import kkbox_manager
except ImportError:
    kkbox_manager = _DummyManager()

# Impor Manajer Beatsource
try:
    from bot.helpers.beatsource.manager import beatsource_manager
except ImportError:
    beatsource_manager = _DummyManager()

# Impor Manajer Soundcloud
try:
    from bot.helpers.soundcloud.manager import soundcloud_manager
except ImportError:
    soundcloud_manager = _DummyManager()

# Impor Manajer Idagio
try:
    from bot.helpers.idagio.manager import idagio_manager
except ImportError:
    idagio_manager = _DummyManager()

# Impor Manajer Bugs
try:
    from bot.helpers.bugs.manager import bugs_manager
except ImportError:
    bugs_manager = _DummyManager()

# Impor Manajer Moov
try:
    from bot.helpers.moov.manager import moov_manager
except ImportError:
    moov_manager = _DummyManager()

# Impor Manajer LivePhish
try:
    from bot.helpers.livephish.manager import livephish_manager
except ImportError:
    livephish_manager = _DummyManager()

# Impor Manajer HighResAudio
try:
    from bot.helpers.highresaudio.manager import highresaudio_manager
except ImportError:
    highresaudio_manager = _DummyManager()

# Impor Manajer Khinsider
try:
    from bot.helpers.khinsider.manager import khinsider_manager
except ImportError:
    khinsider_manager = None

# Impor Manajer Amazon Music
try:
    from bot.helpers.amazon.manager import amazon_manager
except ImportError:
    amazon_manager = _DummyManager()


def fetch_base_buttons():
    # Style: PRIMARY (Biru) untuk Main Menu
    main_button = [[InlineKeyboardButton(text=lang.s.MAIN_MENU_BUTTON, callback_data="main_menu", style=ButtonStyle.PRIMARY)]]
    # Style: DANGER (Merah) untuk Close
    close_button = [[InlineKeyboardButton(text=lang.s.CLOSE_BUTTON, callback_data="close", style=ButtonStyle.DANGER)]]
    return main_button, close_button

def main_menu():
    inline_keyboard = [
        [
            InlineKeyboardButton(
                text=lang.s.CORE,
                callback_data='corePanel'
            )
        ],
        [
            InlineKeyboardButton(
                text=lang.s.TELEGRAM,
                callback_data='tgPanel'
            )
        ],
        [
            InlineKeyboardButton(
                text=lang.s.PROVIDERS,
                callback_data='providerPanel'
            )
        ]
    ]
    main_button, close_button = fetch_base_buttons()
    inline_keyboard += close_button
    return InlineKeyboardMarkup(inline_keyboard)

def providers_button():
    inline_keyboard = []
    
    if BOT_QOBUZ_CLIENTS: 
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=lang.s.QOBUZ,
                    callback_data='qbP'
                )
            ]
        )
    
    if deezer_manager and deezer_manager.clients:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=lang.s.DEEZER,
                    callback_data='dzP'
                )
            ]
        )
    if bot_set.can_enable_tidal:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=lang.s.TIDAL,
                    callback_data='tdP'
                )
            ]
        )
    
    if beatport_manager and (getattr(beatport_manager, 'global_clients', []) or getattr(beatport_manager, 'clients', [])):
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text="BEATPORT", 
                    callback_data='bpP'
                )
            ]
        )
    
    if beatsource_manager and (getattr(beatsource_manager, 'global_clients', []) or getattr(beatsource_manager, 'clients', [])):
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text="BEATSOURCE", 
                    callback_data='bsP'
                )
            ]
        )
    
    if soundcloud_manager and soundcloud_manager.get_client():
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text="SOUNDCLOUD", 
                    callback_data='scP'
                )
            ]
        )
        
    if kkbox_manager and kkbox_manager.clients:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text="KKBOX", 
                    callback_data='kkbP'
                )
            ]
        )
    
    if idagio_manager and idagio_manager.clients:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text="IDAGIO", 
                    callback_data='idP'
                )
            ]
        )
    
    if bugs_manager and bugs_manager.clients:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text="BUGS", 
                    callback_data='bgP'
                )
            ]
        )

    if moov_manager and moov_manager.clients:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text="MOOV", 
                    callback_data='mvP'
                )
            ]
        )

    if livephish_manager and livephish_manager.clients:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text="LIVEPHISH", 
                    callback_data='lpP'
                )
            ]
        )

    if highresaudio_manager and highresaudio_manager.clients:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text="HIGHRESAUDIO", 
                    callback_data='hraP'
                )
            ]
        )

    if khinsider_manager:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text="KHINSIDER", 
                    callback_data='khiP'
                )
            ]
        )

    if amazon_manager:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text="AMAZON MUSIC", 
                    callback_data='amzP'
                )
            ]
        )
        
    main_button, close_button = fetch_base_buttons()
    inline_keyboard += main_button + close_button
    return InlineKeyboardMarkup(inline_keyboard)


def tg_button():
    inline_keyboard = [
        [
            InlineKeyboardButton(
                text=lang.s.BOT_PUBLIC.format(bot_set.bot_public),
                callback_data='botPublic'
            )
        ],
        [
            InlineKeyboardButton(
                text=lang.s.ANTI_SPAM.format(bot_set.anti_spam),
                callback_data='antiSpam'
            )
        ],
        [
            InlineKeyboardButton(
                text=lang.s.LANGUAGE,
                callback_data='langPanel'
            )
        ]
    ]
    main_button, close_button = fetch_base_buttons()
    inline_keyboard += main_button + close_button
    return InlineKeyboardMarkup(inline_keyboard)


def core_buttons():
    inline_keyboard = []
    if bot_set.rclone:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=f"Return Link : {bot_set.link_options}",
                    callback_data='linkOptions'
                )
            ]
        )
    inline_keyboard += [
        [
            InlineKeyboardButton(
                text=f"Upload : {bot_set.upload_mode}",
                callback_data='upload'
            )
        ],
        [
            InlineKeyboardButton(
                text=lang.s.SORT_PLAYLIST.format(bot_set.playlist_sort),
                callback_data='sortPlay'
            ),
            InlineKeyboardButton(
                text=lang.s.DISABLE_SORT_LINK.format(bot_set.disable_sort_link),
                callback_data='sortLinkPlay'
            )
        ],
        [
            InlineKeyboardButton(
                text=lang.s.PLAYLIST_ZIP.format(bot_set.playlist_zip),
                callback_data='playZip'
            ),
            InlineKeyboardButton(
                text=lang.s.PLAYLIST_CONC_BUT.format(bot_set.playlist_conc),
                callback_data='playCONC'
            )
        ],
        [
            InlineKeyboardButton(
                text=lang.s.ARTIST_BATCH_BUT.format(bot_set.artist_batch),
                callback_data='artBATCH'
            ),
            InlineKeyboardButton(
                text=lang.s.ARTIST_ZIP.format(bot_set.artist_zip),
                callback_data='artZip'
            )
        ],
        [
            InlineKeyboardButton(
                text=lang.s.ALBUM_ZIP.format(bot_set.album_zip),
                callback_data='albZip'
            ),
            InlineKeyboardButton(
                text=lang.s.POST_ART_BUT.format(bot_set.art_poster),
                callback_data='albArt'
            )
        ]
    ]
    main_button, close_button = fetch_base_buttons()
    inline_keyboard += main_button + close_button
    return InlineKeyboardMarkup(inline_keyboard)


def language_buttons(languages, selected):
    inline_keyboard = []
    for item in languages:
        text = f"{item.__language__} ✅" if item.__language__ == selected else item.__language__
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=text.UPPER(),
                    callback_data=f'langSet_{item.__language__}'
                )
            ]
        )
    main_button, close_button = fetch_base_buttons()
    inline_keyboard += main_button+ close_button
    return InlineKeyboardMarkup(inline_keyboard)

# tidal panel
def tidal_buttons():
    inline_keyboard = [
        [
            InlineKeyboardButton(
                text=lang.s.AUTHORIZATION,
                callback_data='tdAuth'
            )
        ]
    ]
    if tidal_manager and tidal_manager.clients:
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=lang.s.QUALITY,
                    callback_data='tdQ'
                )
            ]
        )
    main_button, close_button = fetch_base_buttons()
    inline_keyboard += main_button + close_button
    return InlineKeyboardMarkup(inline_keyboard)

def tidal_auth_buttons(active_clients: list = None):
    inline_keyboard = []
    
    if active_clients:
        inline_keyboard.append([InlineKeyboardButton("🔻 HAPUS AKUN (KLIK DI BAWAH) 🔻", callback_data="ignore")])
        
        for client in active_clients:
            uid = client.user_id
            sub = client.sub_type or "UNK"
            country = client.country_code or "??"
            btn_text = f"🗑️ {sub} ({country}) - {uid}"
            
            # Style: DANGER (Merah) untuk tombol hapus
            inline_keyboard.append([
                InlineKeyboardButton(text=btn_text, callback_data=f"tdRemove_{uid}", style=ButtonStyle.DANGER)
            ])
            
    # 1. Ubah Button LOGIN ACCOUNT menjadi Hijau (SUCCESS)
    inline_keyboard.append(
        [
            InlineKeyboardButton(
                text="➕ LOGIN ACCOUNT (TV CODE)", # Teks disesuaikan
                callback_data='tdLogin',
                style=ButtonStyle.SUCCESS
            )
        ]
    )
    
    # 2. Ubah Button Back menjadi Biru (PRIMARY)
    inline_keyboard.append(
        [
            InlineKeyboardButton(
                text="🔙 Back to Quality", 
                callback_data="tdP", 
                style=ButtonStyle.PRIMARY
            )
        ]
    )
    
    return InlineKeyboardMarkup(inline_keyboard)
    

def qb_button(qualities: dict, user_id: int = 0):
    inline_keyboard = []
    usetting = user_id != 0
    
    for quality in qualities.values():
        # 1. Cek apakah kualitas ini terpilih (mengandung centang)
        # Kita cek kedua variasi emoji centang untuk keamanan
        is_selected = "✅" in quality
        
        # 2. Tentukan Style: Hijau (Success) jika terpilih, Default jika tidak
        btn_style = ButtonStyle.SUCCESS if is_selected else ButtonStyle.DEFAULT
        
        # 3. Bersihkan Teks: Hapus emoji centang agar tidak muncul di tombol
        # Kita replace emoji dengan string kosong, lalu strip() untuk hapus spasi sisa
        clean_text = quality.replace("✅", "").replace("️", "").strip()
        
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=clean_text, # Teks tombol BERSIH (tanpa emoji)
                    # Callback data juga menggunakan teks bersih
                    callback_data=f"qbQ_{clean_text}" if not usetting else f"uqbs_{clean_text}",
                    style=btn_style
                )
            ]
        )
        
    if usetting:
        # --- TAMBAHAN TOMBOL COVER SOURCE ---
        user_dict = bot_set.user_data.get(user_id, {})
        cover_source = user_dict.get('qobuz_cover_source', 'itunes') # Default itunes
        
        row_cover = []
        
        # Tombol Original
        style_ori = ButtonStyle.SUCCESS if cover_source == 'original' else ButtonStyle.DEFAULT
        row_cover.append(InlineKeyboardButton("Ori Cover", callback_data="uqbc_original", style=style_ori))
        
        # Tombol iTunes
        style_itu = ButtonStyle.SUCCESS if cover_source == 'itunes' else ButtonStyle.DEFAULT
        row_cover.append(InlineKeyboardButton("iTunes Cover", callback_data="uqbc_itunes", style=style_itu))
        
        # Tombol MusicBrainz
        style_mb = ButtonStyle.SUCCESS if cover_source == 'musicbrainz' else ButtonStyle.DEFAULT
        row_cover.append(InlineKeyboardButton("MB Cover", callback_data="uqbc_musicbrainz", style=style_mb))
        
        inline_keyboard.append(row_cover)
        # ------------------------------------
        
        inline_keyboard.append(
            [
                InlineKeyboardButton(text="🔐 PRIVATE ACCOUNT (Multi-Login)", callback_data="uset_qb_auth", style=ButtonStyle.SUCCESS)
            ]
        )
        
        inline_keyboard.append(
            [
                InlineKeyboardButton(text="🔙 Back", callback_data="uset_back", style=ButtonStyle.PRIMARY)
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard)
    
    main_button, close_button = fetch_base_buttons()
    inline_keyboard += main_button + close_button
    return InlineKeyboardMarkup(inline_keyboard)
    

def tidal_quality_button(qualities: dict, user_id: int = 0, spatial: str = 'OFF'):
    inline_keyboard = []
    usetting = user_id != 0
    spatial_to_show = spatial
    
    user_mqa_fix = "OFF"
    user_convert_m4a = "OFF"

    if usetting:
        try:
            from ..tidal.manager import tidal_manager
            _, spatial_to_show, user_mqa_fix, user_convert_m4a = tidal_manager.get_user_quality_settings(user_id)
        except Exception:
            pass

    # --- BAGIAN KUALITAS AUDIO (Dimodifikasi) ---
    for quality in qualities.values():
        # 1. Cek apakah kualitas ini terpilih (mengandung centang)
        # Kita cek "✅" untuk menentukan warna hijau
        is_selected = "✅" in quality
        
        # 2. Tentukan Style: Hijau (Success) jika terpilih, Default jika tidak
        btn_style = ButtonStyle.SUCCESS if is_selected else ButtonStyle.DEFAULT
        
        # 3. Bersihkan Teks: Hapus emoji centang agar tampilan tombol BERSIH
        # .replace("️", "") digunakan untuk menghapus karakter variasi emoji (VS16) yang kadang tertinggal
        clean_text = quality.replace("✅", "").replace("️", "").strip()
        
        inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text=clean_text, # Teks yang muncul di tombol (Tanpa Emoji)
                    # Callback data juga menggunakan teks bersih
                    callback_data=f"tdSQ_{clean_text}" if not user_id else f"utdqs_{clean_text}",
                    style=btn_style 
                )
            ]
        )
        
    inline_keyboard.append(
        [
            InlineKeyboardButton(
                    text=f'SPATIAL : {spatial_to_show}',
                    callback_data=f"tdSQ_spatial" if not user_id else "utdqs_spatial"
                )
        ]
    )
    
    if usetting:
        # --- LOGIKA TOMBOL COVER SOURCE ---
        user_dict = bot_set.user_data.get(user_id, {})
        cover_source = user_dict.get('tidal_cover_source', 'original') # Default Original
        
        row_cover = []
        style_ori = ButtonStyle.SUCCESS if cover_source == 'original' else ButtonStyle.DEFAULT
        row_cover.append(InlineKeyboardButton("Ori Cover", callback_data="utdc_original", style=style_ori))
        
        style_itu = ButtonStyle.SUCCESS if cover_source == 'itunes' else ButtonStyle.DEFAULT
        row_cover.append(InlineKeyboardButton("iTunes Cover", callback_data="utdc_itunes", style=style_itu))
        
        style_mb = ButtonStyle.SUCCESS if cover_source == 'musicbrainz' else ButtonStyle.DEFAULT
        row_cover.append(InlineKeyboardButton("MB Cover", callback_data="utdc_musicbrainz", style=style_mb))
        
        inline_keyboard.append(row_cover)
        # -----------------------------------

        # --- LOGIKA WARNA TOMBOL MQA & CONVERT ---
        # Logika MQA Fix
        if user_mqa_fix == "ON":
            mqa_text = "MQA Fix: ON"
            mqa_callback = "utdqs_mqa_OFF"
            mqa_style = ButtonStyle.SUCCESS  # Hijau jika ON
        else:
            mqa_text = "MQA Fix: OFF"
            mqa_callback = "utdqs_mqa_ON"
            mqa_style = ButtonStyle.DANGER   # Merah jika OFF
        
        # Logika Convert M4A
        if user_convert_m4a == "ON":
            convert_text = "Convert M4A: ON"
            convert_callback = "utdqs_convert_OFF"
            convert_style = ButtonStyle.SUCCESS # Hijau jika ON
        else:
            convert_text = "Convert M4A: OFF"
            convert_callback = "utdqs_convert_ON"
            convert_style = ButtonStyle.DANGER  # Merah jika OFF
            
        # Menambahkan tombol dengan Style yang sudah ditentukan
        inline_keyboard.append([InlineKeyboardButton(text=mqa_text, callback_data=mqa_callback, style=mqa_style)])
        inline_keyboard.append([InlineKeyboardButton(text=convert_text, callback_data=convert_callback, style=convert_style)])
        
        inline_keyboard.append([InlineKeyboardButton(text="🔐 PRIVATE ACCOUNT (Multi-Login)", callback_data="utd_auth_menu", style=ButtonStyle.PRIMARY)])
        inline_keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="uset_back", style=ButtonStyle.PRIMARY)])
        
        return InlineKeyboardMarkup(inline_keyboard)

    main_button, close_button = fetch_base_buttons()
    inline_keyboard += main_button + close_button
    
    return InlineKeyboardMarkup(inline_keyboard)


# ==========================================
# BEATPORT BUTTONS (PRIVATE ACCOUNT)
# ==========================================

def beatport_user_auth_buttons(is_logged_in: bool):
    buttons = []
    
    if is_logged_in:
        # Style: DANGER (Logout)
        buttons.append([InlineKeyboardButton("🚪 LOGOUT SESSION", callback_data="uset_bp_logout", style=ButtonStyle.DANGER)])
    else:
        # Style: SUCCESS (Login)
        buttons.append([InlineKeyboardButton("➕ LOGIN ACCOUNT", callback_data="uset_bp_instr", style=ButtonStyle.SUCCESS)])
        
    buttons.append([InlineKeyboardButton("🔙 Back to Quality", callback_data="uset_beatport", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(buttons)

def bp_button(quality: dict, user_id: int = None):
    buttons = []
    usetting = user_id is not None
    prefix = "bpQ" if not usetting else f"ubps"
    row = []
    
    # Map teks bersih
    display_text_map = {
        "lossless": "Lossless (FLAC)",
        "high": "High (AAC 256)",
        "medium": "Medium (AAC 128)"
    }
    
    for i, (key, value) in enumerate(quality.items()):
        # Ambil teks bersih (tanpa emoji)
        clean_text = display_text_map.get(key)
        
        # 1. Logic Warna: Cek apakah value asli mengandung centang
        is_selected = "✅" in value
        btn_style = ButtonStyle.SUCCESS if is_selected else ButtonStyle.DEFAULT
        
        if clean_text:
            # 2. Buat Tombol
            # text=clean_text : Teks tombol bersih (tanpa emoji)
            # callback_data : Menggunakan clean_text sesuai pola kode asli Anda
            row.append(InlineKeyboardButton(
                text=clean_text, 
                callback_data=f"{prefix}_{clean_text}", 
                style=btn_style
            ))
            
        # Logic baris (maksimal 2 tombol per baris)
        if (i + 1) % 2 == 0 or i == len(quality) - 1:
            buttons.append(row)
            row = []
            
    if usetting:
        buttons.append([InlineKeyboardButton("🔐 PRIVATE ACCOUNT", callback_data="uset_bp_auth", style=ButtonStyle.PRIMARY)])
        buttons.append(
            [
                InlineKeyboardButton(text="🔙 Back", callback_data="uset_back", style=ButtonStyle.PRIMARY)
            ]
        )
        return InlineKeyboardMarkup(buttons)
        
    main_button, close_button = fetch_base_buttons()
    buttons += main_button + close_button
    return InlineKeyboardMarkup(buttons)


# ==========================================
# BEATSOURCE BUTTONS (PRIVATE ACCOUNT)
# ==========================================

def beatsource_user_auth_buttons(is_logged_in: bool):
    buttons = []
    
    if is_logged_in:
        buttons.append([InlineKeyboardButton("🚪 LOGOUT SESSION", callback_data="uset_bs_logout", style=ButtonStyle.DANGER)])
    else:
        buttons.append([InlineKeyboardButton("➕ LOGIN ACCOUNT", callback_data="uset_bs_instr", style=ButtonStyle.SUCCESS)])
        
    buttons.append([InlineKeyboardButton("🔙 Back to Quality", callback_data="uset_beatsource", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(buttons)

def bs_button(quality: dict, user_id: int = None):
    buttons = []
    usetting = user_id is not None
    prefix = "bsQ" if not usetting else f"usbs" 
    row = []
    
    display_text_map = {
        "lossless": "Lossless (FLAC)",
        "high": "High (AAC 256)",
        "medium": "Medium (AAC 128)"
    }
    
    for i, (key, value) in enumerate(quality.items()):
        # Ambil teks bersih dari map
        clean_text = display_text_map.get(key)
        
        # 1. Cek Warna: Gunakan value asli (yang mungkin ada emoji ✅)
        is_selected = "✅" in value
        btn_style = ButtonStyle.SUCCESS if is_selected else ButtonStyle.DEFAULT

        if clean_text:
            # 2. Buat Tombol: Gunakan clean_text sebagai label tombol
            row.append(InlineKeyboardButton(
                text=clean_text, # Teks bersih (tanpa emoji)
                callback_data=f"{prefix}_{clean_text}", 
                style=btn_style
            ))
            
        if (i + 1) % 2 == 0 or i == len(quality) - 1:
            buttons.append(row)
            row = []
            
    if usetting:
        buttons.append([InlineKeyboardButton("🔐 PRIVATE ACCOUNT", callback_data="uset_bs_auth", style=ButtonStyle.PRIMARY)])
        buttons.append(
            [
                InlineKeyboardButton(text="🔙 Back", callback_data="uset_back", style=ButtonStyle.PRIMARY)
            ]
        )
        return InlineKeyboardMarkup(buttons)
        
    main_button, close_button = fetch_base_buttons()
    buttons += main_button + close_button
    return InlineKeyboardMarkup(buttons)


# Soundcloud Button
def sc_button(quality: dict, user_id: int = None):
    buttons = []
    usetting = user_id is not None
    prefix = "scQ" if not usetting else f"uscs" 
    
    display_text_map = {
        "original": "Original (Jika Ada)",
        "stream": "Stream (Default AAC/MP3)"
    }
    
    for key, value in quality.items():
        # Ambil teks bersih dari map
        clean_text = display_text_map.get(key)
        
        # 1. Cek Warna: Gunakan value asli (yang mungkin ada emoji ✅)
        is_selected = "✅" in value
        btn_style = ButtonStyle.SUCCESS if is_selected else ButtonStyle.DEFAULT
        
        if clean_text:
            # 2. Buat Tombol: Gunakan clean_text sebagai label tombol (Tanpa Emoji)
            buttons.append([
                InlineKeyboardButton(
                    text=clean_text, 
                    callback_data=f"{prefix}_{clean_text}", 
                    style=btn_style
                )
            ])

    if usetting:
        buttons.append(
            [
                InlineKeyboardButton(text="🔙 Back", callback_data="uset_back", style=ButtonStyle.PRIMARY)
            ]
        )
        return InlineKeyboardMarkup(buttons)
        
    main_button, close_button = fetch_base_buttons()
    buttons += main_button + close_button
    return InlineKeyboardMarkup(buttons)


def qb_user_auth_buttons(accounts_list: list):
    buttons = []
    
    if accounts_list:
        buttons.append([InlineKeyboardButton("🔻 CLICK BELOW TO DELETE 🔻", callback_data="ignore")])
        for acc in accounts_list:
            label = acc.get('label', 'Unknown')
            # Jika login via email, tampilkan email. Jika via token, tampilkan UID/Label
            email_label = acc.get('email', label) 
            q_uid = acc.get('user_id', '0')
            
            btn_text = f"🗑️ {email_label} ({q_uid})"
            callback = f"uset_qb_rm_{q_uid}"
            buttons.append([InlineKeyboardButton(btn_text, callback_data=callback, style=ButtonStyle.DANGER)])
            
    # Teks instruksi diubah agar merepresentasikan dukungan ganda (Email ATAU Token)
    buttons.append([InlineKeyboardButton("➕ ADD ACCOUNT (EMAIL / TOKEN)", callback_data="uset_qb_instr", style=ButtonStyle.SUCCESS)])
    buttons.append([InlineKeyboardButton("🔙 Back to Quality", callback_data="uset_qobuz", style=ButtonStyle.PRIMARY)])
    
    return InlineKeyboardMarkup(buttons)


def deezer_user_auth_buttons(accounts_list: list):
    buttons = []
    if accounts_list:
        buttons.append([InlineKeyboardButton("🔻 CLICK BELOW TO DELETE 🔻", callback_data="ignore")])
        for acc in accounts_list:
            label = acc.get('label', 'Unknown')
            uid = acc.get('user_id', '0')
            btn_text = f"🗑️ {label} ({uid})"
            callback = f"uset_dz_rm_{uid}"
            # Style: DANGER
            buttons.append([InlineKeyboardButton(btn_text, callback_data=callback, style=ButtonStyle.DANGER)])
            
    buttons.append([InlineKeyboardButton("➕ ADD ACCOUNT (ARL)", callback_data="uset_dz_instr", style=ButtonStyle.SUCCESS)])
    buttons.append([InlineKeyboardButton("🔙 Back to Quality", callback_data="uset_deezer", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(buttons)


def dz_button(quality: dict, user_id: int = None):
    buttons = []
    usetting = user_id is not None
    prefix = "dzQ" if not usetting else f"udzs"
    row = []
    
    display_text_map = {
        "FLAC": "FLAC",
        "MP3_320": "MP3 320",
        "MP3_128": "MP3 128"
    }
    
    for i, (key, value) in enumerate(quality.items()):
        # Ambil teks bersih dari map (Tanpa Emoji)
        clean_text = display_text_map.get(key)
        
        # 1. Cek Warna: Deteksi centang pada value asli
        is_selected = "✅" in value
        btn_style = ButtonStyle.SUCCESS if is_selected else ButtonStyle.DEFAULT

        if clean_text:
            # 2. Buat Tombol: Gunakan clean_text sebagai label
            row.append(InlineKeyboardButton(
                text=clean_text, 
                callback_data=f"{prefix}_{clean_text}", 
                style=btn_style
            ))
            
        if (i + 1) % 2 == 0 or i == len(quality) - 1:
            buttons.append(row)
            row = []
    
    if usetting:
        # --- LOGIKA TOMBOL COVER SOURCE ---
        user_dict = bot_set.user_data.get(user_id, {})
        cover_source = user_dict.get('deezer_cover_source', 'itunes') # Default itunes
        
        row_cover = []
        style_ori = ButtonStyle.SUCCESS if cover_source == 'original' else ButtonStyle.DEFAULT
        row_cover.append(InlineKeyboardButton("Ori Cover", callback_data="udzc_original", style=style_ori))
        
        style_itu = ButtonStyle.SUCCESS if cover_source == 'itunes' else ButtonStyle.DEFAULT
        row_cover.append(InlineKeyboardButton("iTunes Cover", callback_data="udzc_itunes", style=style_itu))
        
        style_mb = ButtonStyle.SUCCESS if cover_source == 'musicbrainz' else ButtonStyle.DEFAULT
        row_cover.append(InlineKeyboardButton("MB Cover", callback_data="udzc_musicbrainz", style=style_mb))
        
        buttons.append(row_cover)
        # -----------------------------------
        
        # Tombol Private Account & Back (Biru)
        buttons.append([InlineKeyboardButton("🔐 PRIVATE ACCOUNT (Multi-Login)", callback_data="uset_dz_auth", style=ButtonStyle.PRIMARY)])
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="uset_back", style=ButtonStyle.PRIMARY)])
        return InlineKeyboardMarkup(buttons)

    main_button, close_button = fetch_base_buttons()
    buttons += main_button + close_button
    return InlineKeyboardMarkup(buttons)


def kk_button(quality: dict, user_id: int = None):
    buttons = []
    usetting = user_id is not None
    prefix = "kkbQ" if not usetting else f"ukks"
    row = []
    
    display_text_map = {
        "128k": "MP3 128k",
        "192k": "MP3 192k",
        "320k": "AAC 320k",
        "hifi": "FLAC 16-bit",
        "hires": "FLAC 24-bit"
    }
    
    for i, (key, value) in enumerate(quality.items()):
        # Ambil teks bersih dari map
        clean_text = display_text_map.get(key)
        
        # 1. Cek Warna: Gunakan value asli (yang mungkin ada emoji ✅)
        is_selected = "✅" in value
        btn_style = ButtonStyle.SUCCESS if is_selected else ButtonStyle.DEFAULT

        if clean_text:
            # 2. Buat Tombol: Gunakan clean_text sebagai label tombol (Tanpa Emoji)
            row.append(InlineKeyboardButton(
                text=clean_text, 
                callback_data=f"{prefix}_{clean_text}", 
                style=btn_style
            ))
            
        if (i + 1) % 2 == 0 or i == len(quality) - 1:
            buttons.append(row)
            row = []
            
    if usetting:
        buttons.append(
            [
                InlineKeyboardButton(text="🔙 Back", callback_data="uset_back", style=ButtonStyle.PRIMARY)
            ]
        )
        return InlineKeyboardMarkup(buttons)
        
    main_button, close_button = fetch_base_buttons()
    buttons += main_button + close_button
    return InlineKeyboardMarkup(buttons)

def id_button(quality: dict, user_id: int = None):
    buttons = []
    usetting = user_id is not None
    prefix = "idQ" if not usetting else f"uids"
    row = []
    
    display_text_map = {
        "FLAC": "FLAC",
        "MP3_320": "AAC 320k",
        "MP3_160": "AAC 160k"
    }
    
    for i, (key, value) in enumerate(quality.items()):
        # Ini adalah teks bersih (Tanpa Emoji)
        clean_text = display_text_map.get(key)
        
        # 1. Cek Warna: Gunakan value asli (yang mungkin ada emoji ✅)
        is_selected = "✅" in value
        btn_style = ButtonStyle.SUCCESS if is_selected else ButtonStyle.DEFAULT

        if clean_text:
            # 2. Buat Tombol:
            # text=clean_text -> Agar tampilan tombol bersih
            # callback_data -> Tetap menggunakan clean_text sesuai pola
            row.append(InlineKeyboardButton(
                text=clean_text, 
                callback_data=f"{prefix}_{clean_text}", 
                style=btn_style
            ))
            
        if (i + 1) % 2 == 0 or i == len(quality) - 1:
            buttons.append(row)
            row = []
            
    if usetting:
        buttons.append(
            [
                InlineKeyboardButton(text="🔙 Back", callback_data="uset_back", style=ButtonStyle.PRIMARY)
            ]
        )
        return InlineKeyboardMarkup(buttons)
        
    main_button, close_button = fetch_base_buttons()
    buttons += main_button + close_button
    return InlineKeyboardMarkup(buttons)

def bugs_button(quality: dict, user_id: int = None):
    buttons = []
    usetting = user_id is not None
    prefix = "bgQ" if not usetting else f"ubgs"
    
    # Map teks bersih
    display_text_map = {
        "flac": "FLAC 16-bit",
        "aac256": "AAC 320k",
        "320k": "MP3 320k",
        "aac": "AAC 128k"
    }
    
    # Ambil value asli (yang mungkin ada emoji ✅) untuk pengecekan warna
    raw_flac = quality.get("flac", "")
    raw_aac256 = quality.get("aac256", "")
    raw_320k = quality.get("320k", "")
    raw_aac = quality.get("aac", "")

    # Tentukan style berdasarkan tanda centang di value asli
    style_flac = ButtonStyle.SUCCESS if "✅" in raw_flac else ButtonStyle.DEFAULT
    style_aac256 = ButtonStyle.SUCCESS if "✅" in raw_aac256 else ButtonStyle.DEFAULT
    style_320k = ButtonStyle.SUCCESS if "✅" in raw_320k else ButtonStyle.DEFAULT
    style_aac = ButtonStyle.SUCCESS if "✅" in raw_aac else ButtonStyle.DEFAULT

    # Baris 1
    row1 = []
    # Gunakan display_text_map[...] untuk text tombol agar BERSIH (tanpa emoji)
    row1.append(InlineKeyboardButton(text=display_text_map['flac'], callback_data=f"{prefix}_{display_text_map['flac']}", style=style_flac))
    row1.append(InlineKeyboardButton(text=display_text_map['aac256'], callback_data=f"{prefix}_{display_text_map['aac256']}", style=style_aac256)) 
    buttons.append(row1)
    
    # Baris 2
    row2 = []
    row2.append(InlineKeyboardButton(text=display_text_map['320k'], callback_data=f"{prefix}_{display_text_map['320k']}", style=style_320k))
    row2.append(InlineKeyboardButton(text=display_text_map['aac'], callback_data=f"{prefix}_{display_text_map['aac']}", style=style_aac))
    buttons.append(row2)

    if usetting:
        buttons.append(
            [
                InlineKeyboardButton(text="🔙 Back", callback_data="uset_back", style=ButtonStyle.PRIMARY)
            ]
        )
        return InlineKeyboardMarkup(buttons)
        
    main_button, close_button = fetch_base_buttons()
    buttons += main_button + close_button
    return InlineKeyboardMarkup(buttons)


def mv_button(quality: dict, user_id: int = None):
    buttons = []
    usetting = user_id is not None
    prefix = "mvQ" if not usetting else f"umvs"
    
    row = []
    for i, (key, value) in enumerate(quality.items()):
        raw_key = key 
        # Style check
        btn_style = ButtonStyle.SUCCESS if "✅" in value else ButtonStyle.DEFAULT
        
        row.append(InlineKeyboardButton(value, callback_data=f"{prefix}_{raw_key}", style=btn_style))
        
        if len(row) == 2:
            buttons.append(row)
            row = []
            
    if row:
        buttons.append(row)

    if usetting:
        buttons.append(
            [
                InlineKeyboardButton(text="🔙 Back", callback_data="uset_back", style=ButtonStyle.PRIMARY)
            ]
        )
        return InlineKeyboardMarkup(buttons)
        
    main_button, close_button = fetch_base_buttons()
    buttons += main_button + close_button
    return InlineKeyboardMarkup(buttons)

def lp_button(quality: dict, user_id: int = None):
    buttons = []
    usetting = user_id is not None
    prefix = "lpQ" if not usetting else f"ulps"
    
    row = []
    for k, v in quality.items():
        # Style check
        btn_style = ButtonStyle.SUCCESS if "✅" in v else ButtonStyle.DEFAULT
        
        row.append(InlineKeyboardButton(v, callback_data=f"{prefix}_{k}", style=btn_style))
        
        if len(row) == 2:
            buttons.append(row)
            row = []
            
    if row:
        buttons.append(row)

    if usetting:
        buttons.append(
            [
                InlineKeyboardButton(text="🔙 Back", callback_data="uset_back", style=ButtonStyle.PRIMARY)
            ]
        )
        return InlineKeyboardMarkup(buttons)
        
    main_button, close_button = fetch_base_buttons()
    buttons += main_button + close_button
    return InlineKeyboardMarkup(buttons)


# ==========================================
# HIGHRESAUDIO BUTTONS (PRIVATE ACCOUNT)
# ==========================================

def highresaudio_user_auth_buttons(is_logged_in: bool):
    buttons = []
    
    if is_logged_in:
        buttons.append([InlineKeyboardButton("🚪 LOGOUT SESSION", callback_data="uset_hra_logout", style=ButtonStyle.DANGER)])
    else:
        buttons.append([InlineKeyboardButton("➕ LOGIN ACCOUNT", callback_data="uset_hra_instr", style=ButtonStyle.SUCCESS)])
        
    buttons.append([InlineKeyboardButton("🔙 Back to Quality", callback_data="uset_highresaudio", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(buttons)

def hra_button(user_id: int = None):
    buttons = []
    usetting = user_id is not None
    
    # Text: "FLAC (Lossless)" (Tanpa Emoji)
    # Style: ButtonStyle.SUCCESS (Tetap Hijau karena ini default/active)
    buttons.append([InlineKeyboardButton(text="FLAC (Lossless)", callback_data="ignore", style=ButtonStyle.SUCCESS)])
    
    if usetting:
        # Tombol Private Account & Back (Biru)
        buttons.append([InlineKeyboardButton("🔐 PRIVATE ACCOUNT", callback_data="uset_hra_auth", style=ButtonStyle.PRIMARY)])
        buttons.append(
            [
                InlineKeyboardButton(text="🔙 Back", callback_data="uset_back", style=ButtonStyle.PRIMARY)
            ]
        )
        return InlineKeyboardMarkup(buttons)
    
    main_button, close_button = fetch_base_buttons()
    buttons += main_button + close_button
    return InlineKeyboardMarkup(buttons)

# ==========================================
# AMAZON MUSIC BUTTONS (PRIVATE ACCOUNT)
# ==========================================

def amazon_user_auth_buttons(is_logged_in: bool):
    buttons = []
    
    if is_logged_in:
        buttons.append([InlineKeyboardButton("🚪 LOGOUT SESSION", callback_data="uamz_logout", style=ButtonStyle.DANGER)])
    else:
        # Menggunakan alur TV Code
        buttons.append([InlineKeyboardButton("➕ LOGIN ACCOUNT (TV CODE)", callback_data="uamz_instr", style=ButtonStyle.SUCCESS)])
        
    buttons.append([InlineKeyboardButton("🔙 Back to Quality", callback_data="uset_amazon", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(buttons)

def amz_button(quality: dict, user_id: int = None):
    buttons = []
    usetting = user_id is not None
    prefix = "amzQ" if not usetting else "uamzs"
    row = []
    
    display_text_map = {
        "UHD": "UHD (Hi-Res)",
        "HD": "HD (Lossless/FLAC)",
        "SD": "SD (Standard MP3/AAC)"
    }
    
    # 1. Bangun tombol pilihan kualitas (UHD, HD, SD)
    for i, (key, value) in enumerate(quality.items()):
        # Ambil teks bersih untuk label tombol
        clean_text = display_text_map.get(key, key)
        
        # Deteksi apakah kualitas ini sedang terpilih (ada emoji ✅)
        is_selected = "✅" in value
        btn_style = ButtonStyle.SUCCESS if is_selected else ButtonStyle.DEFAULT

        row.append(InlineKeyboardButton(
            text=clean_text, 
            callback_data=f"{prefix}_{key}", 
            style=btn_style
        ))
            
        # Susun 2 tombol per baris
        if (i + 1) % 2 == 0 or i == len(quality) - 1:
            buttons.append(row)
            row = []
            
    # 2. Tambahkan tombol navigasi tambahan
    if usetting:
        # Tampilan untuk menu USER SETTINGS (/usetting)
        buttons.append([InlineKeyboardButton("🔐 PRIVATE ACCOUNT", callback_data="uamz_auth", style=ButtonStyle.PRIMARY)])
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="uset_back", style=ButtonStyle.PRIMARY)])
    else:
        # Tampilan untuk menu ADMIN (Providers Panel)
        buttons.append([InlineKeyboardButton("🔐 GLOBAL ACCOUNTS (Admin)", callback_data="amzAuth", style=ButtonStyle.PRIMARY)])
        main_button, close_button = fetch_base_buttons()
        buttons += main_button + close_button
        
    return InlineKeyboardMarkup(buttons)

def amazon_global_auth_buttons(active_clients: list):
    buttons = []
    if active_clients:
        buttons.append([InlineKeyboardButton("🔻 CLICK BELOW TO DELETE 🔻", callback_data="ignore")])
        for client in active_clients:
            uid = client.tokens.get('customerId', 'Unknown')
            region = client.region.upper()
            btn_text = f"🗑️ {region} - {uid}"
            buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"amzRemove_{uid}", style=ButtonStyle.DANGER)])
            
    buttons.append([InlineKeyboardButton("🔙 Back to Quality", callback_data="amzP", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(buttons)

        
def khi_button(quality: dict, user_id: int = None):
    buttons = []
    usetting = user_id is not None
    prefix = "khiQ" if not usetting else f"ukhis"
    
    row = []
    if "flac" in quality:
        # Ambil value asli untuk cek warna
        raw_txt = quality["flac"]
        style = ButtonStyle.SUCCESS if "✅" in raw_txt else ButtonStyle.DEFAULT
        
        # Gunakan Teks Bersih "FLAC" untuk tombol
        row.append(InlineKeyboardButton("FLAC", callback_data=f"{prefix}_flac", style=style))
        
    if "mp3" in quality:
        raw_txt = quality["mp3"]
        style = ButtonStyle.SUCCESS if "✅" in raw_txt else ButtonStyle.DEFAULT
        
        # Gunakan Teks Bersih "MP3" untuk tombol
        row.append(InlineKeyboardButton("MP3", callback_data=f"{prefix}_mp3", style=style))
    
    if row:
        buttons.append(row)

    if usetting:
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="uset_back", style=ButtonStyle.PRIMARY)])
        return InlineKeyboardMarkup(buttons)
        
    main_button, close_button = fetch_base_buttons()
    buttons += main_button + close_button
    return InlineKeyboardMarkup(buttons)


def lyrics_button(user_settings: dict, user_id):
    buttons = []
    
    status = user_settings.get('lyrics_status', False)
    status_text = "Status: ON" if status else "Status: OFF"
    status_cb = "uset_ly_off" if status else "uset_ly_on"
    
    # Beri warna merah jika OFF, hijau jika ON
    status_style = ButtonStyle.SUCCESS if status else ButtonStyle.DANGER
    buttons.append([InlineKeyboardButton(text=status_text, callback_data=status_cb, style=status_style)])

    if status:
        prov = user_settings.get('lyrics_provider', 'lrclib')
        row_prov = []
        
        # --- LOGIKA WARNA PROVIDER ---
        # Jika dipilih -> Hijau, Jika tidak -> Default
        
        style_lrclib = ButtonStyle.SUCCESS if prov == 'lrclib' else ButtonStyle.DEFAULT
        row_prov.append(InlineKeyboardButton(
            text=f"{'' if prov=='lrclib' else ''}LRCLib", 
            callback_data="uset_ly_p_lrclib", 
            style=style_lrclib
        ))
        
        style_musix = ButtonStyle.SUCCESS if prov == 'musixmatch' else ButtonStyle.DEFAULT
        row_prov.append(InlineKeyboardButton(
            text=f"{'' if prov=='musixmatch' else ''}Musixmatch", 
            callback_data="uset_ly_p_musixmatch", 
            style=style_musix
        ))
        
        style_genius = ButtonStyle.SUCCESS if prov == 'genius' else ButtonStyle.DEFAULT
        row_prov.append(InlineKeyboardButton(
            text=f"{'' if prov=='genius' else ''}Genius", 
            callback_data="uset_ly_p_genius", 
            style=style_genius
        ))
        
        buttons.append(row_prov)
        
        # --- LOGIKA WARNA TIPE LYRICS ---
        
        l_type = user_settings.get('lyrics_type', 'plain')
        row_type = []
        
        style_plain = ButtonStyle.SUCCESS if l_type == 'plain' else ButtonStyle.DEFAULT
        row_type.append(InlineKeyboardButton(
            text=f"{'' if l_type=='plain' else ''}Plain (Text)", 
            callback_data="uset_ly_t_plain", 
            style=style_plain
        ))
        
        style_synced = ButtonStyle.SUCCESS if l_type == 'synced' else ButtonStyle.DEFAULT
        row_type.append(InlineKeyboardButton(
            text=f"{'' if l_type=='synced' else ''}Synced (LRC)", 
            callback_data="uset_ly_t_synced", 
            style=style_synced
        ))
        
        buttons.append(row_type)

    # Tombol Back Biru
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="uset_back", style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(buttons)


def usetting_button(user_id: int = None) -> InlineKeyboardMarkup:
    buttons = []
    
    if tidal_manager:
        buttons.append([InlineKeyboardButton(text=f"Tidal Quality", callback_data=f"uset_tidal")])
        
    show_qobuz = False
    if BOT_QOBUZ_CLIENTS:
        show_qobuz = True
    elif qobuz_manager and qobuz_manager.has_private_session(user_id):
        show_qobuz = True
        
    if show_qobuz:
        buttons.append([InlineKeyboardButton(text=f"Qobuz Quality", callback_data=f"uset_qobuz")])
    
    if beatport_manager:
        if getattr(beatport_manager, 'global_clients', []) or beatport_manager.has_private_session(user_id):
            buttons.append([InlineKeyboardButton(text=f"Beatport Quality", callback_data=f"uset_beatport")])

    if beatsource_manager:
        if getattr(beatsource_manager, 'global_clients', []) or beatsource_manager.has_private_session(user_id):
            buttons.append([InlineKeyboardButton(text=f"Beatsource Quality", callback_data=f"uset_beatsource")])
    
    if soundcloud_manager and soundcloud_manager.get_client():
        buttons.append([InlineKeyboardButton(text=f"Soundcloud Quality", callback_data=f"uset_soundcloud")])
    
    show_deezer = False
    if deezer_manager:
        if deezer_manager.clients:
            show_deezer = True
        elif deezer_manager.has_private_session(user_id):
            show_deezer = True
    
    if show_deezer:
        buttons.append([InlineKeyboardButton(text=f"Deezer Quality", callback_data=f"uset_deezer")])
    
    if kkbox_manager and kkbox_manager.clients:
        buttons.append([InlineKeyboardButton(text=f"KKBox Quality", callback_data=f"uset_kkbox")])
    
    if idagio_manager and idagio_manager.clients:
        buttons.append([InlineKeyboardButton(text=f"Idagio Quality", callback_data=f"uset_idagio")])
    
    if bugs_manager and bugs_manager.clients:
        buttons.append([InlineKeyboardButton(text=f"Bugs Quality", callback_data=f"uset_bugs")])

    if moov_manager and moov_manager.clients:
        buttons.append([InlineKeyboardButton(text=f"Moov Quality", callback_data=f"uset_moov")])

    if livephish_manager and livephish_manager.clients:
        buttons.append([InlineKeyboardButton(text=f"LivePhish Quality", callback_data=f"uset_livephish")])

    if highresaudio_manager:
        buttons.append([InlineKeyboardButton(text=f"HighResAudio Quality", callback_data=f"uset_highresaudio")])
    
    if khinsider_manager:
        buttons.append([InlineKeyboardButton(text=f"Khinsider Quality", callback_data=f"uset_khinsider")])

    if amazon_manager:
        if getattr(amazon_manager, 'global_clients', []) or amazon_manager.has_private_session(user_id):
            buttons.append([InlineKeyboardButton(text=f"Amazon Quality", callback_data=f"uset_amazon")])

    buttons.append([InlineKeyboardButton(text="🔁 Switch Upload Mode", callback_data="uset_upload_mode")])

    buttons.append([InlineKeyboardButton(text="LYRICS SETTINGS", callback_data="uset_lyrics")])
    
    user_dict = bot_set.user_data.get(user_id, {})

    is_playlist = user_dict.get("PLAYLIST_ZIP", False)
    style_playlist = ButtonStyle.SUCCESS if is_playlist else ButtonStyle.DANGER
    buttons.append([InlineKeyboardButton(text="PLAYLIST_ZIP", callback_data="zip_playlist", style=style_playlist)])

    is_album = user_dict.get("ALBUM_ZIP", False)
    style_album = ButtonStyle.SUCCESS if is_album else ButtonStyle.DANGER
    buttons.append([InlineKeyboardButton(text="ALBUM_ZIP", callback_data="zip_album", style=style_album)])

    is_poster = user_dict.get("ART_POSTER", False)
    style_poster = ButtonStyle.SUCCESS if is_poster else ButtonStyle.DANGER
    buttons.append([InlineKeyboardButton(text="ART_POSTER", callback_data="zip_poster", style=style_poster)])
    
    buttons.append([InlineKeyboardButton(text="Close", callback_data="uset_close", style=ButtonStyle.DANGER)])
    
    return InlineKeyboardMarkup(buttons)
