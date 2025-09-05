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

def decrement_batch_remaining(video_id):
    try:
        job_item = jobs_table.get_item(Key={"video_id": video_id}).get('Item')
        batch_key = job_item.get('batch_key') if job_item else None
        if batch_key:
            batch_resp = jobs_table.update_item(
                Key={"video_id": batch_key},
                UpdateExpression="SET remaining = if_not_exists(remaining, :zero) - :one",
                ExpressionAttributeValues={":one": 1, ":zero": 0},
                ReturnValues="ALL_NEW"
            )
            remaining = batch_resp['Attributes'].get('remaining', 0)
            if remaining <= 0:
                jobs_table.update_item(
                    Key={"video_id": batch_key},
                    UpdateExpression="SET #s = :status",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":status": "COMPLETED"}
                )
    except Exception:
        pass

def extract_video_ids_from_channel_or_playlist(url):
    try:
        print(f"Extracting video IDs from: {url}")
        
        ydl_opts = {
            "extract_flat": True,
            "quiet": True,
            "no_warnings": True,
            "cookiefile": 'cookies.txt' if os.path.exists('cookies.txt') else None,
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if 'entries' in info:
                video_ids = []
                for entry in info['entries']:
                    if entry and 'id' in entry:
                        video_ids.append(entry['id'])
                
                print(f"Extracted {len(video_ids)} video IDs from {url}")
                return video_ids
            else:
                if 'id' in info:
                    return [info['id']]
                else:
                    print(f"No video IDs found in {url}")
                    return []
                    
    except Exception as e:
        print(f"Error extracting video IDs from {url}: {str(e)}")
        traceback.print_exc()
        return []

def submit_video_to_sqs(video_id, batch_key=None):
    try:
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        message_body = {
            "url": video_url,
            "type": "video",
            "source": "batch_extraction"
        }
        if batch_key:
            message_body["batch_key"] = batch_key
        
        sqs.send_message(
            QueueUrl=os.environ["DOWNLOAD_QUEUE_URL"],
            MessageBody=json.dumps(message_body)
        )
        print(f"Submitted video ID to SQS: {video_id}")
        
    except Exception as e:
        print(f"Error submitting video ID {video_id} to SQS: {str(e)}")
        raise

def extract_channel_or_playlist_id(url):
    parsed = urlparse(url)
    path = parsed.path or ""
    query = parse_qs(parsed.query or "")

    if 'list' in query and query['list']:
        return query['list'][0]

    path_parts = [p for p in path.split('/') if p]
    if len(path_parts) >= 2 and path_parts[0] == 'channel':
        return path_parts[1]
    if len(path_parts) >= 1 and path_parts[0].startswith('@'):
        return path_parts[0]
    return url

def process_batch_request(url, max_videos=None):
    try:
        print(f"Processing batch request for: {url}")
        
        video_ids = extract_video_ids_from_channel_or_playlist(url)
        
        if not video_ids:
            print(f"No video IDs extracted from {url}")
            return False
        
        if isinstance(max_videos, int) and max_videos > 0:
            original_count = len(video_ids)
            video_ids = video_ids[:max_videos]
            print(f"Limiting videos from {original_count} to {len(video_ids)} due to max_videos={max_videos}")
        
        batch_key = extract_channel_or_playlist_id(url)
        try:
            jobs_table.put_item(Item={
                "video_id": batch_key,
                "status": "IN_PROGRESS",
                "remaining": len(video_ids),
            })
        except Exception:
            pass

        for video_id in video_ids:
            submit_video_to_sqs(video_id, batch_key=batch_key)
        
        print(f"Batch processing completed. {len(video_ids)} videos submitted to SQS.")
        return True
        
    except Exception as e:
        print(f"Batch processing failed: {str(e)}")
        traceback.print_exc()
        try:
            batch_key = extract_channel_or_playlist_id(url)
            jobs_table.update_item(
                Key={"video_id": batch_key},
                UpdateExpression="SET #s = :status",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":status": "FAILED"}
            )
        except Exception:
            pass
        return False

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
        message_type = body.get("type", "video")
        max_videos = body.get("max_videos")
        batch_key = body.get("batch_key")
        
        if not url:
            print("No 'url' in message")
            return

        if message_type in ["channel", "playlist"]:
            print(f"Processing batch request: {url} (type: {message_type})")
            success = process_batch_request(url, max_videos=max_videos)
            if success:
                print(f"Batch processing completed successfully for: {url}")
            else:
                print(f"Batch processing failed for: {url}")
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

        # update job status in DynamoDB
        response = jobs_table.get_item(Key={"video_id": video_id})
        if response.get("Item"):
            jobs_table.update_item(
                Key={"video_id": video_id},
                UpdateExpression="SET #s = :status",
                ConditionExpression="#s != :failed",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":status": "IN_PROGRESS",
                    ":failed": "FAILED"
                }
            )
        else:
            jobs_table.put_item(
                Item={
                    "video_id": video_id,
                    "status": "IN_PROGRESS",
                    "segment_count": len(os.listdir(output_dir)),
                    "segments_processed": 0,
                    **({"batch_key": batch_key} if batch_key else {}),
                }
            )
        
        print(f"Finished processing video: {video_id}")

    except Exception as e:
        print(f"Error processing message: {str(e)}")
        traceback.print_exc()
        
        try:
            body = json.loads(message["Body"])
            url = body.get("url", "")
            message_type = body.get("type", "video")
            if url and message_type == "video":
                video_id = extract_video_id(url)
                if video_id:
                    jobs_table.put_item(
                        Item={
                            "video_id": video_id,
                            "status": "FAILED"
                        }
                    )
                    decrement_batch_remaining(video_id)
        except:
            pass
    
    finally:
        # empty tmp directory
        subprocess.run(["find", DOWNLOAD_DIR, "-mindepth", "1", "-delete"], check=True)

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
