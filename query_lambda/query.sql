SELECT
    t.transcript_line_id,
    t.start_time,
    t.end_time,
    t.text,
    v.video_id,
    v.video_title,
    v.channel_id,
    v.channel_name,
    v.channel_tag,
    v.platform_name,
    d.date
FROM transcript_fact t
JOIN video_dim v ON t.video_sk = v.video_sk
JOIN date_dim d ON v.date_id = d.date_id
WHERE 1 = 1
-- filters
ORDER BY d.date, t.start_time
LIMIT 100;
