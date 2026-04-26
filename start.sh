#!/bin/bash

# Menjalankan daemon aria2c secara native (--daemon=true) dan listen ke semua interface (--rpc-listen-all=true)
aria2c --daemon=true --enable-rpc --rpc-listen-all=true --rpc-listen-port=6800 -j 20 --max-connection-per-server=16 --split=16 --min-split-size=1M --continue=true --allow-overwrite=true --rpc-max-request-size=1024M --seed-time=0

# Menjalankan bot utama
python3 -m bot
