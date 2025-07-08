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
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 10))

# get AWS credentials
session = boto3.Session()
credentials = session.get_credentials()
region = session.region_name
auth = AWSSigV4(
    credentials=credentials,
    region=region,
    service='execute-api'
)

def submit_video(url):
    submit_url = os.getenv("SUBMIT_API_INVOKE_URL")
    if submit_url is None:
        print("SUBMIT_API_INVOKE_URL environment variable is not set")
        sys.exit(1)

    resp = requests.post(submit_url, auth=auth, json={"url": url})
    if resp.status_code == 200:
        print(f"Video transcription request for {url} submitted successfully!")
    else:
        print(f"Video transcription request for {url} failed: {resp.status_code} {resp.text}")
        sys.exit(1)

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

def poll_for_transcript(video_id, platform_name, timeout, interval):
    print("Waiting for video transcription to complete...")
    elapsed = 0
    while elapsed < timeout:
        if video_exists(video_id, platform_name):
            print(f"Transcript ready after {elapsed} sec!")
            return True
        time.sleep(interval)
        elapsed += interval
    print(f"Error: Transcript operation timed out.")
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

    print(f"Running query: {params}")
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
                print("Rank:", result.get("rank", "N/A"))
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

def main():
    parser = argparse.ArgumentParser(description="Submit video transcription requests and query results.")
    
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit_parser = subparsers.add_parser("submit", help="Submit a video for transcription")
    submit_parser.add_argument("--url", required=True, help="Video URL for submission")
    
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
    query_parser.add_argument("--url", action="store_true", help="Pass in video URL for --auto-transcribe")

    args = parser.parse_args()

    if args.command == "submit":
        if video_exists(extract_video_id(args.url), extract_platform_name(args.url)):
            print("Video already exists. No need to submit again.")
            sys.exit(0)
        
        submit_video(args.url)

    elif args.command == "query":
        channel = args.channel_tag or args.channel_id
        if not channel and not args.video_id:
            print("One of channel_tag, channel_id, and video_id required for query command.")
            sys.exit(1)
        
        if channel and not channel_exists(channel, args.platform_name):
            print("Channel not found. Please submit a video first.")
            sys.exit(1)

        if args.video_id and not video_exists(args.video_id, args.platform_name):
            if args.auto_transcribe:
                if not args.url:
                    print("--url is required for --auto-transcribe to submit the missing video.")
                    sys.exit(1)

                # validate URL
                video_id = extract_video_id(args.url)

                print("Submitting video for transcription...")
                submit_video(args.url)
                
                if not poll_for_transcript(video_id, channel, args.platform_name, POLL_TIMEOUT, POLL_INTERVAL):
                    sys.exit(1)
            else:
                print("Video not found. Use --auto-transcribe or submit it first.")
                sys.exit(1)

        run_query(args)
