FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /usr/local/bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/symphony
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    SYMPHONY_BENCH_CONFIG=/opt/symphony/bench/config.toml

COPY pyproject.toml uv.lock ./
COPY core_ai ./core_ai
COPY core_harness ./core_harness
COPY coding_agent ./coding_agent
COPY core_server ./core_server
COPY bench/config.toml ./bench/config.toml

RUN uv sync --frozen --no-dev --package symphony-code \
    && rm -rf /root/.cache/uv

ENV PATH="/opt/symphony/.venv/bin:$PATH"
WORKDIR /testbed
ENTRYPOINT ["symphony", "bench", "--workspace", "/testbed"]
