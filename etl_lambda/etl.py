import os
import json
import boto3
import psycopg2

REGION = os.environ["AWS_REGION"]
DB_HOST = os.environ["DB_HOST"]
DB_USER = os.environ["DB_USER"]
DB_NAME = os.environ["DB_NAME"]
SEGMENT_DURATION = int(os.environ["SEGMENT_DURATION"])

def load_queries(path='etl.sql'):
    queries = {}
    with open(path) as f:
        content = f.read()
        current_key = None
        current_sql = []
        for line in content.splitlines():
            if line.startswith("--"):
                if current_key and current_sql:
                    queries[current_key] = "\n".join(current_sql).strip()
                current_key = line[2:].strip()
                current_sql = []
            else:
                current_sql.append(line)
        if current_key and current_sql:
            queries[current_key] = "\n".join(current_sql).strip()
    return queries

dynamodb = boto3.resource("dynamodb")
jobs_table = dynamodb.Table(os.environ["JOBS_TABLE_NAME"])
s3 = boto3.client("s3") 

queries = load_queries()

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

def lambda_handler(event, context):
    for record in event['Records']:
        bucket = record['s3']['bucket']['name']
        transcript_key = record['s3']['object']['key']
        
        video_id = transcript_key.split('/')[1]
        segment_number = int(transcript_key.split('/')[-1].split('.')[0].split('_')[-1])
        metadata_key = f'metadata/{video_id}.json'

        print(f"Retrieving transcript: {transcript_key} from bucket: {bucket}")
        transcript_obj = s3.get_object(Bucket=bucket, Key=transcript_key)
        transcript_data = json.loads(transcript_obj['Body'].read().decode('utf-8'))

        print(f"Retrieving metadata: {metadata_key} from bucket: {bucket}")
        metadata_obj = s3.get_object(Bucket=bucket, Key=metadata_key)
        metadata = json.loads(metadata_obj['Body'].read().decode('utf-8'))

        try:
            session = boto3.Session()
            rds = session.client("rds")
            token = rds.generate_db_auth_token(
                DBHostname=DB_HOST,
                Port=5432,
                DBUsername=DB_USER,
                Region=REGION
            )

            print(f"Connecting to RDS database...")
            conn = psycopg2.connect(
                host=DB_HOST,
                port=5432,
                user=DB_USER,
                password=token,
                sslmode='require',
                dbname=DB_NAME
            )
            cur = conn.cursor()

            print(f"Inserting date dimension...")
            date_str = metadata['upload_date']
            year = int(date_str[:4])
            month = int(date_str[4:6])
            day = int(date_str[6:8])

            cur.execute(queries['insert_date_dim'], {
                'date': f"{year}-{month:02d}-{day:02d}",
                'year': year,
                'month': month,
                'day': day
            })
            date_id = cur.fetchone()[0]

            print(f"Inserting video dimension...")
            cur.execute(queries['insert_video_dim'], {
                'date_id': date_id,
                'video_id': metadata['id'],
                'video_title': metadata['title'],
                'video_description': metadata['description'],
                'channel_id': metadata['channel_id'],
                'channel_name': metadata['channel'],
                'channel_tag': metadata['uploader_id'],
                'platform_name': 'YouTube'
            })
            video_sk = cur.fetchone()[0]

            print(f"Inserting transcript line facts...")
            transcript_lines = []
            for line in transcript_data['transcription']:
                start_time = line['offsets']['from'] // 1000 + segment_number * SEGMENT_DURATION
                end_time = line['offsets']['to'] // 1000 + segment_number * SEGMENT_DURATION
                text = line['text'].strip()

                transcript_lines.append((
                    video_sk,
                    start_time,
                    end_time,
                    text
                ))
            cur.executemany(queries['insert_transcript_fact'], transcript_lines)
            print(f"Inserted {len(transcript_lines)} transcript lines for video: {metadata['id']}_{segment_number}" )

            conn.commit()
            cur.close()
            conn.close()

            print(f"Successfully inserted data for video: {metadata['id']}_{segment_number}")

            # update job status in DynamoDB
            print(f"Updating job status for video: {metadata['id']}_{segment_number}")
            response = jobs_table.update_item(
                Key={"video_id":  metadata['id']},
                UpdateExpression="SET segments_processed = segments_processed + :inc",
                ExpressionAttributeValues={":inc": 1},
                ReturnValues="ALL_NEW"
            )
            segments_processed = response['Attributes']['segments_processed']
            segment_count = response['Attributes']['segment_count']

            if segments_processed == segment_count:
                jobs_table.update_item(
                    Key={"video_id": metadata['id']},
                    UpdateExpression="SET #s = :status",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":status": "COMPLETED"}
                )
                
                decrement_batch_remaining(metadata['id'])

            print(f"Successfully processed transcript: {transcript_key}")
        
        except Exception as e:
            jobs_table.update_item(
                Key={"video_id": metadata['id']},
                UpdateExpression="SET #s = :status",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":status": "FAILED"}
            )

            decrement_batch_remaining(metadata['id'])

            print(f"Error processing transcript {transcript_key}: {str(e)}")
            return {"statusCode": 500, "body": f"Error processing {transcript_key}: {str(e)}"}

    return {"statusCode": 200, "body": "Success"}
