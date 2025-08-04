import os
import json
import time
import traceback
import subprocess
import boto3
from yt_dlp import YoutubeDL
from urllib.parse import parse_qs, urlparse

DOWNLOAD_DIR = "/tmp"
SEGMENT_DURATION = os.environ["SEGMENT_DURATION"]
BUCKET_NAME = os.environ["BUCKET_NAME"]
REGION = os.environ["AWS_REGION"]

dynamodb = boto3.resource("dynamodb", region_name=REGION)
jobs_table = dynamodb.Table(os.environ["JOBS_TABLE_NAME"])
s3 = boto3.client("s3", region_name=REGION)
sqs = boto3.client("sqs", region_name=REGION)

def extract_video_id(url):
    # get the video ID from the v query parameter
    query = urlparse(url).query
    params = parse_qs(query)
    return params.get("v", [None])[0]

def download_audio(url, cookies_path=None):
    # download audio only
    # use cookies.txt for YouTube authentication
    ydl_opts = {
        "format": "bestaudio",
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
        "concurrent_fragment_downloads": 5,
        "cookiefile": cookies_path if cookies_path and os.path.exists(cookies_path) else None,
        "cachedir": False,
        "quiet": True,
        "retries": 3,
        "fragment_retries": 3,
        "geo_bypass": True,
        "nocheckcertificate": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav"
            }
        ]
    }

    with YoutubeDL(ydl_opts) as ydl:
        # download the audio file and return filename
        print(f"Downloading: {url}{' with cookies' if cookies_path and os.path.exists(cookies_path) else ''}")
        info = ydl.extract_info(url, download=True)
        filename = os.path.splitext(ydl.prepare_filename(info))[0] + ".wav"
        print(f"Downloaded: {url} to {filename}")

        # serialize metadata
        metadata = json.dumps(info)

        return filename, metadata

def split_audio(file_path, base_name):
    # prepare output directory for audio chunks
    output_dir = os.path.join(DOWNLOAD_DIR, base_name)
    os.makedirs(output_dir, exist_ok=True)

    # create consistent output pattern
    output_pattern = os.path.join(output_dir, f"{base_name}_%03d.wav")

    # split audio file into chunks using ffmpeg
    print(f"Splitting audio: {file_path}")
    subprocess.run([
        "ffmpeg",
        "-i", file_path,
        "-f", "segment",
        "-segment_time", SEGMENT_DURATION,
        "-c", "copy",
        "-reset_timestamps", "1",
        output_pattern
    ], check=True)
    print(f"Split audio into chunks in: {output_dir}")

    return output_dir

def upload_chunks(output_dir, metadata, video_id):
    # upload metadata file to S3
    metadata_key = f"metadata/{video_id}.json"
    print(f"Uploading metadata to s3://{BUCKET_NAME}/{metadata_key}")
    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=metadata_key,
        Body=metadata,
        ContentType='application/json'
    )
    print(f"Uploaded metadata to s3://{BUCKET_NAME}/{metadata_key}")

    # loop through the chunks in the output directory and upload them to S3
    for filename in os.listdir(output_dir):
        file_path = os.path.join(output_dir, filename)
        s3_key = f"audio/{video_id}/{filename}"
        print(f"Uploading {file_path} to s3://{BUCKET_NAME}/{s3_key}")
        s3.upload_file(file_path, BUCKET_NAME, s3_key)
        print(f"Uploaded {file_path} to s3://{BUCKET_NAME}/{s3_key}")

def process_message(message):
    try:
        body = json.loads(message["Body"])
        url = body.get("url")
        if not url:
            print("No 'url' in message")
            return

        video_id = extract_video_id(url)
        if not video_id:
            print(f"Could not extract video ID from URL: {url}")
            return

        print(f"Processing video: {video_id}")

        # download audio and pass in the cookies.txt file in the same directory
        downloaded_file, metadata = download_audio(url, 'cookies.txt')

        # split the audio into chunks
        output_dir = split_audio(downloaded_file, video_id)

        # upload chunks and metadata to S3
        upload_chunks(output_dir, metadata, video_id)

        # empty tmp directory
        subprocess.run(["rm", "-rf", os.path.join(DOWNLOAD_DIR, "*")], check=True)

        jobs_table.put_item(
            Item={
                "video_id": video_id,
                "status": "IN_PROGRESS",
                "segment_count": len(os.listdir(output_dir)),
                "segments_processed": 0
            }
        )
        
        print(f"Finished processing video: {video_id}")

    except Exception as e:
        print(f"Error processing {video_id}: {str(e)}")
        traceback.print_exc()
        jobs_table.put_item(
            Item={
                "video_id": video_id,
                "status": "FAILED"
            }
        )
    
    finally:
        receipt_handle = message["ReceiptHandle"]
        sqs.delete_message(
            QueueUrl=os.environ["DOWNLOAD_QUEUE_URL"],
            ReceiptHandle=receipt_handle
        )

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

        except Exception as e:
            print(f"Error polling for messages: {str(e)}")
            traceback.print_exc()
            time.sleep(5)

if __name__ == "__main__":
    main()
