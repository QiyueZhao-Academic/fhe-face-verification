# Runbook

Everything in this project runs from the macOS Terminal. One command does the
whole study; the sections below cover each stage separately for a reader who
prefers to run them one at a time.

---

## 0. Place the project

Extract the archive and move the folder into `~/FHE`:

```bash
mv ~/Downloads/fhe-face-verification ~/FHE/
cd ~/FHE/fhe-face-verification
```

The project writes into three of its own subdirectories and one cache:

| Path | Contents |
|---|---|
| `~/FHE/fhe-face-verification/build` | compiled binaries |
| `~/FHE/fhe-face-verification/artifacts` | templates, `results.json`, `scores.csv`, session files |
| `~/FHE/fhe-face-verification/reports` | `figures/`, and the hand-written report |
| `~/FHE/ffv-cache` | Python environment, model weights, LFW images |

`run.sh` refuses to read or write any path that lies inside a directory named
`Crypto`, so the sibling project at `~/Crypto` is untouched. Setting `FHE_HOME`
or `FFV_CACHE` moves the cache, and the same refusal applies to whatever they
name.

---

## 1. Run everything

```bash
bash run.sh
```

The nine stages are: environment, dataset and models, face templates, build,
self-test and isolation check, benchmark, two-process protocol, figures,
cross-check.

First run on an M1 with 8 GB of memory: roughly 10 minutes of downloads,
6 to 10 minutes to embed the LFW images with the accurate model, 2 minutes to
build, and 3 to 6 minutes for the benchmark. Later runs skip the downloads.

Check the pipeline first with a short run that finishes in a few minutes:

```bash
bash run.sh --quick
```

`--quick` selects the fast model pack, keeps 40 pairs of each class in each
fold, and reduces the timing repetitions. Use it to confirm the machine is set
up; use the full run for numbers worth quoting.

Open the result:

```bash
open reports/figures
```

---

## 2. Stages one at a time

`--only STAGE` runs a single stage. Each assumes the ones before it have run.

```bash
bash run.sh --only env         # Python environment and Microsoft SEAL
bash run.sh --only assets      # LFW images, pairs.txt, ONNX model pack
bash run.sh --only extract     # photographs to encrypted-ready templates
bash run.sh --only build       # compile
bash run.sh --only test        # self-test and server isolation
bash run.sh --only bench       # every experiment, writes results.json
bash run.sh --only protocol    # one verification across two processes
bash run.sh --only figures     # every figure, into reports/figures
bash run.sh --only crosscheck  # verify the record, and a report when one is there
```

### Stage 1: environment

Locates Microsoft SEAL and prepares a Python environment at
`~/FHE/ffv-cache/venv`.

SEAL is looked for in three places, in order: `SEAL_ROOT` when it is set,
Homebrew (`brew --prefix seal`), and a cached source build. When none is
present, SEAL 4.1.2 is cloned and built into `~/FHE/ffv-cache/seal`, which takes
about five minutes on an M1.

SEAL exports a differently named CMake target depending on how it was built:
`SEAL::seal` for a static library and `SEAL::seal_shared` for a shared one.
Homebrew ships the shared build. Both names are discovered rather than assumed,
and the configure step prints which one it found:

```
-- Microsoft SEAL 4.3.3 as SEAL::seal_shared (SHARED_LIBRARY)
```

The project is verified against SEAL 4.3.3 built shared, which is what Homebrew
installs, and against SEAL 4.1.2 built static, which is the source-build
fallback.

```bash
brew install seal cmake        # the fast path, if it is not already installed
```

The Python packages are `onnxruntime`, `opencv-python-headless`, `numpy`,
and `matplotlib`. All four publish Apple Silicon wheels, so nothing
compiles. An interpreter between 3.10 and 3.13 is chosen when one is present,
because `onnxruntime` publishes wheels for that range.

The stage stops with a message when the shell runs under Rosetta 2, since a
timing measured under translation describes emulation.

### Stage 2: dataset and models

Downloads into `~/FHE/ffv-cache`:

- `lfw/pairs.txt`, the official 6000-pair protocol
- `lfw/lfw-deepfunneled.tgz`, about 111 MB, extracted to one directory per identity
- `models/buffalo_l.zip`, about 289 MB, holding an SCRFD-10G detector and a ResNet50 recogniser

`--model buffalo_s` selects the smaller pack instead: about 128 MB, an
SCRFD-500M detector and a MobileFaceNet recogniser, roughly six times faster
over the whole dataset at a small cost in accuracy.

Every file is verified. The published MD5 of each official LFW file is checked on
every run, so a mirror is accepted only when it serves the identical bytes. The
manifest records the result together with the SHA-256 of each model file:

```bash
cat ~/FHE/ffv-cache/manifest.txt
```

#### Read this if the LFW download fails

The canonical host, `vis-www.cs.umass.edu`, fails to resolve on a number of
networks. This is not a fault in the network as a whole: the same machine
reaches GitHub normally. `torchvision` disabled its own automatic download of
LFW for the same reason.

