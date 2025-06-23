CREATE TABLE datetime_dim (
    datetime_id SERIAL PRIMARY KEY,
    datetime TIMESTAMPTZ NOT NULL,
    date DATE NOT NULL,
    year INT NOT NULL,
    month INT NOT NULL,
    day INT NOT NULL,
    hour INT NOT NULL,
    minute INT NOT NULL
);

CREATE TABLE video_dim (
    video_sk SERIAL PRIMARY KEY,
    datetime_id INT REFERENCES datetime_dim(datetime_id),
    video_id VARCHAR(255) NOT NULL UNIQUE,
    video_title VARCHAR(255) NOT NULL,
    video_description TEXT,
    channel_id VARCHAR(255) NOT NULL,
    channel_name VARCHAR(255) NOT NULL,
    channel_tag VARCHAR(255) NOT NULL,
    platform_name VARCHAR(50) NOT NULL
);

CREATE TABLE transcript_fact (
  transcript_line_id SERIAL PRIMARY KEY,
  video_sk INT REFERENCES video_dim(video_sk),
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  text TEXT NOT NULL
);

CREATE INDEX text_fts_idx ON transcript_fact USING GIN(to_tsvector('english', text));
CREATE INDEX video_id_idx ON video_dim(video_id);
CREATE INDEX channel_id_idx ON video_dim(channel_id);
CREATE INDEX channel_tag_idx ON video_dim(channel_tag);
CREATE INDEX datetime_idx ON datetime_dim(datetime);