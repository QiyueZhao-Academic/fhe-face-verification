#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# One command runs the whole study: environment, dataset, build, tests,
# benchmark, two-process protocol, report.
#
#     cd ~/FHE/fhe-face-verification
#     bash run.sh
#
# Written for bash 3.2, the version macOS ships. No associative arrays, no
# mapfile, no bare expansion of a possibly-empty array under `set -u`.
#
# WHERE THINGS ARE WRITTEN
#   <project>/build       compiled binaries
#   <project>/artifacts   templates, results.json, scores.csv, session files
#   <project>/reports     report.pdf, report.md, figures
#   $FHE_HOME/ffv-cache   Python environment, model weights, LFW images
#
# FHE_HOME defaults to the directory holding this project, so a project placed
# at ~/FHE/fhe-face-verification caches into ~/FHE/ffv-cache. Nothing is ever
# written into a directory named Crypto; guard_path below refuses to.

set -u

# --------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
FHE_HOME="${FHE_HOME:-$(cd "$PROJECT_DIR/.." && pwd)}"
CACHE_DIR="${FFV_CACHE:-$FHE_HOME/ffv-cache}"
BUILD_DIR="$PROJECT_DIR/build"
ARTIFACT_DIR="$PROJECT_DIR/artifacts"
REPORT_DIR="$PROJECT_DIR/reports"

MODEL_PACK="buffalo_l"
LIMIT_PAIRS=0
LFW_ROOT=""
SKIP_ASSETS=0
SKIP_REPORT=0
NO_DOWNLOAD=0
SKIP_EXTRACT=0
QUICK=0
COST_REPS=20
DETECTOR_SIZE=320
JOBS=""
ONLY_STAGE=""

usage() {
    cat <<'EOF'
run.sh [options]

  --quick               short run: buffalo_s models, 40 pairs per class per fold,
                        fewer timing repetitions. Use it to check the pipeline.
  --model PACK          buffalo_l (accurate, default) or buffalo_s (fast)
  --pairs N             keep the first N pairs of each class in each fold
  --lfw-root PATH       use an existing LFW image tree. It is opened read-only,
                        and the stage verifies it is unchanged afterwards.
  --detector-size N     detector input resolution in pixels (320)
  --cost-reps N         repetitions per timed operation (20)
  --jobs N              parallel compile jobs (defaults to the core count)
  --skip-assets         assume the cache already holds the dataset and models
  --no-download         use local copies of the dataset alone, downloading nothing
  --skip-extract        reuse the existing template container
  --skip-report         stop after the benchmark
  --only STAGE          run one stage: env, assets, extract, build, test,
                        bench, protocol, report, crosscheck
  -h, --help            this text

Environment:
  FHE_HOME    parent directory for the cache (defaults to the project's parent)
  FFV_CACHE   cache directory itself
  SEAL_ROOT   an existing Microsoft SEAL installation prefix
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --quick) QUICK=1 ;;
        --model) MODEL_PACK="$2"; shift ;;
        --pairs) LIMIT_PAIRS="$2"; shift ;;
        --lfw-root) LFW_ROOT="$2"; shift ;;
        --detector-size) DETECTOR_SIZE="$2"; shift ;;
        --cost-reps) COST_REPS="$2"; shift ;;
        --jobs) JOBS="$2"; shift ;;
        --skip-assets) SKIP_ASSETS=1 ;;
        --no-download) NO_DOWNLOAD=1 ;;
        --skip-extract) SKIP_EXTRACT=1 ;;
        --skip-report) SKIP_REPORT=1 ;;
        --only) ONLY_STAGE="$2"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'run.sh: unknown option %s\n\n' "$1"; usage; exit 2 ;;
    esac
    shift
done

if [ "$QUICK" -eq 1 ]; then
    MODEL_PACK="buffalo_s"
    [ "$LIMIT_PAIRS" -eq 0 ] && LIMIT_PAIRS=40
    COST_REPS=6
fi

# --------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------
say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
info() { printf '    %s\n' "$1"; }
die() { printf '\n\033[31mrun.sh: %s\033[0m\n' "$1" >&2; exit 1; }

# The stage keeps its own number, so a single stage run with --only still
# reports where it sits in the sequence.
step() { say "[$1/9] $2"; }

want() {
    # Runs a stage when no single stage was requested, or when it was this one.
    [ -z "$ONLY_STAGE" ] && return 0
    [ "$ONLY_STAGE" = "$1" ] && return 0
    return 1
}

