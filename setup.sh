#!/usr/bin/env bash

set -e

# check if .env exists
if [ ! -f .env ]; then
  touch .env
fi

# activate .env variables
source .env

# generate bucket name if not set
if [ -z $BUCKET_NAME ]; then
  BUCKET_NAME=transcription-bucket-$(uuidgen | tr '[:upper:]' '[:lower:]')
  echo "BUCKET_NAME=$BUCKET_NAME" >> .env
fi

# create S3 bucket if it doesn't exist
if ! aws s3api head-bucket --bucket $BUCKET_NAME > /dev/null 2>&1; then
    echo "Creating S3 bucket $BUCKET_NAME..."
    aws s3api create-bucket --bucket $BUCKET_NAME > /dev/null 2>&1
else
    echo "S3 bucket $BUCKET_NAME already exists"
fi

# get AWS region from configuration
AWS_REGION=$(aws configure get region)

# ECR repository details
DOWNLOAD_REPOSITORY_NAME=download-worker
ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text)
ECR_URI=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
DOWNLOAD_REPOSITORY_URI=$ECR_URI/$DOWNLOAD_REPOSITORY_NAME

# authenticate to ECR
aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_URI

# create download worker ECR repository if it doesn't exist
if ! aws ecr describe-repositories --repository-names $DOWNLOAD_REPOSITORY_NAME > /dev/null 2>&1; then
    echo "Creating ECR repository $DOWNLOAD_REPOSITORY_NAME..."
    aws ecr create-repository --repository-name $DOWNLOAD_REPOSITORY_NAME > /dev/null 2>&1
else
    echo "ECR repository $DOWNLOAD_REPOSITORY_NAME already exists"
fi

# check if download worker image exists locally before building and pushing
if [ -z $(docker images -q $DOWNLOAD_REPOSITORY_NAME:latest) ]; then
  echo "Building download worker image..."
  docker build --provenance=false -t $DOWNLOAD_REPOSITORY_NAME download_worker
  docker tag $DOWNLOAD_REPOSITORY_NAME:latest $DOWNLOAD_REPOSITORY_URI:latest

  echo "Deleting old images from download worker repository..."
  # empty download worker ECR repository
  OLD_DOWNLOAD_IMAGES=$(aws ecr list-images \
    --repository-name $DOWNLOAD_REPOSITORY_NAME \
    --query 'imageIds[*]' \
    --output json)

  if [ "$OLD_DOWNLOAD_IMAGES" != "[]" ]; then
    aws ecr batch-delete-image \
      --repository-name $DOWNLOAD_REPOSITORY_NAME \
      --image-ids "$OLD_DOWNLOAD_IMAGES" > /dev/null 2>&1
  fi

  echo "Pushing download worker image to ECR..."
  docker push $DOWNLOAD_REPOSITORY_URI:latest
else
  echo "Download worker image already exists"
fi

# Whisper environment variables
# you can set WHISPER_MODEL_SIZE to a different size in .env
WHISPER_MODEL_SIZE=${WHISPER_MODEL_SIZE:-tiny.en}
WHISPER_MODEL_FILENAME=ggml-$WHISPER_MODEL_SIZE.bin
WHISPER_MODEL_URL=https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$WHISPER_MODEL_FILENAME
WHISPER_MODEL_DIR=models

cd transcription_lambda
mkdir -p $WHISPER_MODEL_DIR

# download Whisper model if it doesn't exist
if [ ! -f $WHISPER_MODEL_DIR/$WHISPER_MODEL_FILENAME ]; then
  echo "Downloading Whisper model $WHISPER_MODEL_FILENAME..."
  curl -L -o $WHISPER_MODEL_DIR/$WHISPER_MODEL_FILENAME $WHISPER_MODEL_URL
else
  echo "Whisper model $WHISPER_MODEL_FILENAME already exists"
fi

cd ..

# ECR repository details
TRANSCRIPTION_REPOSITORY_NAME=transcription-lambda
TRANSCRIPTION_REPOSITORY_URI=$ECR_URI/$TRANSCRIPTION_REPOSITORY_NAME

