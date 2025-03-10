FROM apache/airflow:2.10.5

RUN pip install apache-airflow==2.10.5

USER root
RUN apt update && apt -y install ffmpeg && apt -y install curl
RUN curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/bin/yt-dlp
RUN chmod a+rx /usr/bin/yt-dlp

USER airflow