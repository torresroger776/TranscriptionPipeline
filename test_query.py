import os
from dotenv import load_dotenv
import requests
from requests_auth_aws_sigv4 import AWSSigV4
import boto3

load_dotenv()

# get AWS credentials
session = boto3.Session()
credentials = session.get_credentials()
region = session.region_name
auth = AWSSigV4(
    credentials=credentials,
    region=region,
    service='execute-api'
)

# get query parameters from user input
platform_name = input("Enter the platform name: ")

channel_id_or_tag = input("Choose channel ID or tag (id/tag): ")
if channel_id_or_tag not in ['id', 'tag', '']:
    raise ValueError("Invalid input. Please enter 'id' or 'tag' or leave blank.")
if channel_id_or_tag:
    channel_value = input(f"Enter the channel {channel_id_or_tag}: ")

if not channel_id_or_tag:
    video_id = input("Enter the video ID: ")
    if not video_id:
        raise ValueError("Video ID is required if channel ID or tag is not provided.")
else:
    video_id_or_title = input("Choose video ID or title (id/title): ")
    if video_id_or_title not in ['id', 'title', '']:
        raise ValueError("Invalid input. Please enter 'id' or 'title' or leave blank.")
    if video_id_or_title:
        video_value = input(f"Enter the video {video_id_or_title}: ")

keywords = input("Enter keywords to search: ")
start_date = input("Enter start date (YYYY-MM-DD) or leave blank: ")
end_date = input("Enter end date (YYYY-MM-DD) or leave blank: ")

# prepare the query parameters
query_params = {
    "platform_name": platform_name,
    "start_date": start_date.strip() if start_date else None,
    "end_date": end_date.strip() if end_date else None,
    "q": keywords.strip() if keywords else ''
}

if channel_id_or_tag:
    query_params['channel_id' if channel_id_or_tag == 'id' else 'channel_tag'] = channel_value.strip()

if video_id:
    query_params['video_id'] = video_id.strip()
elif video_id_or_title:
    query_params['video_id' if video_id_or_title == 'id' else 'video_title'] = video_value.strip()

print("Query parameters:", query_params)

# get the query API invoke URL from environment variable
invoke_url = os.getenv("QUERY_API_INVOKE_URL")
if invoke_url is None:
    raise ValueError("QUERY_API_INVOKE_URL environment variable is not set")

try:
    # make the API request
    response = requests.get(invoke_url, auth=auth, params=query_params)
    print(response.status_code, response.text)
except requests.exceptions.RequestException as e:
    print(f"An error occurred: {e}")