# create transcription lambda ECR repository if it doesn't exist
if ! aws ecr describe-repositories --repository-names $TRANSCRIPTION_REPOSITORY_NAME > /dev/null 2>&1; then
    echo "Creating ECR repository $TRANSCRIPTION_REPOSITORY_NAME..."
    aws ecr create-repository --repository-name $TRANSCRIPTION_REPOSITORY_NAME > /dev/null 2>&1
else
    echo "ECR repository $TRANSCRIPTION_REPOSITORY_NAME already exists"
fi

# check if transcription lambda image exists locally before building and pushing
if [ -z $(docker images -q $TRANSCRIPTION_REPOSITORY_NAME:latest) ]; then
  echo "Building transcription lambda image..."
  docker buildx build --platform linux/amd64 --provenance=false -t $TRANSCRIPTION_REPOSITORY_NAME transcription_lambda
  docker tag $TRANSCRIPTION_REPOSITORY_NAME:latest $TRANSCRIPTION_REPOSITORY_URI:latest

  echo "Deleting old images from transcription lambda repository..."
  # empty transcription lambda ECR repository
  OLD_TRANSCRIPTION_IMAGES=$(aws ecr list-images \
    --repository-name $TRANSCRIPTION_REPOSITORY_NAME \
    --query 'imageIds[*]' \
    --output json)

  if [ "$OLD_TRANSCRIPTION_IMAGES" != "[]" ]; then
    aws ecr batch-delete-image \
      --repository-name $TRANSCRIPTION_REPOSITORY_NAME \
      --image-ids "$OLD_TRANSCRIPTION_IMAGES" > /dev/null 2>&1
  fi

  echo "Pushing transcription lambda image to ECR..."
  docker push $TRANSCRIPTION_REPOSITORY_URI:latest
else
  echo "Transcription lambda image already exists"
fi

# find default subnet id
DEFAULT_SUBNET_ID=$(aws ec2 describe-subnets \
  --filters "Name=default-for-az,Values=true" \
  --query "Subnets[0].SubnetId" \
  --output text)

# CloudFormation parameters
STACK_NAME=transcription-pipeline-stack
TEMPLATE_FILE=cloudformation/project_cf_template.json

# deploy infrastructure
aws cloudformation deploy \
  --stack-name $STACK_NAME \
  --template-file $TEMPLATE_FILE \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      S3Bucket=$BUCKET_NAME \
      SubnetId=$DEFAULT_SUBNET_ID \
      DownloadWorkerImage=$DOWNLOAD_REPOSITORY_URI:latest \
      TranscriptionLambdaImage=$TRANSCRIPTION_REPOSITORY_URI:latest \
      WhisperModelPath=$WHISPER_MODEL_DIR/$WHISPER_MODEL_FILENAME

# retrieve transcription Lambda ARN
LAMBDA_ARN=$(aws cloudformation describe-stacks --stack-name $STACK_NAME \
  --query "Stacks[0].Outputs[?OutputKey=='TranscriptionLambdaArn'].OutputValue" \
  --output text)

# configure S3 event notification for .wav files in audio/ to invoke the Lambda function
aws s3api put-bucket-notification-configuration \
  --bucket $BUCKET_NAME \
  --notification-configuration '{
    "LambdaFunctionConfigurations": [
      {
        "LambdaFunctionArn": "'"$LAMBDA_ARN"'",
        "Events": ["s3:ObjectCreated:*"],
        "Filter": {
          "Key": {
            "FilterRules": [
              {
                "Name": "prefix",
                "Value": "audio/"
              },
              {
                "Name": "suffix",
                "Value": ".wav"
              }
            ]
          }
        }
      }
    ]
  }'

# store transcription API endpoint in .env
API_INVOKE_URL=$(aws cloudformation describe-stacks --stack-name $STACK_NAME \
  --query "Stacks[0].Outputs[?OutputKey=='APIInvokeURL'].OutputValue" \
  --output text)

if grep -q '^API_INVOKE_URL=' .env; then
  sed -i "s|^API_INVOKE_URL=.*|API_INVOKE_URL=$API_INVOKE_URL|" .env
else
  echo "API_INVOKE_URL=$API_INVOKE_URL" >> .env
fi