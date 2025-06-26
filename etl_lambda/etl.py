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

s3 = boto3.client("s3")
queries = load_queries()

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
            for line in transcript_data['transcription']:
                start_time = line['offsets']['from'] // 1000 + segment_number * SEGMENT_DURATION
                end_time = line['offsets']['to'] // 1000 + segment_number * SEGMENT_DURATION
                text = line['text'].strip()

                cur.execute(queries['insert_transcript_fact'], {
                    'video_sk': video_sk,
                    'start_time': start_time,
                    'end_time': end_time,
                    'text': text
                })

            conn.commit()
            cur.close()
            conn.close()

            print(f"Successfully processed transcript: {transcript_key}")
            return {"statusCode": 200, "body": f"Processed {transcript_key}"}
        
        except Exception as e:
            print(f"Error processing transcript {transcript_key}: {str(e)}")
            return {"statusCode": 500, "body": f"Error processing {transcript_key}: {str(e)}"}
