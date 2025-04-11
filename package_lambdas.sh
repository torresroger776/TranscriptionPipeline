#!/bin/bash

CURRENT_DIR=$(pwd)
LAMBDA_DIR=$1
LAYER_NAME=$2
LAYER_DIR=$LAMBDA_DIR/$LAYER_NAME
DOWNLOAD_LAMBDA_NAME=$3
DOWNLOAD_LAMBDA_DIR=$LAMBDA_DIR/$DOWNLOAD_LAMBDA_NAME
TRANSCRIBE_LAMBDA_NAME=$4
TRANSCRIBE_LAMBDA_DIR=$LAMBDA_DIR/$TRANSCRIBE_LAMBDA_NAME

# download layer if doesn't exist
if [ ! -d "$LAYER_DIR" ]; then
  mkdir -p "$LAYER_DIR/python" "$LAYER_DIR/bin"

  pip install yt-dlp -t "$LAYER_DIR/python"
  
  wget https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
  tar -xvf ffmpeg-release-amd64-static.tar.xz
  mv ffmpeg-*/ffmpeg "$LAYER_DIR/bin/"
  rm -rf ffmpeg-*
fi

# zip layer if zip file doesn't exist
if [ ! -f "$LAYER_DIR.zip" ]; then
  cd "$LAYER_DIR"
  zip -r "../$LAYER_NAME.zip" .
  cd "$CURRENT_DIR"
fi

# zip download lambda
cd "$DOWNLOAD_LAMBDA_DIR"
rm -f "../$DOWNLOAD_LAMBDA_NAME.zip"
zip -r "../$DOWNLOAD_LAMBDA_NAME.zip" .
cd "$CURRENT_DIR"

# # zip transcribe lambda
# cd "$TRANSCRIBE_LAMBDA_DIR"
# rm -f "../$TRANSCRIBE_LAMBDA_NAME.zip"
# zip -r "../$TRANSCRIBE_LAMBDA_NAME.zip" .
# cd "$CURRENT_DIR"