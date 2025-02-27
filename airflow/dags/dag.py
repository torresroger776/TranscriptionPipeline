from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    'owner': 'me',
    'retries': 5,
    'retry_delay': timedelta(minutes=5)
}

with DAG(
    'transcription_data_pipeline',
    default_args=default_args,
    schedule_interval='@once',
    start_date=datetime(2025, 1, 1)
) as dag:

    download_and_split_video = BashOperator(
        task_id='download_and_split_video',
        bash_command='download_and_split.sh',
        env={'VIDEO_ID': '6TlUsYH0UI4'},
        cwd='{{ dag_run.dag.folder }}'
    )

    download_and_split_video