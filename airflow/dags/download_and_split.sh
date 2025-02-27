yt-dlp --concurrent-fragments 5 --format m4a/bestaudio/best --output '%(id)s.%(ext)s' https://www.youtube.com/watch?v=${VIDEO_ID}
mkdir ${VIDEO_ID}
ffmpeg -i ${VIDEO_ID}.m4a -f segment -segment_time 900 -c copy -reset_timestamps 1 ${VIDEO_ID}\\${VIDEO_ID}_%03d.m4a
rm ${VIDEO_ID}.m4a