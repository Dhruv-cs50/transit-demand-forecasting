# ── Full ML pipeline image ───────────────────────────────────────────────────
# Packages the complete transit demand forecasting pipeline:
#   data ingestion → feature engineering → model training → evaluation
#
# Build (Apple Silicon — use Cloud Build or add --platform linux/amd64):
#   docker build --platform linux/amd64 -t transit-pipeline .
#
# Run interactively:
#   docker run -it transit-pipeline bash
#
# Run the full pipeline:
#   docker run transit-pipeline bash scripts/run_pipeline.sh

FROM python:3.11-slim

WORKDIR /app

# System deps needed by some ML packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    git \
    curl \
  && rm -rf /var/lib/apt/lists/*

# Python deps — full ML stack
COPY machine_learning_files/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy entire project (excluding what .dockerignore filters out)
COPY configs/           ./configs/
COPY machine_learning_files/ ./machine_learning_files/
COPY models/            ./models/
COPY Processing/        ./Processing/
COPY evaluation/        ./evaluation/
COPY scripts/           ./scripts/
COPY transit_eda/       ./transit_eda/

# Data directory placeholder (mount real data at runtime)
RUN mkdir -p data/raw data/processed models/chronos2/outputs

# Default: show usage
CMD ["bash", "-c", "echo 'Transit Demand Forecasting Pipeline' && echo 'Run: bash scripts/run_pipeline.sh'"]
