from .tr_en import EN

class HI(EN):
    __language__ = 'hi'
#----------------
#
# बुनियादी जानकारी
#
#----------------
    WELCOME_MSG = "नमस्ते {}"
    DOWNLOADING = 'डाउनलोड हो रहा है........'
    DOWNLOAD_PROGRESS = """
<b>╭─ प्रगति
│
├ {0}
│
├ पूरा हुआ : <code>{1} / {2}</code>
│
├ शीर्षक : <code>{3}</code>
│
╰─ प्रकार : <code>{4}</code></b>
"""
    UPLOADING = 'अपलोड हो रहा है........'
    ZIPPING = 'जिप किया जा रहा है........'
    TASK_COMPLETED = "डाउनलोड समाप्त हुआ"




#----------------
#
# सेटिंग पैनल
#
#----------------
    INIT_SETTINGS_PANEL = '<b>बॉट सेटिंग्स में आपका स्वागत है</b>'
    LANGUAGE_PANEL = 'यहां बॉट की भाषा चुनें'

    TELEGRAM_PANEL = """
<b>टेलीग्राम सेटिंग्स</b>

एडमिन्स : {2}
अधिकृत उपयोगकर्ता : {3}
अधिकृत चैट्स : {4}
"""
    BAN_AUTH_FORMAT = 'उपयोग करें /command {userid}'
    BAN_ID = 'हटा दिया गया {}'
    USER_DOEST_EXIST = "यह आईडी मौजूद नहीं है"
    USER_EXIST = 'यह आईडी पहले से मौजूद है'
    AUTH_ID = 'सफलतापूर्वक अधिकृत'





#----------------
#
# बटन
#
#----------------
    MAIN_MENU_BUTTON = 'मुख्य मेन्यू'
    CLOSE_BUTTON = 'बंद करें'

    TELEGRAM = 'टेलीग्राम'
    CORE = 'कोर'
    PROVIDERS = 'प्रोवाइडर्स'

    LANGUAGE = 'भाषा'
    
    QOBUZ = 'Qobuz'
    DEEZER = 'Deezer'
    BOT_PUBLIC = 'बॉट सार्वजनिक - {}'
    BOT_LANGUAGE = 'भाषा'
    ANTI_SPAM = 'एंटी स्पैम - {}'

    POST_ART_BUT = "आर्ट पोस्टर : {}"

    SORT_PLAYLIST = 'प्लेलिस्ट को क्रमबद्ध करें : {}'

    PLAYLIST_CONC_BUT = "प्लेलिस्ट एक साथ : {}"
    ARTIST_BATCH_BUT = 'कलाकार बैच अपलोड : {}'

    QOBUZ_QUALITY_PANEL = '<b>यहां Qobuz गुणवत्ता संपादित करें</b>'

    RCLONE_LINK = 'प्रत्यक्ष लिंक'
    INDEX_LINK = 'इंडेक्स लिंक'
#----------------
#
# त्रुटियाँ
#
#----------------
    ERR_NO_LINK = 'कोई लिंक नहीं मिला :('
    ERR_LINK_RECOGNITION = "क्षमा करें, दिए गए लिंक को पहचानने में असमर्थ हैं।"
    ERR_QOBUZ_NOT_STREAMABLE = "यह ट्रैक/एल्बम डाउनलोड के लिए उपलब्ध नहीं है।"
    ERR_QOBUZ_NOT_AVAILABLE = "यह ट्रैक आपके क्षेत्र में उपलब्ध नहीं है।"
#----------------
#
# ट्रैक और एल्बम पोस्ट्स
#
#----------------
    ALBUM_TEMPLATE = """
🎶 <b>शीर्षक :</b> {title}
👤 <b>कलाकार :</b> {artist}
📅 <b>रिलीज़ तिथि :</b> {date}
🔢 <b>कुल ट्रैक :</b> {totaltracks}
📀 <b>कुल वॉल्यूम :</b> {totalvolume}
💫 <b>गुणवत्ता :</b> {quality}
📡 <b>प्रोवाइडर :</b> {provider}
🔞 <b>स्पष्ट :</b> {explicit}
"""

    PLAYLIST_TEMPLATE = """
🎶 <b>शीर्षक :</b> {title}
🔢 <b>कुल ट्रैक :</b> {totaltracks}
💫 <b>गुणवत्ता :</b> {quality}
📡 <b>प्रोवाइडर :</b> {provider}
"""

    SIMPLE_TITLE = """
नाम : {0}
प्रकार : {1}
प्रोवाइडर : {2}
"""
