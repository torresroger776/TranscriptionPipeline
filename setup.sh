#!/usr/bin/env bash

set =e

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

STACK_NAME="transcription-pipeline-stack"
TEMPLATE_FILE="cloudformation/project_cf_template.json"
LAMBDA_DIR="lambda"
LAMBDA_NAME="ProcessTranscriptionJob"

# create S3 bucket if it doesn't exist
if ! aws s3api head-bucket --bucket "$BUCKET_NAME"; then
    aws s3api create-bucket --bucket "$BUCKET_NAME"
fi

# zip lambda code
cd "$LAMBDA_DIR/$LAMBDA_NAME"
rm -f "../$LAMBDA_NAME.zip"
zip -r "../$LAMBDA_NAME.zip" .
cd ../..

# upload lambda code to S3 bucket
aws s3 cp $LAMBDA_DIR/$LAMBDA_NAME.zip s3://$BUCKET_NAME/$LAMBDA_DIR/

# deploy stack
aws cloudformation deploy \
  --stack-name $STACK_NAME \
  --template-file $TEMPLATE_FILE \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      LambdaS3Bucket=$BUCKET_NAME \
      LambdaS3Key=$LAMBDA_DIR/$LAMBDA_NAME.zip

# update lambda code
aws lambda update-function-code \
  --function-name $LAMBDA_NAME \
  --s3-bucket $BUCKET_NAME \
  --s3-key $LAMBDA_DIR/$LAMBDA_NAME.zip > /dev/null

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