import os
from dotenv import load_dotenv
import requests
from requests_auth_aws_sigv4 import AWSSigV4
import boto3

load_dotenv()

session = boto3.Session()
credentials = session.get_credentials()
region = session.region_name

auth = AWSSigV4(
    credentials=credentials,
    region=region,
    service='lambda'
)

url = os.getenv('DOWNLOAD_LAMBDA_URL')
if url is None:
    raise ValueError("DOWNLOAD_LAMBDA_URL environment variable is not set")
response = requests.get(url, auth=auth)
print(response.status_code, response.text)
