# The whole CLI in one image, for the processing instance (see README, "Processing on AWS").
# Base images are pinned by digest: bump the tag and digest together (docker buildx imagetools inspect <image>).
FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70

RUN apt-get update \
 && apt-get install -y --no-install-recommends libimage-exiftool-perl libgl1 libegl1 libgles2 libglib2.0-0 curl unzip ca-certificates \
 && curl -sSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscli.zip \
 && unzip -q /tmp/awscli.zip -d /tmp && /tmp/aws/install && rm -rf /tmp/aws /tmp/awscli.zip \
 && apt-get purge -y curl unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.10@sha256:72ab0aeb448090480ccabb99fb5f52b0dc3c71923bffb5e2e26517a1c27b7fec /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src src
COPY assets assets
COPY models models
RUN uv sync --frozen --no-dev

# Same uid as the host user, so out/ stays editable outside the container; ~/.aws is mounted read-only.
RUN useradd --uid 1000 --create-home app && mkdir -p out events && chown app out events
USER app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 EVENT_PHOTOS_REVIEW_HOST=0.0.0.0 AWS_PAGER=""
ENTRYPOINT ["event-photos"]
