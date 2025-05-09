import os
import json
import time
import traceback
import subprocess
import boto3
from yt_dlp import YoutubeDL
from urllib.parse import parse_qs, urlparse

DOWNLOAD_DIR = "/tmp"
SEGMENT_DURATION = 900
BUCKET_NAME = os.environ["BUCKET_NAME"]
TRANSCRIPTION_QUEUE_URL = os.environ["TRANSCRIPTION_QUEUE_URL"]
REGION = os.environ["AWS_REGION"]

s3 = boto3.client("s3", region_name=REGION)
sqs = boto3.client("sqs", region_name=REGION)

def extract_video_id(url):
    # get the video ID from the v query parameter
    query = urlparse(url).query
    params = parse_qs(query)
    return params.get("v", [None])[0]

def download_audio(url, cookies_path=None):
    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
        "concurrent_fragment_downloads": 5,
        "cookiefile": cookies_path if cookies_path and os.path.exists(cookies_path) else None,
        "cachedir": False,
        "quiet": True,
        "retries": 3,
        "fragment_retries": 3,
        "geo_bypass": True,
        "nocheckcertificate": True
    }

    with YoutubeDL(ydl_opts) as ydl:
        # download the audio file and return filename
        print(f"Downloading: {url}{' with cookies' if cookies_path and os.path.exists(cookies_path) else ''}")
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        print(f"Downloaded: {url} to {filename}")
        return filename

def split_audio(file_path, output_dir, base_name):
    os.makedirs(output_dir, exist_ok=True)
    output_pattern = os.path.join(output_dir, f"{base_name}_%03d.m4a")

    # split audio file into segments using ffmpeg
    print(f"Splitting audio: {file_path}")
    subprocess.run([
        "ffmpeg",
        "-i", file_path,
        "-f", "segment",
        "-segment_time", str(SEGMENT_DURATION),
        "-c", "copy",
        "-reset_timestamps", "1",
        output_pattern
    ], check=True)
    print(f"Split audio into segments in: {output_dir}")

def upload_and_notify_chunks(output_dir, video_id):
    # loop through the files in the output directory and upload them to S3
    for filename in sorted(os.listdir(output_dir)):
        file_path = os.path.join(output_dir, filename)
        s3_key = f"raw/{video_id}/{filename}"
        print(f"Uploading {file_path} to s3://{BUCKET_NAME}/{s3_key}")
        s3.upload_file(file_path, BUCKET_NAME, s3_key)

        # send message to SQS queue for transcription for each segment
        print(f"Notifying transcription service for {s3_key}")
        msg_body = json.dumps({
            "video_id": video_id,
            "filename": filename,
            "s3_key": s3_key,
            "bucket": BUCKET_NAME
        })
        sqs.send_message(QueueUrl=TRANSCRIPTION_QUEUE_URL, MessageBody=msg_body)

def process_message(message):
    body = json.loads(message["Body"])
    url = body.get("url")
    if not url:
        print("No 'url' in message")
        return

    video_id = extract_video_id(url)
    if not video_id:
        print(f"Could not extract video ID from URL: {url}")
        return

    try:
        print(f"Processing video: {video_id}")
        downloaded_file = download_audio(url, 'cookies.txt')
        output_dir = os.path.join(DOWNLOAD_DIR, video_id)
        split_audio(downloaded_file, output_dir, video_id)
        os.remove(downloaded_file)
        upload_and_notify_chunks(output_dir, video_id)
        print(f"Finished processing video: {video_id}")

    except Exception as e:
        print(f"Error processing {video_id}: {str(e)}")
        traceback.print_exc()

def main():
    # set up worker to listen to SQS queue for download requests
    while True:
        try:
            # long polling to receive messages from SQS
            response = sqs.receive_message(
                QueueUrl=os.environ["DOWNLOAD_QUEUE_URL"],
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20
            )

            messages = response.get("Messages", [])
            if not messages:
                continue

            for message in messages:
                process_message(message)

                receipt_handle = message["ReceiptHandle"]
                sqs.delete_message(
                    QueueUrl=os.environ["DOWNLOAD_QUEUE_URL"],
                    ReceiptHandle=receipt_handle
                )

        except Exception as e:
            print(f"Error: {str(e)}")
            traceback.print_exc()
            time.sleep(5)

if __name__ == "__main__":
    main()
