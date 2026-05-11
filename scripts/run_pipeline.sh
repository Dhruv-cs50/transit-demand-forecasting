#!/usr/bin/env bash
# Full ML pipeline — uses .venv311 (Python 3.11 + AutoGluon)
# Run from repo root: bash scripts/run_pipeline.sh
set -e
PYTHON=".venv311/bin/python"

echo "=== 1. Rebuild feature store + splits ==="
$PYTHON machine_learning_files/merge_pipeline.py

echo "=== 1.5. Feature engineering ==="
$PYTHON Processing/feature_engineering.py

echo "=== 1.6. Validate data quality ==="
$PYTHON evaluation/validators.py --input data/processed/feature_store_enriched.parquet --mode lenient --freq MS

echo "=== 2. Chronos-2 zero-shot ==="
$PYTHON machine_learning_files/zero_shot.py

echo "=== 3. SARIMA baseline ==="
$PYTHON models/baselines/arima.py

echo "=== 4. Prophet baseline ==="
$PYTHON models/baselines/prophet_baseline.py

echo "=== 5. AutoGluon fine-tune (DeepAR + AutoETS ensemble) ==="
$PYTHON models/chronos2/finetune.py --time-limit 1800

echo "=== 6. Benchmarks ==="
$PYTHON models/baselines/benchmarks.py

echo "=== 7. Export website data ==="
$PYTHON scripts/export_website_data.py --feature-store data/processed/feature_store_enriched.parquet

echo ""
echo "Done. Run: firebase deploy --only hosting"
