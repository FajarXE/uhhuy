# [GANTI FILE: Dockerfile]
FROM --platform=linux/amd64 ubuntu:26.04 AS base

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Jakarta \
    PIP_BREAK_SYSTEM_PACKAGES=1

WORKDIR /usr/src/app

# Menginstal dependensi inti, termasuk Python 3, pip, dan header pengembangan (python3-dev)
RUN apt-get update -qq && \
    apt-get install -qq -y python3 python3-pip python3-dev \
    ffmpeg gcc libffi-dev curl zip cargo pkg-config git aria2 && \
    rm -rf /var/lib/apt/lists/*

FROM --platform=linux/amd64 base AS builder
RUN apt-get update -qq && \
    apt-get install -qq -y git wget unzip && \
    rm -rf /var/lib/apt/lists/*

# Mengunduh rclone
RUN curl -O https://downloads.rclone.org/v1.75.1/rclone-v1.75.1-linux-amd64.zip && \
    unzip rclone-v1.75.1-linux-amd64.zip && \
    install -m 755 rclone-v1.75.1-linux-amd64/rclone /usr/bin/rclone && \
    rm -rf rclone-v1.75.1-linux-amd64*

# Mengunduh mp4decrypt (Bento4)
RUN wget https://www.bok.net/Bento4/binaries/Bento4-SDK-1-6-0-640.x86_64-unknown-linux.zip && \
    unzip Bento4-SDK-1-6-0-640.x86_64-unknown-linux.zip -d bento4 && \
    install -m 755 bento4/Bento4-SDK-1-6-0-640.x86_64-unknown-linux/bin/mp4decrypt /usr/bin/mp4decrypt && \
    rm -rf Bento4* bento4

FROM --platform=linux/amd64 base AS final

COPY --from=builder /usr/bin/rclone /usr/bin/rclone
COPY --from=builder /usr/bin/mp4decrypt /usr/bin/mp4decrypt
COPY requirements.txt .

# Menggunakan modul pip bawaan python3 untuk menginstal dependensi
RUN python3 -m pip install --no-cache-dir -r requirements.txt
COPY . .

ENTRYPOINT ["bash", "start.sh"]
