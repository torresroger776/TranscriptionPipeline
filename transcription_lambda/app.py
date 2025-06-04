import json
import boto3
import os
import subprocess
import traceback

s3 = boto3.client("s3")

MODEL_PATH = os.environ.get("WHISPER_MODEL_PATH", "models/ggml-tiny.en.bin")
OUTPUT_DIR = "/tmp"

def lambda_handler(event, context):
    print("Event received:", json.dumps(event))

    try:
        # check if model file exists
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"Model file not found: {MODEL_PATH}")

        # identify the audio file in the S3 event
        s3_record = event["Records"][0]["s3"]
        bucket = s3_record["bucket"]["name"]
        key = s3_record["object"]["key"]
        filename = os.path.basename(key)
        local_path = os.path.join("/tmp", filename)

        # download the audio file from S3
        print(f"Downloading s3://{bucket}/{key} to {local_path}")
        s3.download_file(bucket, key, local_path)

        # trancribe the audio file using whisper.cpp and store as JSON
        print(f"Running transcription on {local_path} using model {os.path.basename(MODEL_PATH)}")
        output_file_base = os.path.join(OUTPUT_DIR, os.path.splitext(filename)[0])
        command = [
            "./build/bin/whisper-cli",
            "-m", MODEL_PATH,
            "-f", local_path,
            "-of", output_file_base,
            "-oj"
        ]
        subprocess.run(command, check=True)

        video_id = key.split('/')[1]
        output_json_path = f"{output_file_base}.json"
        s3_output_key = f"transcripts/{video_id}/{os.path.basename(output_json_path)}"
        
        # upload the JSON transcription to S3
        print(f"Uploading {output_json_path} to s3://{bucket}/{s3_output_key}")
        s3.upload_file(output_json_path, bucket, s3_output_key)

        return {
            "statusCode": 200,
            "body": json.dumps("Transcription completed.")
        }
    
    except subprocess.CalledProcessError as e:
        print(f"Transcription process failed: {str(e)}")
        traceback.print_exc()
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Transcription failed", "details": str(e)})
        }

    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        traceback.print_exc()
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Unexpected error", "details": str(e)})
        }
