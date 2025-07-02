import os
import json
import boto3
import psycopg2
from urllib.parse import quote

REGION = os.environ["AWS_REGION"]
DB_HOST = os.environ["DB_HOST"]
DB_USER = os.environ["DB_USER"]
DB_NAME = os.environ["DB_NAME"]

def lambda_handler(event, context):
    filters = event.get("queryStringParameters", {}) or {}
    keywords = filters.pop("q", None)

    where_clauses = []
    params = {}

    valid_filters = {
        "video_id", "channel_id", "channel_tag", "platform_name"
    }

    print("Checking if filters are valid")
    channel_ok = "channel_id" in filters or "channel_tag" in filters
    platform_ok = "platform_name" in filters
    keywords = keywords.strip() if keywords else None

    if not (channel_ok and platform_ok and keywords):
        return {
            "statusCode": 400,
            "body": "Bad Request: Must provide 'channel_id' or 'channel_tag', 'platform_name', and 'q' (keywords)."
        }

    for key, value in filters.items():
        if key in valid_filters:
            where_clauses.append(f"{key} = %({key})s")
            params[key] = value
    
    if "start_date" in filters:
        where_clauses.append("d.date >= %(start_date)s")
        params["start_date"] = filters["start_date"]

    if "end_date" in filters:
        where_clauses.append("d.date <= %(end_date)s")
        params["end_date"] = filters["end_date"]

    if "video_title" in filters:
        where_clauses.append("to_tsvector('english', v.video_title) @@ plainto_tsquery('english', %(video_title)s)")
        params["video_title"] = filters['video_title']

    if keywords:
        where_clauses.append("to_tsvector('english', t.text) @@ plainto_tsquery('english', %(q)s)")
        params["q"] = keywords

    with open("query.sql") as f:
        base_query = f.read()

    print("Building SQL query")
    if where_clauses:
        filter_sql = " AND " + " AND ".join(where_clauses)
        final_query = base_query.replace("-- filters", filter_sql)
    else:
        final_query = base_query.replace("-- filters", "")

    try:
        session = boto3.Session()
        rds = session.client("rds")
        token = rds.generate_db_auth_token(
            DBHostname=DB_HOST,
            Port=5432,
            DBUsername=DB_USER,
            Region=REGION
        )

        print("Connecting to RDS database...")
        conn = psycopg2.connect(
            host=DB_HOST,
            port=5432,
            user=DB_USER,
            password=token,
            sslmode="require",
            dbname=DB_NAME
        )
        cur = conn.cursor()

        print("Executing query")
        cur.execute(final_query, params)
        rows = cur.fetchall()

        columns = [desc[0] for desc in cur.description]

        results = []
        for row in rows:
            start_time = max(0, row[columns.index("start_time")] - 2)
            video_id = row[columns.index("video_id")]

            results.append({
                "video_url": f"https://www.youtube.com/watch?v={quote(video_id)}&t={start_time}s",
                "text": row[columns.index("text")],
                "video_title": row[columns.index("video_title")],
                "channel_name": row[columns.index("channel_name")],
                "upload_date": row[columns.index("date")],
            })

        cur.close()
        conn.close()

        return {
            "statusCode": 200,
            "body": json.dumps(results, default=str)
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": f"Error querying database: {str(e)}"
        }
