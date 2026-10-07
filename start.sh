#!/bin/bash

# Menjalankan daemon aria2c
aria2c --daemon=true --enable-rpc --rpc-listen-all=true --rpc-listen-port=6800 -j 20 --max-connection-per-server=1 --split=1 --min-split-size=5M --continue=true --allow-overwrite=true --rpc-max-request-size=1024M --seed-time=0

# Menjalankan API Scraper Audiomack di latar belakang
uvicorn audiomack_api.main:app --host 127.0.0.1 --port 8000 &

# BERI JEDA 15 DETIK AGAR API BENAR-BENAR SIAP SEBELUM BOT JALAN
sleep 15

# Menjalankan bot utama
python3 -m bot
