-- insert_date_dim
INSERT INTO date_dim
(date, year, month, day)
VALUES (%(date)s, %(year)s, %(month)s, %(day)s)
ON CONFLICT (date) DO UPDATE SET date = EXCLUDED.date
RETURNING date_id;

-- insert_video_dim
INSERT INTO video_dim
(date_id, video_id, video_title, video_description, channel_id, channel_name, channel_tag, platform_name)
VALUES (%(date_id)s, %(video_id)s, %(video_title)s, %(video_description)s, %(channel_id)s, %(channel_name)s, %(channel_tag)s, %(platform_name)s)
ON CONFLICT (video_id) DO UPDATE SET video_id = EXCLUDED.video_id
RETURNING video_sk;

-- insert_transcript_fact
INSERT INTO transcript_fact
(video_sk, start_time, end_time, text)
VALUES (%s, %s, %s, %s)
ON CONFLICT ON CONSTRAINT video_and_time_unique DO NOTHING;
