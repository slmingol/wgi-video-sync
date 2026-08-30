FROM docker.io/library/python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt analyze.py process.py entrypoint.sh ./
RUN pip install --no-cache-dir --root-user-action=ignore -q --upgrade pip \
    && pip install --no-cache-dir --root-user-action=ignore -q -r requirements.txt \
    && chmod +x entrypoint.sh

# Default working dir is /videos so relative paths (config.json, output/) land in the mount
WORKDIR /videos

ENTRYPOINT ["/app/entrypoint.sh"]
