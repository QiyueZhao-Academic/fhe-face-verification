# fhe-face-verification

## 📄 [Full experiment report (PDF)](./REPORT.pdf)
Successful local run on macOS · OpenFHE 1.5.1 · [Read online](./reports/report.md)

Privacy-preserving 1:1 face verification on Labeled Faces in the Wild. A deep
network turns each photograph into a 512-dimensional unit-norm template, the
client encrypts it under RNS-CKKS, and the server computes the cosine similarity
of two templates as one homomorphic inner product. The server holds no key.

One command runs the whole study and writes a PDF report whose every number
comes from that run.

```bash
cd ~/FHE/fhe-face-verification
bash run.sh
open reports/report.pdf
```

`RUNBOOK.md` covers each stage separately, along with what to do when a stage
fails.

---

## Résumé (en français)

*Cette section est en français. Le reste du document est en anglais.*

Ce projet met en œuvre une vérification faciale 1:1 respectueuse de la vie
privée sur le jeu de données Labeled Faces in the Wild. Un réseau profond
convertit chaque photographie en un gabarit de 512 dimensions de norme
unitaire ; le client le chiffre sous RNS-CKKS et le serveur calcule la
similarité cosinus de deux gabarits par un unique produit scalaire homomorphe.
Le serveur ne détient aucune clé. Cette séparation est imposée à la
compilation : la bibliothèque et l'exécutable du serveur excluent l'unité de
traduction qui porte la clé secrète, et `tools/check_isolation.sh` le vérifie
sur les sources, sur les objets compilés et sur l'exécutable lié.

Le circuit tient à une profondeur multiplicative de 1 : une multiplication
terme à terme, puis un repliement par rotations de 1, 2, 4 et ainsi de suite
jusqu'à 256, les neuf pas de doublement pour lesquels des clés de Galois sont
produites. Au degré 8192, un chiffré porte 4096 emplacements et un gabarit en
occupe 512, de sorte qu'une seule passe produit huit scores indépendants. La
comparaison au seuil demeure chez le client, qui apprend le score numérique ;
le serveur observe les chiffrés seuls.

Une seule commande exécute l'étude entière et produit un rapport PDF dont
chaque valeur provient de cette exécution : précision à dix plis selon le
protocole officiel de LFW, rapport entre la plus grande erreur de score et la
plus petite marge de décision, coût d'une vérification, apport du regroupement
par emplacements, et dépendance de la précision au facteur d'échelle.
`RUNBOOK.md` détaille chaque étape et la conduite à tenir lorsqu'une étape
échoue.

---

## What it measures

| Question | Answer in the report |
|---|---|
| How accurate is the encrypted pipeline on real faces? | 10-fold accuracy under the official LFW pair protocol, for both the cleartext and the encrypted score tables |
| Does encryption change any decision? | The ratio of the largest score error to the smallest decision margin, which bounds the answer instead of observing it |
| What does one verification cost? | Per-stage server time, key and ciphertext sizes, uplink and downlink per verification |
| What does slot packing buy? | Amortised latency and bandwidth against batch size |
| How does precision depend on the scaling factor? | A measured slope against a prediction fixed at 1 with no fitted constant |
| Does the server hold decryption capability? | A check at three depths: sources, compiled objects, linked executable |
| Do the files still agree with each other? | A static check of every contract that joins two files, run before anything is built |

---

## Getting the dataset

The canonical LFW host fails to resolve on a number of networks, and
`torchvision` disabled its own automatic download of the dataset for that
reason. Stage 2 therefore searches instead of assuming: a path given with
`--lfw-root`, then an image tree or archive already in `~/FHE`, `~/Crypto`,
`~/Downloads`, `~/Documents`, `~/Desktop`, `~/Datasets` or `~/data`, then four
remote mirrors, each over three transports including one that resolves the
hostname through DNS-over-HTTPS.

Every file is verified against the published MD5 of the official archive, so a
mirror is accepted only when its bytes are identical. When every source fails,
download `lfw-deepfunneled.tgz` in a browser, leave it in `~/Downloads`, and run
`bash run.sh --only assets`. `RUNBOOK.md` covers this in full.

---

## Design

**The circuit is one inner product.** Templates leave the client at unit L2
norm, so cosine similarity is a dot product: one element-wise multiplication and
one sum. RNS-CKKS evaluates that at multiplicative depth one, so a single rescale
suffices and bootstrapping stays out of the picture.

**The sum is a rotate-and-sum fold.** Adding a copy of the ciphertext rotated by
one slot, then by two, four and so on up to 256, leaves slot *i* holding the sum
of the 512 consecutive slots that begin at *i*. Because a template occupies a
block whose length is a power of two and divides the slot count, the first slot
of each block holds exactly that block's inner product. Galois keys are generated
for those nine strides alone.

**Eight verifications share one pass.** A ciphertext at degree 8192 carries 4096
slots and a template occupies 512, so eight templates sit side by side. The
multiplication is element-wise and the fold is block-local, so one pass produces
eight independent scores.

**The client compares, the server evaluates.** A threshold comparison under
encryption needs a polynomial approximation to a step function, and the depth
that requires is deliberately excluded. The consequence is explicit in the trust
model: the server learns the ciphertexts and nothing about their contents, and
the client learns the numeric score.