The stage therefore searches for the data in several places before it gives up.
In order:

1. **A path given with `--lfw-root`.** Used directly, opened read-only.
2. **An image tree already on the machine.** `~/FHE`, `~/Crypto`, `~/Downloads`,
   `~/Documents`, `~/Desktop`, `~/Datasets` and `~/data` are scanned for a
   directory holding one subdirectory per identity. A hit skips the download.
3. **An archive already on the machine.** Any `lfw*.tgz`, `lfw*.tar.gz` or
   `lfw*.zip` in those same directories is extracted into the cache.
4. **Four remote mirrors**, each over three transports: `urllib`, then `curl`,
   then `curl` aimed at an address resolved through DNS-over-HTTPS. The third
   transport is what succeeds when the machine's own resolver is the problem.

If all of that fails, download the archive in a browser from either

- `https://vis-www.cs.umass.edu/lfw/lfw-deepfunneled.tgz`
- `https://archive.org/details/lfw-dataset` — the file `lfw-deepfunneled.zip`

and leave it in `~/Downloads`. That directory is searched, so the next run finds
it:

```bash
bash run.sh --only assets
```

To point at a copy that is already extracted:

```bash
bash run.sh --lfw-root /path/to/lfw-deepfunneled
```

The tree is opened read-only, and stage 3 fingerprints every file's size and
modification time before and after to confirm it was left unchanged. A path
inside a directory named `Crypto` is accepted for reading on those terms, and
`run.sh` still refuses to write anywhere inside such a directory.

`--no-download` restricts the stage to local sources alone.

Two things to check when the images are found but stage 3 then reports missing
files. The protocol lists every image it needs by name, so a subset of LFW
cannot be evaluated against it, and a different face collection will not match
at all. The tree needs this shape:

```
lfw-deepfunneled/
  Abel_Pacheco/
    Abel_Pacheco_0001.jpg
    Abel_Pacheco_0004.jpg
  ...
```

### Stage 3: face templates

Each image named by `pairs.txt` passes through detection, five-point alignment
and embedding once, and the result is cached, because the 6000 pairs name about
7700 distinct images. Output is `artifacts/lfw_templates.ffvemb`, about 25 MB.

The stage prints how many images the detector found a face in. The remainder use
the central crop that the deep-funnelling registration implies, and the count
appears in the report.

```bash
bash run.sh --only extract --pairs 100          # 100 pairs per class per fold
bash run.sh --only extract --detector-size 480  # a larger detector input
```

### Stage 4: build

Configures with CMake and compiles four binaries into `build`:

| Binary | Role |
|---|---|
| `ffv_bench` | every experiment, writes `results.json` and `scores.csv` |
| `ffv_selftest` | 46 checks across seven suites |
| `ffv_client` | key generation, encryption, decryption |
| `ffv_server` | homomorphic evaluation, linked without any decryption code |

Floating-point contraction is switched off, so the cleartext reference scores
are plain IEEE-754 double arithmetic and agree across hosts that differ in their
use of fused multiply-add.

### Stage 5: self-test and isolation

```bash
python3 tools/check_wiring.py
./build/ffv_selftest
bash tools/check_isolation.sh build
```

The wiring check verifies the contracts that join one file of the project to
another: the magic string and field widths of the template container that Python
writes and C++ reads, the JSON paths and CSV columns that C++ writes and Python
reads, the session and request file names shared by the client and the server,
the command-line flags `run.sh` passes to each program, the sources named by
`CMakeLists.txt`, and the paths named by this document. It reads the sources and
needs no build, so `run.sh` also runs it as its first action, where a broken
contract costs a second to find instead of ten minutes.

The self-test covers parameter validation, the modulus chain, the homomorphic
inner product against known values, agreement between the two fold strategies,
slot packing, the metrics layer including tie handling and the refusal to report
an unresolvable operating point, session serialisation, and platform detection.

The isolation check works at three depths: the server sources, the compiled
server objects, and the linked `ffv_server` executable. It also checks the
client library and expects to find the secret-key types there, which shows the
test distinguishes the two halves rather than passing trivially.

### Stage 6: benchmark

```bash
./build/ffv_bench --templates artifacts/lfw_templates.ffvemb --out-dir artifacts
./build/ffv_bench --help
```

Useful options:

| Option | Effect |
|---|---|
| `--pairs N` | keep N pairs of each class in each fold |
| `--mode ct_pt` | score against a cleartext enrolled template |
| `--degree N` | change the polynomial modulus degree |
| `--scale-bits N` | change the scaling factor |
| `--fold naive` | use the d-1 rotation fold for the score table |
| `--score-batch N` | templates packed per ciphertext, 0 for as many as fit |
| `--skip-scale` | omit the scaling-factor sweep |
| `--skip-naive` | omit the d-1 rotation cost baseline |
| `--target-fars L` | comma-separated false accept rates |

The benchmark refuses to run under Rosetta 2.

