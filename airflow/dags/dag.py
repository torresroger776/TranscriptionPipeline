from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.providers.google.cloud.transfers.local_to_gcs import LocalFilesystemToGCSOperator

default_args = {
    'owner': 'me',
    'retries': 5,
    'retry_delay': timedelta(minutes=5)
}

video_id = '{{ dag_run.conf["video_id"] }}'

with DAG(
    'transcription_data_pipeline',
    default_args=default_args,
    schedule_interval='@once',
    start_date=datetime(2025, 1, 1)
) as dag:

    download_and_split_video = BashOperator(
        task_id='download_and_split_video',
        bash_command='download_and_split.sh',
        env={'VIDEO_ID': video_id},
        append_env=True,
        cwd='/opt/airflow/'
    )

    store_audio_in_gcs = LocalFilesystemToGCSOperator(
        task_id='store_audio_in_gcs',
        src=f'/opt/airflow/{video_id}/*',
        dst=f'audio_files/{video_id}/',
        bucket='transcription-project-store',
        gcp_conn_id='google_cloud_default'
    )

    cleanup_files = BashOperator(
        task_id='cleanup_files',
        bash_command=f'rm -rf /opt/airflow/{video_id}',
        cwd='/opt/airflow/'
    )

    download_and_split_video >> store_audio_in_gcs >> cleanup_files