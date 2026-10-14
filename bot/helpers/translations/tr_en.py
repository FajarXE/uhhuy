class EN(object):
    __language__ = 'en'
#----------------
#
# BASICS
#
#----------------
    WELCOME_MSG = "ʜᴇʟʟᴏ {}"
    DOWNLOADING = 'ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ........'
    DOWNLOAD_PROGRESS = """
<b>╭─ ᴘʀᴏɢʀᴇss
│
├ {0}
│
├ ᴅᴏɴᴇ : <code>{1} / {2}</code>
│
├ ᴛɪᴛʟᴇ : <code>{3}</code>
│
╰─ ᴛʏᴘᴇ : <code>{4}</code></b>
"""
    UPLOADING = 'ᴜᴘʟᴏᴀᴅɪɴɢ........'
    ZIPPING = 'ᴢɪᴘᴘɪɴɢ........'
    TASK_COMPLETED = "ᴅᴏᴡɴʟᴏᴀᴅ ғɪɴɪsʜᴇᴅ"

#----------------
#
# SETTINGS PANEL
#
#----------------
    INIT_SETTINGS_PANEL = '<b>Welcome to Bot Settings</b>'
    LANGUAGE_PANEL = 'Select bot language here'
    CORE_PANEL = 'Edit main settings here\n\nP-Batch: Playlist Batch\nA-Batch: Artist Batch'
    PROVIDERS_PANEL = 'Configure each platform separately'

    TIDAL_PANEL = "Configure Tidal settings here"
    TIDAL_AUTH_PANEL = """
Manage auth of Tidal Account here

<b>Account :</b> <code>{}</code>
<b>Mobile HiRes :</b> <code>{}</code>
<b>Mobile Atmos :</b> <code>{}</code>
<b>TV/Auto : </b> <code>{}</code>
"""
    TIDAL_AUTH_URL = "Go to the below link for logging in\n{}"
    TIDAL_AUTH_SUCCESSFULL = 'Successfully logged in Tidal'
    TIDAL_REMOVED_SESSION = 'Successfully removed all sessions for Tidal'

    TELEGRAM_PANEL = """
<b>Telegram Settings</b>

Admins : {2}
Auth Users : {3}
Auth Chats : {4}
"""
    BAN_AUTH_FORMAT = 'Use /command {userid}'
    BAN_ID = 'Successfully Removed'
    USER_DOEST_EXIST = "This ID doesn't exist"
    USER_EXIST = 'This ID already exist'
    AUTH_ID = 'Successfully Authed'

#----------------
#
# BUTTONS
#
#----------------
    MAIN_MENU_BUTTON = 'MAIN MENU'
    CLOSE_BUTTON = 'CLOSE'
    PROVIDERS = 'PROVIDERS'
    TELEGRAM = 'Telegram'
    CORE = 'CORE'
    
    QOBUZ = 'Qobuz'
    DEEZER = 'Deezer'
    TIDAL = 'Tidal'

    BOT_PUBLIC = 'Bot Public - {}'
    BOT_LANGUAGE = 'Language'
    ANTI_SPAM = 'Anti Spam - {}'
    LANGUAGE = 'Language'
    QUALITY = 'Quality'
    AUTHORIZATION = "Authorizations"

    POST_ART_BUT = "Art Poster : {}"
    SORT_PLAYLIST = 'Sort Playlist : {}'
    DISABLE_SORT_LINK = 'Disable Sort Link : {}'
    PLAYLIST_CONC_BUT = "P-Batch DL : {}"
    PLAYLIST_ZIP = 'Zip Playlist : {}'
    ARTIST_BATCH_BUT = 'A-Batch Upload : {}'
    ARTIST_ZIP = 'Zip Artist : {}'
    ALBUM_ZIP = 'Zip Album : {}'

    QOBUZ_QUALITY_PANEL = '<b>Edit Qobuz Quality Here</b>'

    TIDAL_LOGIN_TV = 'Login TV'
    TIDAL_REMOVE_LOGIN = "Remove Login"
    TIDAL_REFRESH_SESSION = 'Refresh Auth'

    RCLONE_LINK = 'Direct Link'
    INDEX_LINK = 'Index Link'

#----------------
#
# ERRORS & WARNINGS
#
#----------------
    ERR_NO_LINK = 'No link found :('
    ERR_LINK_RECOGNITION = "Sorry, couldn't recognise the given link."
    ERR_QOBUZ_NOT_STREAMABLE = "This track/album is not available to download."
    ERR_QOBUZ_NOT_AVAILABLE = "This track is not available in your region"
    ERR_LOGIN_TIDAL_TV_FAILED = "Login failed : {}"
    WARNING_NO_TIDAL_TOKEN = 'No TV/Auto token-secret added'

#----------------
#
# TRACK & ALBUM POSTS
#
#----------------
    ALBUM_TEMPLATE = """
<b>ᴛɪᴛʟᴇ :</b> {title}
<b>ᴀʀᴛɪsᴛ :</b> {artist}
<b>ʀᴇʟᴇᴀsᴇ ᴅᴀᴛᴇ :</b> {release_date}
<b>ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs :</b> {totaltracks}
<b>ᴛᴏᴛᴀʟ ᴠᴏʟᴜᴍᴇs :</b> {totalvolume}
<b>ǫᴜᴀʟɪᴛʏ :</b> {quality}
<b>ᴘʀᴏᴠɪᴅᴇʀ :</b> {provider}
<b>ᴇxᴘʟɪᴄɪᴛ :</b> {explicit}
"""

    PLAYLIST_TEMPLATE = """
<b>ᴛɪᴛʟᴇ :</b> {title}
<b>ᴛᴏᴛᴀʟ ᴛʀᴀᴄᴋs :</b> {totaltracks}
<b>ǫᴜᴀʟɪᴛʏ :</b> {quality}
<b>ᴘʀᴏᴠɪᴅᴇʀ :</b> {provider}
"""

    SIMPLE_TITLE = """
ɴᴀᴍᴇ : {0}
ᴛʏᴘᴇ : {1}
ᴘʀᴏᴠɪᴅᴇʀ : {2}
"""

    # [FIX] Masuk ke dalam indentasi class EN agar tidak memicu AttributeError
    ARTIST_TEMPLATE = """
<b>ᴀʀᴛɪsᴛ :</b> {artist}
<b>ǫᴜᴀʟɪᴛʏ :</b> {quality}
<b>ᴘʀᴏᴠɪᴅᴇʀ :</b> {provider}
"""
