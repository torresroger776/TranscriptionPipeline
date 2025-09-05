import argparse
import boto3
import json
import os
import re
import requests
import sys
import time
from dotenv import load_dotenv
from requests_auth_aws_sigv4 import AWSSigV4
from urllib.parse import urlparse, parse_qs

load_dotenv()

POLL_TIMEOUT = int(os.getenv("POLL_TIMEOUT", 1800))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 30))

# get AWS credentials
session = boto3.Session()
credentials = session.get_credentials()
region = session.region_name
auth = AWSSigV4(
    credentials=credentials,
    region=region,
    service='execute-api'
)

dynamodb = boto3.resource('dynamodb', region_name=region)
jobs_table = dynamodb.Table(os.getenv("JOBS_TABLE_NAME"))

def extract_batch_key(url):
    parsed = urlparse(url)
    path = parsed.path or ""
    query = parse_qs(parsed.query or "")

    if 'list' in query and query['list']:
        return query['list'][0]

    parts = [p for p in path.split('/') if p]
    if len(parts) >= 2 and parts[0] == 'channel':
        return parts[1]
    if len(parts) >= 1 and parts[0].startswith('@'):
        return parts[0]
    return url

def submit_video(url):
    submit_url = os.getenv("SUBMIT_API_INVOKE_URL")
    if submit_url is None:
        print("SUBMIT_API_INVOKE_URL environment variable is not set")
        sys.exit(1)

    resp = requests.post(submit_url, auth=auth, json={"url": url})
    if resp.status_code == 200:
        print(f"Video transcription request for {url} submitted successfully")
    else:
        print(f"Video transcription request for {url} failed: {resp.status_code} {resp.text}")
        sys.exit(1)

def submit_channel_or_playlist(url, max_videos=None):
    submit_url = os.getenv("SUBMIT_API_INVOKE_URL")
    if submit_url is None:
        print("SUBMIT_API_INVOKE_URL environment variable is not set")
        sys.exit(1)

    if is_channel_url(url):
        submission_type = "channel"
    elif is_playlist_url(url):
        submission_type = "playlist"
    else:
        print(f"URL {url} is not a valid channel or playlist URL")
        sys.exit(1)

    message_body = {
        "url": url,
        "type": submission_type
    }
    if max_videos is not None:
        message_body["max_videos"] = max_videos

    resp = requests.post(submit_url, auth=auth, json=message_body)
    if resp.status_code == 200:
        print(f"{submission_type.capitalize()} batch processing request for {url} submitted successfully")
    else:
        print(f"{submission_type.capitalize()} batch processing request for {url} failed: {resp.status_code} {resp.text}")
        sys.exit(1)

def is_channel_url(url):
    if extract_platform_name(url) != "YouTube":
        return False
    
    parsed = urlparse(url)
    path = parsed.path

    channel_patterns = [
        r'^/channel/[^/]+(/.*)?$',
        r'^/c/[^/]+(/.*)?$',
        r'^/user/[^/]+(/.*)?$',
        r'^/@[^/]+(/.*)?$'
    ]
    
    return any(re.match(pattern, path) for pattern in channel_patterns)

def is_playlist_url(url):
    if extract_platform_name(url) != "YouTube":
        return False
    
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    return 'list' in query_params

def channel_exists(channel_id_or_tag, platform_name):
    query_url = os.getenv("QUERY_API_INVOKE_URL")
    if query_url is None:
        print("QUERY_API_INVOKE_URL environment variable is not set")
        sys.exit(1)
    
    params = {
        "q": "",
        ("channel_tag" if channel_id_or_tag.startswith("@") else "channel_id"): channel_id_or_tag,
        "platform_name": platform_name
    }
    resp = requests.get(query_url, auth=auth, params=params)
    if resp.status_code != 200:
        print(f"Error querying for channel {channel_id_or_tag}: {resp.status_code} {resp.text}")
        sys.exit(1)
    return len(resp.json()) > 0

