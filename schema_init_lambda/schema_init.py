import psycopg2
import os

def lambda_handler(event, context):
    DB_HOST = os.environ["DB_HOST"]
    DB_NAME = os.environ["DB_NAME"]
    DB_USER = os.environ["DB_USER"]
    DB_PASSWORD = os.environ["DB_PASSWORD"]

    try:
        # connect to RDS database
        conn = psycopg2.connect(
            host=DB_HOST,
            port=5432,
            user=DB_USER,
            password=DB_PASSWORD,
            sslmode='require',
            dbname=DB_NAME
        )

        with conn, conn.cursor() as cur:
            with open("schema.sql", "r") as f:
                # grant IAM authentication permission to master user
                cur.execute(f"GRANT rds_iam TO {DB_USER};")

                # execute schema creation script
                cur.execute(f.read())
                
                conn.commit()

        return { "statusCode": 200, "body": "Schema created successfully" }
    
    except Exception as e:
        return { "statusCode": 500, "body": f"Error creating schema: {str(e)}" }