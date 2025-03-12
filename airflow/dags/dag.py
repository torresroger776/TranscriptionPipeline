from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.providers.google.cloud.transfers.local_to_gcs import LocalFilesystemToGCSOperator

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
        env={'VIDEO_ID': '{{dag_run.conf["video_id"]}}'},
        append_env=True,
        cwd='{{ dag_run.dag.folder }}'
    )

    store_audio_in_gcs = LocalFilesystemToGCSOperator(
        task_id='store_audio_in_gcs',
        src='{{ dag_run.dag.folder }}/{{dag_run.conf["video_id"]}}/*',
        dst='audio_files/{{dag_run.conf["video_id"]}}/',
        bucket='transcription-project-store',
        gcp_conn_id='google_cloud_default'
    )

    download_and_split_video >> store_audio_in_gcs