def video_exists(video_id, platform_name):
    query_url = os.getenv("QUERY_API_INVOKE_URL")
    if query_url is None:
        print("QUERY_API_INVOKE_URL environment variable is not set")
        sys.exit(1)
    
    params = {
        "q": "",
        "video_id": video_id,
        "platform_name": platform_name
    }
    resp = requests.get(query_url, auth=auth, params=params)
    if resp.status_code != 200:
        print(f"Error querying for video {video_id}: {resp.status_code} {resp.text}")
        sys.exit(1)
    return len(resp.json()) > 0

def poll_for_transcript(video_id, timeout, interval):
    print("Waiting for video transcription to complete...")
    elapsed = 0
    while elapsed < timeout:
        response = jobs_table.get_item(Key={"video_id": video_id})
        item = response.get("Item")
        if item:
            status = item.get("status")
            if status == "FAILED":
                print(f"Video transcription for {video_id} failed. Try submitting again.")
                return False
            if status == "COMPLETED":
                print(f"Transcript for video {video_id} is ready")
                return True
        time.sleep(interval)
        elapsed += interval
    print(f"Transcript polling timed out. Use transcribe query to check status.")
    return False

def poll_for_batch(batch_key, timeout, interval):
    print("Waiting for channel/playlist batch processing to complete...")
    elapsed = 0
    while elapsed < timeout:
        response = jobs_table.get_item(Key={"video_id": batch_key})
        item = response.get("Item")
        if item:
            status = item.get("status")
            if status == "FAILED":
                print("Batch processing failed. Try submitting again.")
                return False
            if status == "COMPLETED":
                print("Batch processing completed")
                return True
        time.sleep(interval)
        elapsed += interval
    print("Batch polling timed out.")
    return False

def run_query(args):
    query_url = os.getenv("QUERY_API_INVOKE_URL")
    if query_url is None:
        print("QUERY_API_INVOKE_URL environment variable is not set")
        sys.exit(1)
    
    params = {
        "q": args.q,
        "platform_name": args.platform_name
    }
    if args.channel_id:
        params["channel_id"] = args.channel_id
    if args.channel_tag:
        params["channel_tag"] = args.channel_tag
    if args.video_id:
        params["video_id"] = args.video_id
    if args.start_date:
        params["start_date"] = args.start_date
    if args.end_date:
        params["end_date"] = args.end_date
    if args.video_title:
        params["video_title"] = args.video_title

    resp = requests.get(query_url, auth=auth, params=params)
    if resp.status_code != 200:
        print(f"Error running query: {resp.status_code} {resp.text}")
        sys.exit(1)

    results = resp.json()

    if args.output:
        if not args.output.endswith('.json'):
            print("Output file must have .json extension")
            sys.exit(1)
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"Query results saved to {args.output}")
    else:
        if results:
            for result in results:
                print("\nVideo URL:", result["video_url"])
                print("Text:", result["text"])
                print("Date:", result["upload_date"])
                print("Title:", result["video_title"])
        else:
            print("No results found for the query.")

def extract_platform_name(url):
    url_parsed = urlparse(url)
    hostname = url_parsed.hostname

    if hostname and hostname.startswith("www."):
        hostname = hostname[4:]

    if hostname in ("youtube.com", "youtu.be", "m.youtube.com"):
        return "YouTube"
    else:
        print("Unsupported platform. Only YouTube is supported.")
        sys.exit(1)

def extract_video_id(url):
    url_parsed = urlparse(url)
    hostname = url_parsed.hostname

    if hostname and hostname.startswith("www."):
        hostname = hostname[4:]

    match extract_platform_name(url):
        case "YouTube":
            if "youtu.be" in hostname:
                video_id = url_parsed.path.lstrip('/')
            else:
                qs = parse_qs(url_parsed.query)
                video_id = qs.get("v", [None])[0]

            if not video_id or not re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
                print("Invalid YouTube video URL. Please provide a valid URL.")
                sys.exit(1)
        case _:
            print("Unsupported platform. Only YouTube is supported.")
            sys.exit(1)
    
    return video_id

