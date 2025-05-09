FROM python:3.13.3-slim

WORKDIR /app

COPY . /app/

RUN apt-get update && \
    apt-get install -y ffmpeg && \
    pip install -U pip && \
    pip install --no-cache-dir -r requirements.txt && \
    rm -rf /var/lib/apt/lists/*

CMD ["python", "download_worker.py"]