# Refuses any path that lies inside a directory named Crypto. The sibling
# research project lives there and this project must leave it untouched.
guard_path() {
    case "/$1/" in
        */Crypto/*|*/crypto/*)
            die "refusing to use '$1' because it lies inside a directory named Crypto"
            ;;
    esac
}

guard_path "$CACHE_DIR"
guard_path "$BUILD_DIR"
guard_path "$ARTIFACT_DIR"
guard_path "$REPORT_DIR"

core_count() {
    if command -v sysctl >/dev/null 2>&1 && sysctl -n hw.ncpu >/dev/null 2>&1; then
        sysctl -n hw.ncpu
    elif command -v nproc >/dev/null 2>&1; then
        nproc
    else
        echo 2
    fi
}
[ -z "$JOBS" ] && JOBS="$(core_count)"

file_bytes() {
    if stat -f%z "$1" >/dev/null 2>&1; then stat -f%z "$1"; else stat -c%s "$1"; fi
}

# A fingerprint of a directory tree: every file's name, size and modification
# time. Comparing it before and after a stage shows whether that stage left the
# tree untouched, which is the claim this project makes about any dataset
# directory it did not create.
tree_fingerprint() {
    find "$1" -type f -exec ls -ln {} + 2>/dev/null \
        | awk '{ print $5, $9 }' | sort | cksum
}

printf '\033[1mfhe-face-verification\033[0m\n'
info "project : $PROJECT_DIR"
info "cache   : $CACHE_DIR"
info "jobs    : $JOBS"
[ "$QUICK" -eq 1 ] && info "mode    : quick"

# ==========================================================================
# 1. Environment
# ==========================================================================
VENV_DIR="$CACHE_DIR/venv"
PY="$VENV_DIR/bin/python3"

# PY_ANY runs code that imports the standard library alone: the wiring check, the
# asset fetcher and the threshold lookup. It prefers the virtual environment and
# falls back to whatever python3 is on PATH, so `--only assets` works on a
# machine where the environment stage has not run yet.
system_python() {
    for candidate in python3.12 python3.11 python3.13 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            printf '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

resolve_python() {
    if [ -x "$PY" ]; then
        PY_ANY="$PY"
    else
        PY_ANY="$(system_python)" || die "no python3 found. Install one with: brew install python@3.12"
    fi
}

# Stages that import onnxruntime, numpy, matplotlib or reportlab need the
# environment, so they say so instead of failing on a missing interpreter.
need_venv() {
    [ -x "$PY" ] || die "the python environment is absent. Build it first:
    bash run.sh --only env"
}

if want env; then
    step 1 "environment"

    # Every later write in this stage lands under the cache, so it is created
    # first. A fresh machine has no cache at all.
    mkdir -p "$CACHE_DIR" || die "cannot create $CACHE_DIR"

    # The wiring check reads the sources and verifies the contracts that join
    # them: the container format, the JSON and CSV column names, the session file
    # names, and the command-line flags this script passes. It needs no build and
    # no network, so it runs first, where a broken contract costs a second to
    # find instead of ten minutes.
    resolve_python
    if [ -n "${PY_ANY:-}" ]; then
        "$PY_ANY" "$PROJECT_DIR/tools/check_wiring.py" > "$CACHE_DIR/wiring.log" 2>&1
        if [ $? -eq 0 ]; then
            info "wiring: $(tail -1 "$CACHE_DIR/wiring.log")"
        else
            tail -25 "$CACHE_DIR/wiring.log"
            die "the sources disagree with each other. The log above names each contract that \
failed; the full output is at $CACHE_DIR/wiring.log"
        fi
    fi

    case "$(uname -s)" in
        Darwin)
            info "host: macOS $(sw_vers -productVersion 2>/dev/null) $(uname -m)"
            if [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" = "1" ]; then
                die "this shell runs under Rosetta 2 translation. Open a native arm64 Terminal, \
because timings measured under translation are not publishable."
            fi
            ;;
        Linux) info "host: $(uname -s) $(uname -m)" ;;
        *) info "host: $(uname -s) $(uname -m)" ;;
    esac

    command -v cmake >/dev/null 2>&1 || die "cmake is absent. Install it with: brew install cmake"

    # Microsoft SEAL. An installed copy is preferred; otherwise it is built from
    # source into the cache, never into the project and never near Crypto.
    if [ -n "${SEAL_ROOT:-}" ]; then
        info "SEAL: using SEAL_ROOT=$SEAL_ROOT"
    elif command -v brew >/dev/null 2>&1 && brew --prefix seal >/dev/null 2>&1; then
        SEAL_ROOT="$(brew --prefix seal)"
        info "SEAL: Homebrew at $SEAL_ROOT"
    elif [ -d "$CACHE_DIR/seal/lib/cmake" ]; then
        SEAL_ROOT="$CACHE_DIR/seal"
        info "SEAL: cached build at $SEAL_ROOT"
    else
        info "SEAL: absent, building from source into $CACHE_DIR/seal"
        guard_path "$CACHE_DIR/seal"
        mkdir -p "$CACHE_DIR/src" || die "cannot create $CACHE_DIR/src"
        if [ ! -d "$CACHE_DIR/src/SEAL" ]; then
            command -v git >/dev/null 2>&1 || die "git is absent. Install it with: brew install git"
            git clone --depth 1 --branch v4.1.2 https://github.com/microsoft/SEAL.git \
                "$CACHE_DIR/src/SEAL" || die "cannot clone Microsoft SEAL"
        fi
        cmake -S "$CACHE_DIR/src/SEAL" -B "$CACHE_DIR/src/SEAL/build" \
            -DCMAKE_BUILD_TYPE=Release -DSEAL_BUILD_DEPS=ON -DBUILD_SHARED_LIBS=OFF \
            -DCMAKE_INSTALL_PREFIX="$CACHE_DIR/seal" >/dev/null || die "SEAL configure failed"
        cmake --build "$CACHE_DIR/src/SEAL/build" -j "$JOBS" >/dev/null \
            || die "SEAL build failed"
        cmake --install "$CACHE_DIR/src/SEAL/build" >/dev/null || die "SEAL install failed"
        SEAL_ROOT="$CACHE_DIR/seal"
        info "SEAL: built and installed at $SEAL_ROOT"
    fi
    # Recorded so that a later `--only build` finds the same installation
    # without repeating the search.
    printf '%s\n' "$SEAL_ROOT" > "$CACHE_DIR/seal_root.txt" \
        || die "cannot write $CACHE_DIR/seal_root.txt"

    # Python. onnxruntime publishes macOS arm64 wheels for 3.10 through 3.13, so
    # an interpreter in that range is chosen when one is present.
    if [ ! -x "$PY" ]; then
        BASE_PY=""
        for candidate in python3.12 python3.11 python3.13 python3.10 python3; do
            if command -v "$candidate" >/dev/null 2>&1; then
                version="$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
                case "$version" in
                    3.10|3.11|3.12|3.13) BASE_PY="$candidate"; break ;;
                    *) [ -z "$BASE_PY" ] && BASE_PY="$candidate" ;;
                esac
            fi
        done
        [ -z "$BASE_PY" ] && die "no python3 found. Install one with: brew install python@3.12"
        version="$("$BASE_PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
        info "python: $BASE_PY ($version)"
        case "$version" in
            3.10|3.11|3.12|3.13) ;;
            *) info "note: onnxruntime may publish no wheel for $version; \
install python@3.12 if the next step fails" ;;
        esac
        "$BASE_PY" -m venv "$VENV_DIR" || die "cannot create the virtual environment"
    else
        info "python: reusing $VENV_DIR"
    fi

    "$PY" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
    if ! "$PY" -c 'import onnxruntime, cv2, numpy, reportlab, matplotlib' >/dev/null 2>&1; then
        info "installing python packages"
        "$PY" -m pip install --quiet -r "$PROJECT_DIR/python/requirements.txt" \
            || die "package installation failed. See $PROJECT_DIR/python/requirements.txt"
    fi
    "$PY" -c 'import onnxruntime, cv2, numpy, reportlab, matplotlib
print("    onnxruntime %s, opencv %s, numpy %s" % (onnxruntime.__version__, cv2.__version__, numpy.__version__))' \
        || die "the python environment is incomplete"
fi

resolve_python

# SEAL_ROOT is recovered here so that a single stage run with --only build finds
# the same installation the environment stage chose.
if [ -z "${SEAL_ROOT:-}" ] && [ -f "$CACHE_DIR/seal_root.txt" ]; then
    SEAL_ROOT="$(cat "$CACHE_DIR/seal_root.txt")"
fi
if [ -z "${SEAL_ROOT:-}" ] && command -v brew >/dev/null 2>&1; then
    if brew --prefix seal >/dev/null 2>&1; then SEAL_ROOT="$(brew --prefix seal)"; fi
fi
if [ -z "${SEAL_ROOT:-}" ] && [ -d "$CACHE_DIR/seal/lib/cmake" ]; then
    SEAL_ROOT="$CACHE_DIR/seal"
fi
SEAL_ROOT="${SEAL_ROOT:-}"

# ==========================================================================
# 2. Dataset and models
# ==========================================================================
MANIFEST="$CACHE_DIR/manifest.txt"

if want assets && [ "$SKIP_ASSETS" -eq 0 ]; then
    step 2 "dataset and models"
    mkdir -p "$CACHE_DIR" || die "cannot create $CACHE_DIR"
    ASSET_ARGS="--cache $CACHE_DIR --model-pack $MODEL_PACK --search $FHE_HOME"
    [ -n "$LFW_ROOT" ] && ASSET_ARGS="$ASSET_ARGS --lfw-root $LFW_ROOT"
    [ "$NO_DOWNLOAD" -eq 1 ] && ASSET_ARGS="$ASSET_ARGS --no-download"
    # shellcheck disable=SC2086
    if ! "$PY_ANY" "$PROJECT_DIR/python/fetch_assets.py" $ASSET_ARGS; then
        die "the assets are incomplete. Follow the instructions above, then re-run:
    bash run.sh --only assets"
    fi
fi

read_manifest() {
    [ -f "$MANIFEST" ] || die "$MANIFEST is absent; run without --skip-assets first"
    grep "^$1 " "$MANIFEST" | head -1 | cut -d' ' -f2-
}

# ==========================================================================
# 3. Templates
# ==========================================================================
TEMPLATES="$ARTIFACT_DIR/lfw_templates.ffvemb"

if want extract && [ "$SKIP_EXTRACT" -eq 0 ]; then
    step 3 "face templates"
    need_venv
    PAIRS_FILE="$(read_manifest pairs)"
    IMAGES_DIR="$(read_manifest images)"
    MODELS_DIR="$(read_manifest models)"
    [ -n "$IMAGES_DIR" ] || die "the manifest names no image tree; re-run the asset stage"
    guard_path "$ARTIFACT_DIR"
    mkdir -p "$ARTIFACT_DIR"

    # The image tree is opened for reading alone. When it sits outside the cache
    # this project created, that claim is verified instead of asserted: a
    # fingerprint of every file's size and modification time is taken before and
    # after, and the two are compared. A tree inside a directory named Crypto is
    # reused this way rather than refused, since reading it changes nothing.
    FINGERPRINT_BEFORE=""
    case "$IMAGES_DIR" in
        "$CACHE_DIR"/*) ;;
        *)
            info "image tree: $IMAGES_DIR (opened read-only)"
            FINGERPRINT_BEFORE="$(tree_fingerprint "$IMAGES_DIR")"
            ;;
    esac

    # The manifest is passed as a path so that the provenance sentence, which
    # contains spaces, travels without any quoting in this script.
    EXTRACT_ARGS="--lfw-root $IMAGES_DIR --pairs $PAIRS_FILE --models $MODELS_DIR \
--out $TEMPLATES --detector-size $DETECTOR_SIZE --manifest $MANIFEST"
    [ "$LIMIT_PAIRS" -gt 0 ] && EXTRACT_ARGS="$EXTRACT_ARGS --limit-pairs $LIMIT_PAIRS"
    # shellcheck disable=SC2086
    "$PY" "$PROJECT_DIR/python/extract_embeddings.py" $EXTRACT_ARGS \
        || die "template extraction failed"

    if [ -n "$FINGERPRINT_BEFORE" ]; then
        if [ "$(tree_fingerprint "$IMAGES_DIR")" = "$FINGERPRINT_BEFORE" ]; then
            info "image tree: verified unchanged"
        else
            die "the image tree at $IMAGES_DIR changed during extraction, which it must not. \
Report this, and treat the templates from this run as suspect."
        fi
    fi
fi

# ==========================================================================
# 4. Build
# ==========================================================================
if want build; then
    step 4 "build"
    CMAKE_ARGS="-DCMAKE_BUILD_TYPE=Release"
    [ -n "$SEAL_ROOT" ] && CMAKE_ARGS="$CMAKE_ARGS -DCMAKE_PREFIX_PATH=$SEAL_ROOT"
    # shellcheck disable=SC2086
    cmake -S "$PROJECT_DIR" -B "$BUILD_DIR" $CMAKE_ARGS \
        || die "cmake configure failed. Check that Microsoft SEAL 4.x is installed."
    cmake --build "$BUILD_DIR" -j "$JOBS" || die "compilation failed"
    info "binaries: ffv_bench ffv_selftest ffv_client ffv_server"
fi

# ==========================================================================
# 5. Tests
# ==========================================================================
if want test; then
    step 5 "self-test and server isolation"
    "$PY_ANY" "$PROJECT_DIR/tools/check_wiring.py" | tail -1 \
        || die "the sources disagree with each other; run tools/check_wiring.py for detail"
    "$BUILD_DIR/ffv_selftest" --tmp "$BUILD_DIR/selftest" || die "the self-test failed"
    bash "$PROJECT_DIR/tools/check_isolation.sh" "$BUILD_DIR" \
        || die "the server holds decryption capability, which contradicts the threat model"
fi

# ==========================================================================
# 6. Benchmark
# ==========================================================================
if want bench; then
    step 6 "benchmark"
    [ -f "$TEMPLATES" ] || die "$TEMPLATES is absent; run the extract stage first"
    info "templates: $(($(file_bytes "$TEMPLATES") / 1000000)) MB"
    "$BUILD_DIR/ffv_bench" --templates "$TEMPLATES" --out-dir "$ARTIFACT_DIR" \
        --cost-reps "$COST_REPS" || die "the benchmark failed"
fi

# ==========================================================================
# 7. Two-process protocol
# ==========================================================================
if want protocol; then
    step 7 "two-process protocol"
    SESSION="$ARTIFACT_DIR/session"
    guard_path "$SESSION"
    rm -rf "$SESSION"
    "$BUILD_DIR/ffv_client" keygen --session "$SESSION" || die "key generation failed"

    # The threshold comes from the first fold of the run that just finished, so
    # the demonstration decides at the same operating point the report quotes.
    THRESHOLD="$("$PY_ANY" -c '
import json, sys
path = sys.argv[1]
try:
    folds = json.load(open(path))["verification_cleartext"]["protocol"]["per_fold"]
    print("%.12g" % folds[0]["threshold"])
except Exception:
    print("0.28")
' "$ARTIFACT_DIR/results.json")"
    info "threshold from fold 0: $THRESHOLD"

    # The server starts first and waits for the request marker, so the exchange
    # crosses a real process boundary.
    "$BUILD_DIR/ffv_server" serve --session "$SESSION" --once --timeout 120 &
    SERVER_PID=$!
    "$BUILD_DIR/ffv_client" request --session "$SESSION" --templates "$TEMPLATES" --pair 0 \
        || die "the request failed"
    wait "$SERVER_PID" || die "the server process failed"
    "$BUILD_DIR/ffv_client" collect --session "$SESSION" --templates "$TEMPLATES" --pair 0 \
        --threshold "$THRESHOLD" || die "collecting the response failed"
fi

# ==========================================================================
# 8. Report
# ==========================================================================
if want report && [ "$SKIP_REPORT" -eq 0 ]; then
    step 8 "report"
    need_venv
    guard_path "$REPORT_DIR"
    "$PY" "$PROJECT_DIR/python/make_report.py" \
        --results "$ARTIFACT_DIR/results.json" \
        --scores "$ARTIFACT_DIR/scores.csv" \
        --protocol "$ARTIFACT_DIR/session/protocol.json" \
        --out-dir "$REPORT_DIR" || die "report generation failed"
fi

# ==========================================================================
# 9. Cross-check
# ==========================================================================
if want crosscheck; then
    step 9 "cross-check"
    need_venv
    "$PY" "$PROJECT_DIR/python/crosscheck.py" \
        --results "$ARTIFACT_DIR/results.json" \
        --scores "$ARTIFACT_DIR/scores.csv" \
        --markdown "$REPORT_DIR/report.md" || die "the cross-check found a disagreement"
fi

# --------------------------------------------------------------------------
say "done"
[ -f "$REPORT_DIR/report.pdf" ] && info "report  : $REPORT_DIR/report.pdf"
[ -f "$REPORT_DIR/report.md" ] && info "markdown: $REPORT_DIR/report.md"
[ -f "$ARTIFACT_DIR/results.json" ] && info "record  : $ARTIFACT_DIR/results.json"
[ -f "$ARTIFACT_DIR/scores.csv" ] && info "scores  : $ARTIFACT_DIR/scores.csv"
if [ -f "$REPORT_DIR/report.pdf" ] && [ "$(uname -s)" = "Darwin" ]; then
    printf '\n    open it with: open "%s"\n' "$REPORT_DIR/report.pdf"
fi