def build_url(video_id, platform_name):
    if platform_name == "YouTube":
        return f"https://www.youtube.com/watch?v={video_id}"
    else:
        print("Unsupported platform.")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Submit video transcription requests and query results.")
    
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit_parser = subparsers.add_parser("submit", help="Submit a video, channel, or playlist for transcription")
    submit_parser.add_argument("--url", required=True, help="Video, channel, or playlist URL for submission")
    submit_parser.add_argument("--type", choices=["auto", "video", "channel", "playlist"], default="auto", 
                              help="Type of submission (auto-detected if not specified)")
    submit_parser.add_argument("--max-videos", type=int, default=None, help="Maximum number of videos to process for channel/playlist submissions")
    submit_parser.add_argument("--wait", action="store_true", help="Wait for batch processing to complete for channel/playlist submissions")
    
    query_parser = subparsers.add_parser("query", help="Query video transcriptions")
    query_parser.add_argument("--q", required=True, help="Keywords for query")
    query_parser.add_argument("--channel_tag", help="Channel tag")
    query_parser.add_argument("--channel_id", help="Channel ID")
    query_parser.add_argument("--platform_name", required=True, help="Platform name (e.g. YouTube)")
    query_parser.add_argument("--video_id", help="Video ID")
    query_parser.add_argument("--start_date", help="Start date filter")
    query_parser.add_argument("--end_date", help="End date filter")
    query_parser.add_argument("--video_title", help="Filter by video title")
    query_parser.add_argument("--auto-transcribe", action="store_true", help="Automatically transcribe video if not found")
    query_parser.add_argument("--output", help="Output JSON file for query results")

    args = parser.parse_args()

    if args.command == "submit":
        url = args.url
        
        if args.type == "auto":
            if is_channel_url(url):
                submission_type = "channel"
            elif is_playlist_url(url):
                submission_type = "playlist"
            elif extract_platform_name(url) == "YouTube":
                submission_type = "video"
            else:
                print("Unsupported URL type. Please provide a valid YouTube video, channel, or playlist URL.")
                sys.exit(1)
        else:
            submission_type = args.type
        
        if submission_type in ["channel", "playlist"]:
            submit_channel_or_playlist(url, max_videos=args.max_videos)
            
            if args.wait:
                batch_key = extract_batch_key(url)
                if not poll_for_batch(batch_key, POLL_TIMEOUT, POLL_INTERVAL):
                    sys.exit(1)
        else:
            video_id = extract_video_id(url)
            if video_exists(video_id, extract_platform_name(url)):
                print("Video already exists. No need to submit again.")
                sys.exit(0)
            
            submit_video(url)

            if not poll_for_transcript(video_id, POLL_TIMEOUT, POLL_INTERVAL):
                sys.exit(1)

    elif args.command == "query":
        channel = args.channel_tag or args.channel_id
        if not channel and not args.video_id:
            print("One of channel_tag, channel_id, or video_id required for query command.")
            sys.exit(1)
        
        if channel and not channel_exists(channel, args.platform_name):
            print("Channel not found. Please submit a video first.")
            sys.exit(1)

        # auto-transcribe if the video provided does not have a transcript
        if args.video_id and not video_exists(args.video_id, args.platform_name):
            if args.auto_transcribe:
                print(f"Submitting video {args.video_id} for transcription...")
                submit_video(build_url(args.video_id, args.platform_name))
                
                if not poll_for_transcript(args.video_id, POLL_TIMEOUT, POLL_INTERVAL):
                    sys.exit(1)
            else:
                print("Video not found. Use --auto-transcribe or submit it first.")
                sys.exit(1)

        run_query(args)
