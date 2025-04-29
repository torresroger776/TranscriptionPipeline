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

# get the url from user input
url = input("Enter a YouTube video URL: ")

# get the API invoke URL from environment variable
invoke_url = os.getenv("API_INVOKE_URL")
if invoke_url is None:
    raise ValueError("API_INVOKE_URL environment variable is not set")

# make the API request
response = requests.post(invoke_url, auth=auth, json={
    "url": url
})
print(response.status_code, response.text)
