from bot import CMD
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

import bot.helpers.translations as lang

from ..settings import bot_set
from ..helpers.buttons.settings import *
from ..helpers.database.mongo_async import database
from ..helpers.message import send_message, edit_message, check_user, fetch_user_details



@Client.on_message(filters.command(CMD.SETTINGS))
async def settings(c, message):
    if await check_user(message.from_user.id, restricted=True):
        user = await fetch_user_details(message)
        await send_message(user, lang.s.INIT_SETTINGS_PANEL, markup=main_menu())


@Client.on_callback_query(filters.regex(pattern=r"^corePanel"))
async def core_cb(client: Client, cb: CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        await edit_message(
            cb.message,
            lang.s.CORE_PANEL,
            core_buttons()
        )



@Client.on_callback_query(filters.regex(pattern=r"^upload"))
async def upload_mode_cb(client: Client, cb: CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        modes = ['Local', 'Telegram']
        modes_count = 2
        if bot_set.rclone:
            modes.append('RCLONE')
            modes_count+=1

        current = modes.index(bot_set.upload_mode)
        nexti = (current + 1) % modes_count
        bot_set.upload_mode = modes[nexti]
        await database.set_variable('UPLOAD_MODE', modes[nexti])
        await core_cb(client, cb)


@Client.on_callback_query(filters.regex(pattern=r"^linkOption"))
async def link_option_cb(client: Client, cb: CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        options = ['False', 'Index', 'RCLONE', 'Both']
        current = options.index(bot_set.link_options)
        nexti = (current + 1) % 4
        bot_set.link_options = options[nexti]
        await database.set_variable('RCLONE_LINK_OPTIONS', options[nexti])
        await core_cb(client, cb)


@Client.on_callback_query(filters.regex(pattern=r"^albArt"))
async def alb_art_cb(client, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        art_post = bot_set.art_poster
        art_post = False if art_post else True
        bot_set.art_poster = art_post
        await database.set_variable('ART_POSTER', art_post)
        await core_cb(client, cb)

@Client.on_callback_query(filters.regex(pattern=r"^playCONC"))
async def playlist_conc_cb(client, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        play_conc = bot_set.playlist_conc
        play_conc = False if play_conc else True
        bot_set.playlist_conc = play_conc
        await database.set_variable('PLAYLIST_CONCURRENT', play_conc)
        await core_cb(client, cb)


@Client.on_callback_query(filters.regex(pattern=r"^artBATCH"))
async def artist_conc_cb(client, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        artist_batch = bot_set.artist_batch
        artist_batch = False if artist_batch else True
        bot_set.artist_batch = artist_batch
        await database.set_variable('ARTIST_BATCH_UPLOAD', artist_batch)
        await core_cb(client, cb)

@Client.on_callback_query(filters.regex(pattern=r"^sortPlay"))
async def playlist_sort_cb(client, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        sort = bot_set.playlist_sort
        sort = False if sort else True
        bot_set.playlist_sort = sort
        await database.set_variable('PLAYLIST_SORT', sort)
        await core_cb(client, cb)


@Client.on_callback_query(filters.regex(pattern=r"^playZip"))
async def playlist_zip_cb(client, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        option = bot_set.playlist_zip
        option = False if option else True
        bot_set.playlist_zip = option
        await database.set_variable('PLAYLIST_ZIP', option)
        await core_cb(client, cb)


@Client.on_callback_query(filters.regex(pattern=r"^sortLinkPlay"))
async def playlist_disable_zip_link(client, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        option = bot_set.disable_sort_link
        option = False if option else True
        bot_set.disable_sort_link = option
        await database.set_variable('PLAYLIST_LINK_DISABLE', option)
        await core_cb(client, cb)


@Client.on_callback_query(filters.regex(pattern=r"^artZip"))
async def artist_zip_cb(client, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        option = bot_set.artist_zip
        option = False if option else True
        bot_set.artist_zip = option
        await database.set_variable('ARTIST_ZIP', option)
        await core_cb(client, cb)


@Client.on_callback_query(filters.regex(pattern=r"^albZip"))
async def album_zip_cb(client, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        option = bot_set.album_zip
        option = False if option else True
        bot_set.album_zip = option
        await database.set_variable('ALBUM_ZIP', option)
        await core_cb(client, cb)



#--------------------

# COMMON

#--------------------
@Client.on_callback_query(filters.regex(pattern=r"^main_menu"))
async def main_menu_cb(client, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        await edit_message(cb.message, lang.s.INIT_SETTINGS_PANEL, markup=main_menu())

@Client.on_callback_query(filters.regex(pattern=r"^close"))
async def close_cb(client, cb:CallbackQuery):
    if await check_user(cb.from_user.id, restricted=True):
        try:
            await client.delete_messages(
                chat_id=cb.message.chat.id,
                message_ids=cb.message.id
            )
        except:
            pass

@Client.on_message(filters.command(CMD.BAN))
async def ban(client: Client, msg: Message):
    if await check_user(msg.from_user.id, restricted=True):
        try:
            id_ = int(msg.text.split(" ", maxsplit=1)[1])
        except IndexError:
            await send_message(msg, lang.s.BAN_AUTH_FORMAT)
            return

        user = False if str(id_).startswith('-100') else True
        if user:
            if id_ in bot_set.auth_users:
                bot_set.auth_users.remove(id_)
                await database.authorize_users('AUTH_USERS', id_, True)
            else:
                await send_message(msg, lang.s.USER_DOEST_EXIST)
        else:
            if id_ in bot_set.auth_chats:
                bot_set.auth_chats.remove(id_)
                await database.authorize_chats('AUTH_CHATS', id_, True)
            else:
                await send_message(msg, lang.s.USER_DOEST_EXIST)
        await send_message(msg, lang.s.BAN_ID)
        

@Client.on_message(filters.command(CMD.AUTH + ["add"]))
async def auth(client: Client, msg: Message):
    if await check_user(msg.from_user.id, restricted=True):
        try:
            id_ = int(msg.text.split(" ", maxsplit=1)[1])
        except IndexError:
            await send_message(msg, lang.s.BAN_AUTH_FORMAT)
            return

        user = False if str(id_).startswith('-100') else True
        if user:
            if id_ not in bot_set.auth_users:
                bot_set.auth_users.append(id_)
                await database.authorize_users('AUTH_USERS', id_)
            else:
                await send_message(msg, lang.s.USER_EXIST)
        else:
            if id_ not in bot_set.auth_chats:
                bot_set.auth_chats.append(id_)
                await database.authorize_chats('AUTH_CHATS', id_)
            else:
                await send_message(msg, lang.s.USER_EXIST)
        await send_message(msg, lang.s.AUTH_ID)


@Client.on_message(filters.command(CMD.LOG))
async def send_log(client: Client, msg: Message):
    if await check_user(msg.from_user.id, restricted=True):
        user = await fetch_user_details(msg)
        await send_message(
            user, 
            './bot/bot_logs.log',
            'doc'
        )
