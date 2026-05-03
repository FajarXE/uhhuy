# [GANTI FILE: Dockerfile]
FROM --platform=linux/amd64 python:3.12-slim AS base

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Jakarta

WORKDIR /usr/src/app

RUN apt-get update -qq && \
    apt-get install -qq -y ffmpeg gcc libffi-dev curl zip cargo pkg-config git aria2 && \
    rm -rf /var/lib/apt/lists/*

FROM --platform=linux/amd64 base AS builder
RUN apt-get update -qq && \
    apt-get install -qq -y git wget unzip && \
    rm -rf /var/lib/apt/lists/*

RUN curl -O https://downloads.rclone.org/v1.70.2/rclone-v1.70.2-linux-amd64.zip && \
    unzip rclone-v1.70.2-linux-amd64.zip && \
    install -m 755 rclone-v1.70.2-linux-amd64/rclone /usr/bin/rclone && \
    rm -rf rclone-v1.70.2-linux-amd64*

RUN wget https://www.bok.net/Bento4/binaries/Bento4-SDK-1-6-0-640.x86_64-unknown-linux.zip && \
    unzip Bento4-SDK-1-6-0-640.x86_64-unknown-linux.zip -d bento4 && \
    install -m 755 bento4/Bento4-SDK-1-6-0-640.x86_64-unknown-linux/bin/mp4decrypt /usr/bin/mp4decrypt && \
    rm -rf Bento4* bento4

FROM --platform=linux/amd64 base AS final

COPY --from=builder /usr/bin/rclone /usr/bin/rclone
COPY --from=builder /usr/bin/mp4decrypt /usr/bin/mp4decrypt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENTRYPOINT ["bash", "start.sh"]
