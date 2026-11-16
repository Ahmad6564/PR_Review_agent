FROM python:3.12-slim

# ripgrep powers the agent's search_repo tool; it degrades to a Python walk without it.
RUN apt-get update && apt-get install -y --no-install-recommends ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml ./
COPY prlens/ ./prlens/
COPY README.md ./
RUN uv pip install --system --no-cache .

ENTRYPOINT ["python", "-m", "prlens.action"]
