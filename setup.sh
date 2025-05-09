#!/usr/bin/env bash

set -e

# check if .env exists
if [ ! -f .env ]; then
  touch .env
fi

# activate .env variables
source .env

# create bucket name if not set
if [ -z $BUCKET_NAME ]; then
  BUCKET_NAME=transcription-bucket-$(uuidgen | tr '[:upper:]' '[:lower:]')
  echo "BUCKET_NAME=$BUCKET_NAME" >> .env
fi

# get AWS region from configuration
AWS_REGION=$(aws configure get region)

# CloudFormation parameters
STACK_NAME=transcription-pipeline-stack
TEMPLATE_FILE=cloudformation/project_cf_template.json

# ECR repository details
DOWNLOAD_REPOSITORY_NAME=download-worker
TRANSCRIPTION_REPOSITORY_NAME=transcription-worker
IMAGE_TAG=latest
ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text)
ECR_URI=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
DOWNLOAD_REPOSITORY_URI=$ECR_URI/$DOWNLOAD_REPOSITORY_NAME
TRANSCRIPTION_REPOSITORY_URI=$ECR_URI/$TRANSCRIPTION_REPOSITORY_NAME

# create S3 bucket if it doesn't exist
if ! aws s3api head-bucket --bucket $BUCKET_NAME; then
    aws s3api create-bucket --bucket $BUCKET_NAME
fi

# authenticate to ECR
aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_URI

# create download worker ECR repository if it doesn't exist
if ! aws ecr describe-repositories --repository-names $DOWNLOAD_REPOSITORY_NAME > /dev/null 2>&1; then
    aws ecr create-repository --repository-name $DOWNLOAD_REPOSITORY_NAME > /dev/null 2>&1
else
    echo "ECR repository $DOWNLOAD_REPOSITORY_NAME already exists"
fi

# build and push download worker image
docker build -t $DOWNLOAD_REPOSITORY_NAME download_worker
docker tag $DOWNLOAD_REPOSITORY_NAME:$IMAGE_TAG $DOWNLOAD_REPOSITORY_URI:$IMAGE_TAG
docker push $DOWNLOAD_REPOSITORY_URI:$IMAGE_TAG

# find subnet id
DEFAULT_SUBNET_ID=$(aws ec2 describe-subnets \
  --filters "Name=default-for-az,Values=true" \
  --query "Subnets[0].SubnetId" \
  --output text)

# deploy stack
aws cloudformation deploy \
  --stack-name $STACK_NAME \
  --template-file $TEMPLATE_FILE \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      S3Bucket=$BUCKET_NAME \
      DownloadWorkerImage=$DOWNLOAD_REPOSITORY_URI:$IMAGE_TAG \
      SubnetId=$DEFAULT_SUBNET_ID

# get api invoke URL
API_INVOKE_URL=$(aws cloudformation describe-stacks --stack-name $STACK_NAME \
  --query "Stacks[0].Outputs[?OutputKey=='APIInvokeURL'].OutputValue" \
  --output text)

# update or append API_INVOKE_URL in .env
if grep -q '^API_INVOKE_URL=' .env; then
  sed -i "s|^API_INVOKE_URL=.*|API_INVOKE_URL=$API_INVOKE_URL|" .env
else
  echo "API_INVOKE_URL=$API_INVOKE_URL" >> .env
fi