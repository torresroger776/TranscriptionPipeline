CREATE TABLE IF NOT EXISTS date_dim (
    date_id SERIAL PRIMARY KEY,
    date DATE NOT NULL UNIQUE,
    year INT NOT NULL,
    month INT NOT NULL,
    day INT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_dim (
    video_sk SERIAL PRIMARY KEY,
    date_id INT REFERENCES date_dim(date_id),
    video_id VARCHAR(255) NOT NULL UNIQUE,
    video_title VARCHAR(255) NOT NULL,
    video_description TEXT,
    channel_id VARCHAR(255) NOT NULL,
    channel_name VARCHAR(255) NOT NULL,
    channel_tag VARCHAR(255) NOT NULL,
    platform_name VARCHAR(50) NOT NULL
);

CREATE TABLE IF NOT EXISTS transcript_fact (
  transcript_line_id SERIAL PRIMARY KEY,
  video_sk INT REFERENCES video_dim(video_sk),
  start_time INT NOT NULL,
  end_time INT NOT NULL,
  text TEXT NOT NULL,
  CONSTRAINT video_and_time_unique UNIQUE (video_sk, start_time, end_time)
);

CREATE INDEX IF NOT EXISTS text_fts_idx ON transcript_fact USING GIN(to_tsvector('english', text));
CREATE INDEX IF NOT EXISTS video_id_idx ON video_dim(video_id);
CREATE INDEX IF NOT EXISTS channel_id_idx ON video_dim(channel_id);
CREATE INDEX IF NOT EXISTS channel_tag_idx ON video_dim(channel_tag);
CREATE INDEX IF NOT EXISTS date_idx ON date_dim(date);