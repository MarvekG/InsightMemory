# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ARG TORCH_VERSION=2.10.0+cpu

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl sudo \
    && groupadd --system --gid 10001 memory \
    && useradd --system --uid 10001 --gid 10001 --create-home --home-dir /home/memory --shell /bin/bash memory \
    && usermod -aG sudo memory \
    && echo 'memory ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/memory \
    && chmod 440 /etc/sudoers.d/memory \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /home/memory/.insight_memory/logs /home/memory/.insight_memory/data/models /tmp/memory \
    && chown -R memory:memory /home/memory/.insight_memory /tmp/memory && \
    pip install --upgrade pip && \
    pip install uv -i https://mirrors.aliyun.com/pypi/simple/ 

COPY --chown=memory:memory requirements.txt ./

RUN --mount=type=cache,target=/root/.cache/uv \
    UV_LINK_MODE=copy uv pip install --system -i https://mirrors.aliyun.com/pypi/simple/ \
    --find-links https://mirrors.aliyun.com/pytorch-wheels/cpu/ \
    "torch==${TORCH_VERSION}" && \
    uv pip install --system -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

COPY --chown=memory:memory . .

EXPOSE 8010

USER memory

CMD ["python", "run.py"]
