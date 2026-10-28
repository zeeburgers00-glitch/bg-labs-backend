ARG UBUNTU_VERSION=22.04
ARG CUDA_VERSION=12.3.1
ARG BASE_CUDA_DEV_CONTAINER=nvidia/cuda:${CUDA_VERSION}-devel-ubuntu${UBUNTU_VERSION}
ARG BASE_CUDA_RUN_CONTAINER=nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu${UBUNTU_VERSION}

# Ref: https://github.com/ggml-org/whisper.cpp
FROM ${BASE_CUDA_DEV_CONTAINER} AS install-whisper
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install --fix-missing --no-install-recommends -y bash git make vim wget g++ ffmpeg curl

WORKDIR /app/data/libs/whisper
RUN git clone https://github.com/ggerganov/whisper.cpp.git -b v1.7.1 --depth 1 .

RUN make clean
RUN GGML_CUDA=1 make -j

RUN sh ./models/download-ggml-model.sh medium.en

FROM ${BASE_CUDA_RUN_CONTAINER} AS base

# install node
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    gnupg \
    lsb-release \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get update && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*
RUN node -v && npm -v

# install dependencies
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app
RUN apt update
RUN apt install -y \
      # whisper dependencies
      git \
      wget \
      cmake \
      ffmpeg \
      curl \
      build-essential \
      make \
      # remotion dependencies
      libnss3 \
      libdbus-1-3 \
      libatk1.0-0 \
      libgbm-dev \
      libasound2 \
      libxrandr2 \
      libxkbcommon-dev \
      libxfixes3 \
      libxcomposite1 \
      libxdamage1 \
      libatk-bridge2.0-0 \
      libpango-1.0-0 \
      libcairo2 \
      libcups2 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
# setup pnpm
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable

FROM base AS prod-deps
COPY package.json pnpm-lock.yaml* /app/
RUN --mount=type=cache,id=pnpm,target=/pnpm/store pnpm install --prod --frozen-lockfile
RUN pnpm install --prefer-offline --no-cache --prod

FROM prod-deps AS build
COPY tsconfig.json /app
COPY tsconfig.build.json /app
COPY vite.config.ts /app
COPY src /app/src
RUN --mount=type=cache,id=pnpm,target=/pnpm/store pnpm install --frozen-lockfile
RUN pnpm build

FROM base
COPY static /app/static
COPY --from=install-whisper /app/data/libs/whisper /app/data/libs/whisper
COPY --from=prod-deps /app/node_modules /app/node_modules
COPY --from=build /app/dist /app/dist
COPY package.json /app/

# app configuration via environment variables
ENV DATA_DIR_PATH=/app/data
ENV DOCKER=true
# number of chrome tabs to use for rendering
ENV CONCURRENCY=1
# video cache - 2000MB
ENV VIDEO_CACHE_SIZE_IN_BYTES=2097152000

# install kokoro, headless chrome and ensure music files are present
RUN node dist/scripts/install.js

CMD ["pnpm", "start"]
