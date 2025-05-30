### Stage 1: Install dependencies
FROM amazonlinux:2023 AS builder

RUN yum update -y && \
    yum install -y \
        python3 \
        python3-pip \
        git \
        gcc \
        gcc-c++ \
        cmake \
        make && \
    yum clean all

RUN git clone https://github.com/ggerganov/whisper.cpp.git && \
    cd whisper.cpp && make

### Stage 2: Use ECR Lambda base image
FROM public.ecr.aws/lambda/python:3.12

# copy Lambda folder files
WORKDIR ${LAMBDA_TASK_ROOT}
COPY . .

# copy the built whisper.cpp files from the builder stage
COPY --from=builder /whisper.cpp/build ./build

# copy necessary library
COPY --from=builder /usr/lib64/libgomp.so.1 /usr/lib64/

# expose necessary libraries to whisper-cli
ENV LD_LIBRARY_PATH=${LAMBDA_TASK_ROOT}/build/src:$LD_LIBRARY_PATH
ENV LD_LIBRARY_PATH=${LAMBDA_TASK_ROOT}/build/ggml/src:$LD_LIBRARY_PATH

RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir boto3==1.38.9

CMD ["app.lambda_handler"]