**The separation is enforced by the build.** The server library and the server
executable are compiled without the translation unit holding the secret key.
`tools/check_isolation.sh` verifies this by reading the server sources, the
compiled server objects and the linked executable, and by confirming that the
client library does reference the secret-key types, which shows the check
distinguishes the two halves.

---

## Parameters

| | |
|---|---|
| Scheme | RNS-CKKS, Microsoft SEAL 4.x |
| Polynomial modulus degree | 8192, giving 4096 slots |
| Coefficient modulus | 60, 40, 60 bits — 160 of the 218 that tc128 permits at this degree |
| Scaling factor | 2^40 |
| Security level | tc128 |
| Multiplicative depth | 1 |
| Rotations per score | 9 |
| Templates per ciphertext | 8 |

The last prime in the chain is the key-switching prime and carries no plaintext,
so the data chain holds two levels: one product, one rescale.

---

## Layout

```
run.sh                    the whole study in one command
CMakeLists.txt
include/ffv/              crypto, client, server, templates, metrics, json, io, timing, platform
src/core/                 implementations; server.cpp names no secret key
src/bench/                one file per experiment, one JSON emitter
src/apps/                 ffv_bench, ffv_client, ffv_server, ffv_selftest
python/ffv/               face frontend, LFW protocol, figures, report
python/                   fetch_assets, extract_embeddings, make_report, crosscheck
tools/check_isolation.sh  server isolation at three depths
tools/check_wiring.py     every contract joining one file to another
```

`src/bench/emit_json.cpp` is the only place the benchmark writes numbers, and
the report generator reads that file and nothing else, so a figure in the PDF
and a figure on the console cannot disagree.

---

## Requirements

- macOS on Apple Silicon, or Linux on x86-64
- CMake 3.22 or newer, and a C++17 compiler
- Microsoft SEAL 4.x — `brew install seal`, or `run.sh` builds it into the cache.
  Both the static target `SEAL::seal` and the shared target `SEAL::seal_shared`
  are supported; the build discovers which one the installation exports.
- Python 3.10 to 3.13, for `onnxruntime`, `opencv-python-headless`, `numpy`, `matplotlib`, `reportlab`

Microsoft SEAL is the only compiled dependency. The C++ side uses no JSON
library, no test framework and no numerical library. PDF generation uses
ReportLab and needs no LaTeX.

---

## Where files are written

| Path | Contents |
|---|---|
| `build/` | compiled binaries |
| `artifacts/` | templates, `results.json`, `scores.csv`, session files |
| `reports/` | `report.pdf`, `report.md`, figures |
| `$FHE_HOME/ffv-cache/` | Python environment, model weights, LFW images |

`FHE_HOME` defaults to the directory holding the project, so a project at
`~/FHE/fhe-face-verification` caches into `~/FHE/ffv-cache`. `run.sh` refuses
any path lying inside a directory named `Crypto`.

---

## Reproducibility

Floating-point contraction is switched off at compile time, so the cleartext
reference scores are plain IEEE-754 double arithmetic and agree bit for bit
across hosts that would otherwise differ in their use of fused multiply-add.

The sources compile warning-free under GCC with libstdc++ and under Clang with
libc++, including with libc++'s transitive includes disabled. Apple's libc++
removes transitive includes over time, so every name is accompanied by the header
that declares it and `tools/check_wiring.py` enforces that.

The benchmark records the host, the compiler, the flags and the SEAL version
next to the timings, and stops when it detects Rosetta 2 translation, since a
latency measured under emulation describes the emulator.

The asset manifest records the SHA-256 of every model file, so the weights behind
a set of numbers can be named afterwards.

Two checks guard consistency, one static and one after the run.

`tools/check_wiring.py` reads the sources and verifies the contracts that join
one file to another: the magic string and field widths of the template container
that Python writes and C++ reads, the JSON paths and CSV columns that C++ writes
and Python reads, the session and request file names shared by the client and the
server, the flags `run.sh` passes to each program, the sources named by
`CMakeLists.txt`, and the paths named by the documentation. It needs no build, so
`run.sh` runs it first.

`python/crosscheck.py` recomputes the derived values inside `results.json` from
their inputs, recomputes the accuracy and the largest error from `scores.csv`,
and matches every number in `report.md` against the set derivable from the
record.

---

## References

- Cheon, Kim, Kim and Song. Homomorphic Encryption for Arithmetic of Approximate Numbers. ASIACRYPT 2017.
- Cheon, Han, Kim, Kim and Song. A Full RNS Variant of Approximate Homomorphic Encryption. SAC 2018.
- Boddeti. Secure Face Matching Using Fully Homomorphic Encryption. BTAS 2018.
- Engelsma, Jain and Boddeti. HERS: Homomorphically Encrypted Representation Search. IEEE T-BIOM 4(3), 2022.
- Deng, Guo, Xue and Zafeiriou. ArcFace: Additive Angular Margin Loss for Deep Face Recognition. CVPR 2019.
- Guo, Deng, Lattas and Zafeiriou. Sample and Computation Redistribution for Efficient Face Detection. ICLR 2022.
- Huang, Ramesh, Berg and Learned-Miller. Labeled Faces in the Wild. UMass Amherst TR 07-49, 2007.

## License

MIT. See `LICENSE`. Labeled Faces in the Wild and the InsightFace model weights
carry their own terms, which apply to any use of them here.
