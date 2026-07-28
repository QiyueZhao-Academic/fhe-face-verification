# Runbook — local execution on macOS (Apple Silicon) with VS Code

Target machine: macOS on ARM, Homebrew already providing `seal 4.3.3`,
`cmake 4.4.0`, `nlohmann-json 3.12.0`, `cpp-gsl 4.2.2`, `libomp`,
`python@3.12`, `openssl@3`.

Everything below runs offline except the optional LFW download and `pip`.

---

## 0. Prerequisites

```bash
brew list --versions seal cmake nlohmann-json cpp-gsl python@3.12
```

If anything is missing:

```bash
brew install seal cmake nlohmann-json cpp-gsl python@3.12
```

Use **Python 3.12**, not 3.14: TensorFlow (needed only for real embeddings) has
no 3.14 build yet, and several scientific wheels lag behind too.

## 1. Clone / open and create the environment

```bash
cd path/to/fhe-face-verification
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .          # makes `import fheface` work from anywhere
```

`make setup` does the same in one command.

In VS Code: **Python: Select Interpreter** → `./.venv/bin/python`.
`.vscode/settings.json` already points there, enables pytest and sets the
Homebrew include paths for the C++ extension.

## 2. Build the native SEAL driver (recommended backend)

```bash
bash scripts/build_cpp.sh
```

Expected tail of the output:

```
-- Found Microsoft SEAL 4.3.3
[100%] Built target ckks_dot
ckks_dot 0.1.0 (SEAL 4.3.3)
```

Troubleshooting:

| Symptom | Fix |
|---|---|
| `Could not find a package configuration file provided by "SEAL"` | `cmake -S cpp -B cpp/build -DCMAKE_PREFIX_PATH=$(brew --prefix)` — the script already passes it; check `brew --prefix` returns `/opt/homebrew` |
| `nlohmann_json` not found | `brew install nlohmann-json` |
| `Microsoft.GSL` not found | `brew install cpp-gsl` (Homebrew SEAL is built against it) |
| CMake ≥ 4 rejects the project | already handled: `cmake_minimum_required(VERSION 3.16)` is above the 3.5 cutoff |
| binary elsewhere | export `CKKS_DOT_BIN=/full/path/to/ckks_dot` |

## 3. Verify what is usable

```bash
python scripts/00_check_env.py
```

This prints one line per optional package and per FHE backend. Nothing fails
hard — read the table and proceed.

```bash
python -m pytest        # ~5 s, skips backends that are unavailable
```

## 4. First full run (synthetic, no downloads, ~1 minute)

```bash
bash scripts/run_all.sh
open reports/results.md
```

This validates the whole chain — metrics, PCA, encryption, report — before you
spend time on TensorFlow. The synthetic dataset produces embeddings with the
same geometry as real ones, so accuracy numbers are plausible but **must not be
reported as face-recognition results**.

## 5. Real run on LFW

Install the deep-learning stack once (~2 GB):

```bash
python -m pip install -r requirements-dl.txt
```

Then:

```bash
DATASET=lfw MODEL=Facenet512 N_PAIRS=300 FHE_PAIRS=50 DIMS="128 64 32" \
  bash scripts/run_all.sh
```

* First call downloads LFW (~200 MB) into `~/scikit_learn_data` and caches it.
* First DeepFace call downloads the model weights into `~/.deepface/weights`.
* Both are cached; later runs are offline.
* Expect roughly 10–20 minutes for embedding extraction of 300 + 300 pairs on
  an M-series laptop; the encrypted part is a few minutes.

Useful variants:

```bash
MODEL=ArcFace bash scripts/run_all.sh                 # different backbone
BACKENDS="seal_cpp tenseal" bash scripts/run_all.sh   # compare two libraries
```

## 6. Running the stages individually

```bash
python scripts/01_extract_embeddings.py --dataset lfw --model Facenet512 --n-pairs 300
python scripts/02_baseline_plaintext.py
python scripts/03_reduce_pca.py --dims 128 64 32
python scripts/04_fhe_benchmark.py --backends seal_cpp --dims full 64 32 --n-pairs 50
python scripts/05_make_report.py
```

Each script writes JSON under `artifacts/`; step 5 only aggregates. Re-running a
single stage never invalidates the others.

To change cryptographic parameters:

```bash
python scripts/04_fhe_benchmark.py --backends seal_cpp --poly 16384 --scale-bits 40
```

`--poly 8192` gives a 160-bit modulus chain (limit 218 at 128-bit security);
`--poly 16384` doubles the slots and roughly doubles latency and ciphertext size
— a good extra row for the report.

## 7. Outputs

| Path | Content |
|---|---|
| `artifacts/embeddings/*.npz` | cached L2-normalised embeddings + provenance metadata |
| `artifacts/results/baseline.json` | plaintext accuracy / AUC / EER |
| `artifacts/results/pca.json` | accuracy per reduced dimension |
| `artifacts/results/fhe_<backend>_d<dim>.json` | encrypted metrics, timings, sizes |
| `reports/figures/*.png` | ROC curve, score distributions |
| `reports/results.md` | assembled tables, ready to paste into the report |

Every JSON embeds a machine fingerprint (`env`), so timings from different
machines can never be silently mixed.

## 8. Reproducibility checklist

1. Same Python 3.12 venv, `pip freeze > requirements.lock.txt` committed once
   the run you want to publish is done.
2. `--seed` is explicit everywhere and defaults to 1234.
3. Face detection is skipped (LFW is pre-aligned), removing detector randomness.
4. PCA and the decision threshold are fitted on **train** only.
5. `artifacts/` and `reports/` are git-ignored; commit only the final JSON files
   you actually cite.

## 9. Reset

```bash
make clean          # removes build, artifacts and generated report
```

## 10. Suggested extensions (each is a report section on its own)

* Split the driver into two processes (client / server over a socket) to
  measure real network cost — the C++ code is already structured that way.
* 1:N identification against an encrypted gallery, with SIMD batching of many
  gallery templates into a single ciphertext.
* Compare CKKS against a quantised integer scheme (BFV/BGV) on the same task.
* Quantify what the returned score leaks: simulate a hill-climbing attack and
  plot reconstruction quality against the number of queries.
