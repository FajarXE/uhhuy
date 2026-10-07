#!/bin/bash

# Menjalankan daemon aria2c
aria2c --daemon=true --enable-rpc --rpc-listen-all=true --rpc-listen-port=6800 -j 20 --max-connection-per-server=1 --split=1 --min-split-size=5M --continue=true --allow-overwrite=true --rpc-max-request-size=1024M --seed-time=0

# Menjalankan API Scraper Audiomack dan menyimpan lognya
uvicorn audiomack_api.main:app --host 127.0.0.1 --port 8000 > uvicorn_error.log 2>&1 &

# Beri jeda agar browser Playwright termuat
sleep 15

# Mencetak log Uvicorn ke terminal Northflank agar kita tahu jika ada error
echo "=== LOG UVICORN AUDIOMACK ==="
cat uvicorn_error.log
echo "============================="

# Menjalankan bot utama
python3 -m bot
