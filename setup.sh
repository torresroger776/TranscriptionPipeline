#!/usr/bin/env bash

# check if .env exists
if [ ! -f .env ]; then
  touch .env
fi
source .env

# create bucket name if not set
if [ -z "$BUCKET_NAME" ]; then
  BUCKET_NAME="transcription-bucket-$(uuidgen | tr '[:upper:]' '[:lower:]')"
  echo "BUCKET_NAME=$BUCKET_NAME" >> .env
fi

# CloudFormation variables
STACK_NAME="transcription-pipeline-stack"
TEMPLATE_FILE="project_cf_template.json"

# Lambda variables
LAMBDA_DIR="lambda"
LAYER_NAME="YtdlpFfmpegLayer"
DOWNLOAD_LAMBDA_NAME="DownloadAndSplitAudio"
TRANSCRIBE_LAMBDA_NAME="TranscribeAudio"

# create S3 bucket if it doesn't exist
if ! aws s3api head-bucket --bucket "$BUCKET_NAME"; then
    aws s3api create-bucket --bucket "$BUCKET_NAME"
fi

# package lambda layer and lambdas
./package_lambdas.sh $LAMBDA_DIR $LAYER_NAME $DOWNLOAD_LAMBDA_NAME $TRANSCRIBE_LAMBDA_NAME

# upload lambda code and layers to S3 bucket
aws s3 sync $LAMBDA_DIR/ s3://$BUCKET_NAME/$LAMBDA_DIR/ \
  --exclude "*" \
  --include "*.zip"

# CloudFormation parameters
PARAMETERS=(
  "ParameterKey=S3BucketName,ParameterValue=$BUCKET_NAME"
  "ParameterKey=S3LambdaPrefix,ParameterValue=$LAMBDA_DIR"
  "ParameterKey=LayerName,ParameterValue=$LAYER_NAME"
  "ParameterKey=DownloadLambdaName,ParameterValue=$DOWNLOAD_LAMBDA_NAME"
)

# check if stack exists
aws cloudformation describe-stacks --stack-name $STACK_NAME > /dev/null 2>&1

# create or update stack
if [ $? -eq 0 ]; then
  aws cloudformation update-stack \
    --stack-name $STACK_NAME \
    --template-body file://$TEMPLATE_FILE \
    --parameters "${PARAMETERS[@]}" \
    --capabilities CAPABILITY_NAMED_IAM

  aws cloudformation wait stack-update-complete --stack-name $STACK_NAME
else
  aws cloudformation create-stack \
    --stack-name $STACK_NAME \
    --template-body file://$TEMPLATE_FILE \
    --parameters "${PARAMETERS[@]}" \
    --capabilities CAPABILITY_NAMED_IAM
  
  aws cloudformation wait stack-create-complete --stack-name $STACK_NAME
fi

# get lambda function url
aws cloudformation describe-stacks --stack-name $STACK_NAME \
  --query "Stacks[0].Outputs[?OutputKey=='DownloadAndSplitAudioLambdaUrl'].OutputValue" \
  --output text | xargs -I {} echo "DOWNLOAD_LAMBDA_URL={}" >> .env