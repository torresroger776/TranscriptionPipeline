#!/usr/bin/env bash

set -e

create_ecr_repo() {
    local REPO_NAME=$1

    if ! aws ecr describe-repositories --repository-names "$REPO_NAME" > /dev/null 2>&1; then
        echo "Creating ECR repository: $REPO_NAME"
        aws ecr create-repository --repository-name "$REPO_NAME" > /dev/null 2>&1
    else
        echo "ECR repository $REPO_NAME already exists"
    fi
}

build_and_push_image() {
    local LOCAL_NAME=$1
    local REPO_URI=$2
    local BUILD_DIR=$3
    local BUILD_ARGS=$4

    # build Docker image
    echo "Building Docker image: $LOCAL_NAME"
    docker buildx build $BUILD_ARGS -t "$LOCAL_NAME" "$BUILD_DIR"
    docker tag "$LOCAL_NAME:latest" "$REPO_URI:latest"

    # delete old images from ECR repository
    echo "Deleting old images from $LOCAL_NAME ECR repository..."
    OLD_IMAGES=$(aws ecr list-images --repository-name "$LOCAL_NAME" --query 'imageIds[*]' --output json)
    if [ "$OLD_IMAGES" != "[]" ]; then
        aws ecr batch-delete-image --repository-name "$LOCAL_NAME" --image-ids "$OLD_IMAGES" > /dev/null 2>&1
    fi

    # push image to ECR
    echo "Pushing image to ECR: $REPO_URI"
    docker push "$REPO_URI:latest"
}

package_and_upload_lambda() {
    local DIR_NAME=$1

    if [ ! -f "$DIR_NAME.zip" ]; then
        echo "Packaging Lambda: $DIR_NAME"
        cd "$DIR_NAME"
        zip -r "../$DIR_NAME.zip" .
        cd ..
        echo "Uploading $DIR_NAME.zip to S3..."
        aws s3 cp "$DIR_NAME.zip" "s3://$BUCKET_NAME/lambda/$DIR_NAME.zip" > /dev/null 2>&1
    else
        echo "$DIR_NAME.zip already exists, skipping packaging"
    fi
}

# create .env or activate existing one
if [ ! -f .env ]; then
  touch .env
fi
source .env

# generate bucket name if not set
if [ -z "$BUCKET_NAME" ]; then
  BUCKET_NAME=transcription-bucket-$(uuidgen | tr '[:upper:]' '[:lower:]')
  echo "BUCKET_NAME=$BUCKET_NAME" >> .env
fi

# create S3 bucket if it doesn't exist
if ! aws s3api head-bucket --bucket "$BUCKET_NAME" > /dev/null 2>&1; then
  echo "Creating S3 bucket: $BUCKET_NAME"
  aws s3api create-bucket --bucket "$BUCKET_NAME" > /dev/null 2>&1
else
  echo "S3 bucket $BUCKET_NAME already exists"
fi

# authenticate Docker with ECR
AWS_REGION=$(aws configure get region)
ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text)
ECR_URI="$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

aws ecr get-login-password | docker login --username AWS --password-stdin "$ECR_URI"

# push download worker Docker image to ECR
DOWNLOAD_REPO_NAME=download-worker
DOWNLOAD_REPO_URI=$ECR_URI/$DOWNLOAD_REPO_NAME
create_ecr_repo "$DOWNLOAD_REPO_NAME"
build_and_push_image "$DOWNLOAD_REPO_NAME" "$DOWNLOAD_REPO_URI" download_worker "--provenance=false"

# push transcription Lambda Docker image to ECR
TRANSCRIPTION_REPO_NAME=transcription-lambda
TRANSCRIPTION_REPO_URI=$ECR_URI/$TRANSCRIPTION_REPO_NAME

WHISPER_MODEL_SIZE=${WHISPER_MODEL_SIZE:-tiny.en}
WHISPER_MODEL_FILENAME=ggml-$WHISPER_MODEL_SIZE.bin
WHISPER_MODEL_DIR=models

mkdir -p transcription_lambda/$WHISPER_MODEL_DIR
if [ ! -f transcription_lambda/$WHISPER_MODEL_DIR/$WHISPER_MODEL_FILENAME ]; then
  echo "Downloading Whisper model: $WHISPER_MODEL_FILENAME"
  curl -L -o transcription_lambda/$WHISPER_MODEL_DIR/$WHISPER_MODEL_FILENAME \
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/$WHISPER_MODEL_FILENAME"
else
  echo "Whisper model $WHISPER_MODEL_FILENAME already exists"
fi

create_ecr_repo "$TRANSCRIPTION_REPO_NAME"
build_and_push_image "$TRANSCRIPTION_REPO_NAME" "$TRANSCRIPTION_REPO_URI" transcription_lambda "--platform linux/amd64 --provenance=false"

# prune Docker images
docker image prune -f

