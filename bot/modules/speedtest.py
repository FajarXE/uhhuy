import asyncio
import speedtest
from pyrogram import Client, filters
from config import Config

# Filter Admin
admin_only = filters.user(list(Config.ADMINS))

@Client.on_message(filters.command(["speedtest", "speed"]) & admin_only)
async def speedtest_handler(client, message):
    m = await message.reply_text("🚀 **Menjalankan Speedtest...**\nMohon tunggu sebentar...", quote=True)
    
    try:
        # Jalankan di thread terpisah agar bot tidak macet (blocking)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_speedtest)
        
        # Format Text Output
        output_text = (
            "**Speedtest Results:**\n\n"
            f"**ISP:** {result['client']['isp']}\n"
            f"**Ping:** {result['ping']} ms\n"
            f"**Download:** {result['download_str']}\n"
            f"**Upload:** {result['upload_str']}"
        )
        
        # Kirim Gambar Hasil
        await message.reply_photo(
            photo=result['share'],
            caption=output_text
        )
        await m.delete()
        
    except Exception as e:
        await m.edit(f"❌ **Speedtest Gagal:**\n`{e}`")

def run_speedtest():
    # Inisialisasi Speedtest
    s = speedtest.Speedtest()
    s.get_best_server()
    s.download()
    s.upload()
    
    res = s.results.dict()
    
    # Konversi bit ke Mbit
    d_mbit = res["download"] / 1024 / 1024
    u_mbit = res["upload"] / 1024 / 1024
    
    # Tambahkan string format yang rapi ke dictionary hasil
    res['download_str'] = f"{d_mbit:.2f} Mbit/s"
    res['upload_str'] = f"{u_mbit:.2f} Mbit/s"
    
    return res
