#!/usr/bin/env bash
# End-to-end pipeline. Override defaults with environment variables, e.g.
#   DATASET=lfw MODEL=Facenet512 N_PAIRS=300 FHE_PAIRS=50 bash scripts/run_all.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

DATASET="${DATASET:-synthetic}"
MODEL="${MODEL:-synthetic}"
N_PAIRS="${N_PAIRS:-400}"
DIM="${DIM:-512}"          # only used by the synthetic dataset
FHE_PAIRS="${FHE_PAIRS:-50}"
DIMS="${DIMS:-64 32}"
BACKENDS="${BACKENDS:-}"

# Pick the strongest available backend automatically when none is forced.
if [[ -z "${BACKENDS}" ]]; then
  if [[ -x "cpp/build/ckks_dot" ]]; then BACKENDS="seal_cpp"
  elif python -c "import tenseal" 2>/dev/null; then BACKENDS="tenseal"
  else BACKENDS="numpy"; echo "warning: no FHE backend found, using the plaintext reference" >&2
  fi
fi

echo "== 0. environment =="
python scripts/00_check_env.py || true

echo "== 1. embeddings (${DATASET}/${MODEL}) =="
python scripts/01_extract_embeddings.py --dataset "${DATASET}" --model "${MODEL}" \
  --n-pairs "${N_PAIRS}" --dim "${DIM}"

echo "== 2. plaintext baseline =="
python scripts/02_baseline_plaintext.py

echo "== 3. PCA reduction =="
python scripts/03_reduce_pca.py --dims ${DIMS} || echo "PCA skipped (scikit-learn missing?)"

echo "== 4. encrypted benchmark (backends: ${BACKENDS}) =="
# shellcheck disable=SC2086
python scripts/04_fhe_benchmark.py --backends ${BACKENDS} \
  --dims full ${DIMS} --n-pairs "${FHE_PAIRS}"

echo "== 5. report =="
python scripts/05_make_report.py
echo "done: reports/results.md"