# download and prepare psycopg2 library for Lambdas
if [ ! -d schema_init_lambda/psycopg2 ] || [ ! -d etl_lambda/psycopg2 ] || [ ! -d query_lambda/psycopg2 ]; then
  echo "Downloading psycopg2 library..."
  TMP_PG_DIR=psycopg2_tmp
  mkdir -p $TMP_PG_DIR
  curl -sL -o $TMP_PG_DIR/psycopg2.zip "https://github.com/jkehler/awslambda-psycopg2/archive/refs/heads/master.zip"
  unzip -q $TMP_PG_DIR/psycopg2.zip -d $TMP_PG_DIR
  for DIR in schema_init_lambda etl_lambda query_lambda; do
    rm -rf $DIR/psycopg2*
    cp -r $TMP_PG_DIR/awslambda-psycopg2-master/psycopg2-3.11/* $DIR/
  done
  rm -rf $TMP_PG_DIR
else
  echo "psycopg2 already exist, skipping download"
fi

# package and upload Lambda functions
package_and_upload_lambda schema_init_lambda
package_and_upload_lambda etl_lambda
package_and_upload_lambda query_lambda

# deploy CloudFormation stack
DEFAULT_VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text)
DEFAULT_SUBNET_ID=$(aws ec2 describe-subnets --filters "Name=default-for-az,Values=true" --query "Subnets[0].SubnetId" --output text)
DEFAULT_ROUTE_TABLE_ID=$(aws ec2 describe-route-tables --filters "Name=vpc-id,Values=$DEFAULT_VPC_ID" "Name=association.main,Values=true" --query "RouteTables[0].RouteTableId" --output text)

STACK_NAME=transcription-pipeline-stack
TEMPLATE_FILE=cloudformation/project_cf_template.json

aws cloudformation deploy \
  --stack-name $STACK_NAME \
  --template-file $TEMPLATE_FILE \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    S3Bucket=$BUCKET_NAME \
    VpcId=$DEFAULT_VPC_ID \
    SubnetId=$DEFAULT_SUBNET_ID \
    RouteTableId=$DEFAULT_ROUTE_TABLE_ID \
    DownloadWorkerImage=$DOWNLOAD_REPO_URI:latest \
    TranscriptionLambdaImage=$TRANSCRIPTION_REPO_URI:latest \
    SegmentDuration=900 \
    WhisperModelPath=$WHISPER_MODEL_DIR/$WHISPER_MODEL_FILENAME \
    RDSDBName=${RDS_DB_NAME:-transcriptiondb} \
    RDSDBInstanceIdentifier=${RDS_DB_INSTANCE_IDENTIFIER:-transcription-db} \
    RDSMasterUsername=${RDS_MASTER_USERNAME:-dbadmin} \
    RDSMasterPassword=${RDS_MASTER_PASSWORD:-dbadmin123}

# set up S3 bucket notifications for Lambda triggers
TRANSCRIPTION_LAMBDA_ARN=$(aws cloudformation describe-stacks --stack-name $STACK_NAME \
  --query "Stacks[0].Outputs[?OutputKey=='TranscriptionLambdaArn'].OutputValue" --output text)

ETL_LAMBDA_ARN=$(aws cloudformation describe-stacks --stack-name $STACK_NAME \
  --query "Stacks[0].Outputs[?OutputKey=='ETLLambdaArn'].OutputValue" --output text)

aws s3api put-bucket-notification-configuration --bucket $BUCKET_NAME --notification-configuration '{
  "LambdaFunctionConfigurations": [
    {
      "LambdaFunctionArn": "'"$TRANSCRIPTION_LAMBDA_ARN"'", "Events": ["s3:ObjectCreated:*"],
      "Filter": {"Key": {"FilterRules": [{"Name": "prefix", "Value": "audio/"},{"Name": "suffix", "Value": ".wav"}]}}
    },
    {
      "LambdaFunctionArn": "'"$ETL_LAMBDA_ARN"'", "Events": ["s3:ObjectCreated:*"],
      "Filter": {"Key": {"FilterRules": [{"Name": "prefix", "Value": "transcripts/"},{"Name": "suffix", "Value": ".json"}]}}
    }
  ]
}'

# invoke schema init Lambda to set up the database schema
echo "Invoking schema init Lambda..."
aws lambda invoke --function-name schema-init-lambda --payload '{}' response.json
echo "Schema init Lambda response:"
cat response.json && rm response.json

# retrieve CloudFormation stack outputs and update .env file
SUBMIT_API_INVOKE_URL=$(aws cloudformation describe-stacks --stack-name $STACK_NAME \
  --query "Stacks[0].Outputs[?OutputKey=='SubmitAPIInvokeURL'].OutputValue" --output text)
QUERY_API_INVOKE_URL=$(aws cloudformation describe-stacks --stack-name $STACK_NAME \
  --query "Stacks[0].Outputs[?OutputKey=='QueryAPIInvokeURL'].OutputValue" --output text)
JOBS_TABLE_NAME=$(aws cloudformation describe-stacks --stack-name $STACK_NAME \
  --query "Stacks[0].Outputs[?OutputKey=='VideoTranscriptionJobsTableName'].OutputValue" --output text)

grep -q '^SUBMIT_API_INVOKE_URL=' .env && sed -i "s|^SUBMIT_API_INVOKE_URL=.*|SUBMIT_API_INVOKE_URL=$SUBMIT_API_INVOKE_URL|" .env || echo "SUBMIT_API_INVOKE_URL=$SUBMIT_API_INVOKE_URL" >> .env
grep -q '^QUERY_API_INVOKE_URL=' .env && sed -i "s|^QUERY_API_INVOKE_URL=.*|QUERY_API_INVOKE_URL=$QUERY_API_INVOKE_URL|" .env || echo "QUERY_API_INVOKE_URL=$QUERY_API_INVOKE_URL" >> .env
grep -q '^JOBS_TABLE_NAME=' .env && sed -i "s|^JOBS_TABLE_NAME=.*|JOBS_TABLE_NAME=$JOBS_TABLE_NAME|" .env || echo "JOBS_TABLE_NAME=$JOBS_TABLE_NAME" >> .env