### Stage 7: two-process protocol

One verification carried out across two operating-system processes that
communicate through files. The server process starts first and waits for the
request marker, so the exchange crosses a real process boundary and the byte
counts are the sizes of the files that crossed it.

```bash
SESSION=artifacts/session
rm -rf "$SESSION"
./build/ffv_client keygen  --session "$SESSION"
./build/ffv_server serve   --session "$SESSION" --once --timeout 120 &
./build/ffv_client request  --session "$SESSION" --templates artifacts/lfw_templates.ffvemb --pair 0
wait
./build/ffv_client collect  --session "$SESSION" --templates artifacts/lfw_templates.ffvemb --pair 0 --threshold 0.28
```

The secret key is written to `$SESSION/private` and read by `ffv_client` alone.
`$SESSION/public` holds the session descriptor and the evaluation keys, and is
the only directory `ffv_server` opens.

### Stage 8: figures

```bash
python3 python/make_figures.py --results artifacts/results.json --out-dir reports
```

Writes every figure into `reports/figures`, each one drawn from `results.json`
and from `scores.csv` alone. The prose of the report is written by hand; this
stage supplies the figures it cites and nothing else.

### Stage 9: cross-check

```bash
python3 python/crosscheck.py --results artifacts/results.json \
    --scores artifacts/scores.csv --markdown reports/report.md
```

Three groups of checks: derived values inside `results.json` recomputed from
their inputs; the accuracy, area under the curve and largest error recomputed
from `scores.csv` and compared with the record; and, when a Markdown report is
present at the path given by `--markdown`, every number in it matched against
the set of numbers derivable from the record. Writing the report as Markdown
therefore puts the hand-written prose under the same check the record is under.
The group is skipped when that file is absent.

---

## 3. What to look at in the output

| Quantity | Where | Meaning |
|---|---|---|
| `verification_encrypted.protocol.accuracy_mean` | `results.json` | accuracy under the fold protocol |
| `equivalence.max_abs_error` | `results.json` | largest gap between an encrypted score and its reference |
| `equivalence.error_over_margin` | `results.json` | below 1 means no decision can change |
| `equivalence.observed_flips` | `results.json` | decisions that did change |
| `cost_ct_ct.server_score.median_ms` | `results.json` | server time for one verification |
| `batching[].amortised_ms_per_verification` | `results.json` | time per verification with packing |
| `scale_fit.measured_slope` | `results.json` | measured against the predicted slope of 1 |
| `operating_points[].resolvable` | `results.json` | whether the sample supports that rate |

---

## 4. When something goes wrong

**`cmake configure failed`, SEAL not found.** Install it, or point the build at
an existing copy:

```bash
brew install seal
SEAL_ROOT="$(brew --prefix seal)" bash run.sh --only build
```

**`get_target_property() called with non-existent target "SEAL::seal"`.** This
came from an earlier version that assumed the static target name. The current
CMakeLists discovers `SEAL::seal` or `SEAL::seal_shared`, whichever the
installation exports. Confirm with:

```bash
python3 tools/check_wiring.py | grep SEAL
```

**Python package installation fails.** `onnxruntime` publishes wheels for 3.10
through 3.13. Install one in that range and rebuild the environment:

```bash
brew install python@3.12
rm -rf ~/FHE/ffv-cache/venv
bash run.sh --only env
```

**The LFW download fails with a name that will not resolve.** See "Read this if
the LFW download fails" under stage 2. The short answer: download
`lfw-deepfunneled.tgz` in a browser, leave it in `~/Downloads`, and run
`bash run.sh --only assets`.

**The download stalls.** Each file is fetched to a `.part` and renamed on
completion, so re-running resumes from the last complete file. Delete a
truncated `.part` and run the stage again.

**A file fails its checksum.** The cached copy is discarded and the next mirror
is tried. A repeated failure on every mirror means the bytes on offer differ from
the published archive, and the manifest records what was seen.

**`this shell runs under Rosetta 2`.** Right-click Terminal in Applications,
choose Get Info, and clear "Open using Rosetta".

**Embedding is slow.** `--model buffalo_s` is about six times faster.
`--pairs 200` shortens the dataset. `--detector-size 224` speeds up detection at
some cost in the detection rate, which the extraction stage prints.

**Memory pressure on an 8 GB machine.** The benchmark holds one score table and
a few ciphertexts, and stays well under a gigabyte. The embedding stage loads one
ONNX model at a time; `--batch-size 8` lowers its peak.

**A cross-check fails.** The message names the disagreeing quantity. Re-run the
benchmark and the report so that both come from the same run:

```bash
bash run.sh --only bench && bash run.sh --only figures && bash run.sh --only crosscheck
```

---

## 5. Starting over

```bash
rm -rf build artifacts reports          # rebuild and re-measure, keep the downloads
rm -rf ~/FHE/ffv-cache                  # discard the environment and the downloads too
```

Neither command touches anything outside `~/FHE`.
