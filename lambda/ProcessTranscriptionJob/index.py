import json
import boto3
import os

sqs = boto3.client('sqs')
queue_url = os.environ['QUEUE_URL']

def handler(event, context):
    # get video url
    body = json.loads(event['body'])
    url = body.get('url')
    if not url:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "url required"})
        }

    # send url to SQS queue
    message = {"url": url}
    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(message))
    return {
        "statusCode": 200,
        "body": json.dumps({"status": "enqueued"})
    }
