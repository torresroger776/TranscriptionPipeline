import boto3
import psycopg2
import os

def lambda_handler(event, context):
    REGION = os.environ["AWS_REGION"]
    DB_HOST = os.environ["DB_HOST"]
    DB_USER = os.environ["DB_USER"]
    DB_NAME = os.environ["DB_NAME"]

    print(f"Connecting to RDS instance...")
    session = boto3.Session()
    rds = session.client("rds")
    print(f"Generating authentication token for RDS...")
    token = rds.generate_db_auth_token(
        DBHostname=DB_HOST,
        Port=5432,
        DBUsername=DB_USER,
        Region=REGION
    )

    try:
        print(f"Connecting to the database...")
        conn = psycopg2.connect(
            host=DB_HOST,
            port=5432,
            user=DB_USER,
            password=token,
            sslmode='require',
            dbname=DB_NAME
        )

        with conn, conn.cursor() as cur:
            print(f"Querying database for tables...")
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public';
            """)
            tables = cur.fetchall()

            for (table_name,) in tables:
                print(f"\nTable: {table_name}")
                cur.execute("""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                        AND table_name = %s
                    ORDER BY ordinal_position;
                """, (table_name,))
                columns = cur.fetchall()
                for col_name, col_type in columns:
                    print(f"Column: {col_name}, Type: {col_type}")

        return { "statusCode": 200, "message": "Success" }

    except Exception as e:
        return { "statusCode": 500, "message": f"Error: {str(e)}" }
