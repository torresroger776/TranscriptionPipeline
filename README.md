# Transcription Pipeline

**End-to-end AWS-based pipeline for downloading and transcribing videos, and querying video transcripts**

---

## Project Overview

This project demonstrates a scalable data pipeline that:

- Ingests videos via URL on-demand using an ECS download worker
- Splits audio into segments, stores them in S3, and triggers transcription
- Transcribes audio with a Lambda function
- Loads transcript data into a PostgreSQL RDS instance with full-text search capability
- Exposes a flexible query API to search transcripts by keywords, channel, video, and date filters

**Goal:** Give users a simple CLI to submit videos, auto-transcribe missing videos, and query transcripts, in case certain videos don't have automatic subtitles or exist on non-YouTube platforms.

---

## **Key Technologies**

* AWS API Gateway
* AWS Lambda (transcription, ETL, schema initialization, querying)
* AWS SQS
* AWS ECS (download worker)
* AWS S3 (audio segments, transcripts, metadata)
* PostgreSQL RDS
* Python (yt_dlp, boto3, psycopg2, etc.)
* Infrastructure as Code: CloudFormation

---

## **How It Works**

1. **Submit**

- The user submits a YouTube URL via the CLI.
- API Gateway enqueues the URL to SQS.
- An ECS service downloads the video, splits audio into 15-minute segments, and uploads them to S3 with metadata.

2. **Transcribe**

- S3 upload triggers a Lambda to transcribe audio segments with Whisper.
- The transcription JSON is stored back in S3.
- An ETL Lambda loads transcripts into PostgreSQL, using a date dimension, video dimension, and transcript fact table.

3. **Query**

- The user queries transcripts via the CLI.
- The query Lambda supports keyword search (full text search) and filters by channel, date range, video title, etc.
- Results include video URLs and timestamps where keywords appear.

4. **Smart Submit + Query**

- The CLI supports an `--auto-transcribe` flag to automatically submit and wait for missing videos to be processed before querying.

---

## **Deploying the Infrastructure**

This project provides a single `setup.sh` script to automate the entire deployment:

- Creates your `.env` file and generates a unique S3 bucket name
- Builds and pushes Docker images for the ECS download worker and the transcription Lambda
- Packages and uploads zip files for the schema initialization, ETL, and query Lambda functions
- Deploys the entire pipeline using AWS CloudFormation
- Configures S3 event notifications for the transcription and ETL Lambda functions
- Invokes the schema initialization Lambda function to create or update the PostgreSQL DB schema
- Stores your API Gateway endpoints in your `.env` for use via the CLI

### To deploy:

1. Make sure you have:

   - An AWS account with the required IAM permissions
   - Docker installed
   - AWS CLI configured (`aws configure`)
- Note: You may need to add a `cookies.txt` file to the `download_worker` directory to bypass YouTube login restrictions. You can accomplish this by opening YouTube in an incognito tab and using the [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) Chrome extension to generate the file in Netscape format. Once you close the incognito tab, you can be sure that the cookies will be unique and won't need refreshing.

2. Clone this repo and run:

   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```

3. When the script completes, your `.env` will contain:

   - Your generated S3 bucket name
   - The submit and query API endpoints
   - The DynamoDB status tracker table name

---

## **CLI Usage**

**Install the CLI:**

```bash
pip install -e .
```

**Submit a video for transcription:**

```bash
transcribe submit --url "https://www.youtube.com/watch?v=abc123"
```

**Query a channel for keywords:**

```bash
transcribe query --q "machine learning" --channel_tag "@MyChannel" --platform_name YouTube
```

**Auto-transcribe if missing and then query:**

```bash
transcribe query --q "NLP" --platform_name YouTube --video_id "abc123" --auto-transcribe
```

---

## **Future Improvements**

- Allow batch YouTube channel and playlist submission
- Add support for other video platforms (currently YouTube only)
- Build a minimal web UI for end users
- Accept natural language prompting
