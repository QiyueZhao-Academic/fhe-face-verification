# Privacy-Preserving Face Verification under CKKS Homomorphic Encryption

Two face templates are compared **while both stay encrypted**. The server that
performs the comparison never sees a biometric template and never sees the
similarity score: it only manipulates ciphertexts. Only the client, holding the
secret key, decrypts the final score and applies the decision threshold.

The repository is a small, fully reproducible research harness: plaintext
baseline, PCA reduction study, encrypted benchmark, and an auto-generated
results report.

---

## 1. Why this problem

A face embedding is irrevocable personal data. Under the GDPR it is a special
category (Art. 9), and unlike a password it cannot be reset after a breach.
Classical protection encrypts templates *at rest*, but they must be decrypted to
be compared — the matching server is therefore the weak point. Homomorphic
encryption removes that decryption step entirely.

CKKS (Cheon–Kim–Kim–Song) is the natural scheme here: it operates on vectors of
real numbers with SIMD packing, which is exactly the shape of a face embedding.
Its cost is that arithmetic is *approximate*, so measuring the numerical error
against the plaintext reference is part of the experiment, not an afterthought.

## 2. Protocol

```
CLIENT (holds secret key)                 SERVER (holds nothing)
------------------------------            -------------------------------
u = L2-normalise(embed(image_1))
v = L2-normalise(embed(image_2))
Enc(u), Enc(v)  ------------------------>  c = Enc(u) * Enc(v)     (1 mult.)
                                           relinearise, rescale
                                           rotate-and-add fold over slots
                                           -> Enc(<u, v>)
score = Dec(Enc(<u,v>))  <---------------  Enc(<u,v>)
decision = score >= threshold
```

Because both vectors are L2-normalised, the inner product **is** the cosine
similarity, so a single homomorphic multiplication plus a slot reduction is
enough. Multiplicative depth used: **1**. No bootstrapping, hence the low
latency.

### Threat model (stated explicitly, as a reviewer will ask)

* **Semi-honest server**, single-key setting. The server follows the protocol
  and learns nothing beyond ciphertext sizes and access patterns.
* **Not covered**: a malicious server returning a forged ciphertext (needs
  verifiable computation), collusion between server and client, and the
  information that the *score itself* leaks to the client over many queries
  (hill-climbing / template-reconstruction attacks). See §7.
* Security level: 128 bits (`sec_level_type::tc128`, HomomorphicEncryption.org
  standard parameters).

## 3. Layout

```
src/fheface/            library code
  embeddings.py         LFW / synthetic pair datasets, DeepFace extraction
  metrics.py            ROC, AUC, EER, accuracy (numpy only, no sklearn drift)
  fhe/                  interchangeable CKKS backends
    numpy_backend.py    plaintext reference (NOT encryption) -- correctness check
    tenseal_backend.py  TenSEAL / CKKS
    seal_cpp_backend.py native Microsoft SEAL binary (recommended on macOS ARM)
cpp/ckks_dot.cpp        the SEAL driver: keygen, encrypt, homomorphic dot, decrypt
scripts/00..05          the pipeline, one script per stage
tests/                  fast smoke tests, no heavy dependency
```

## 4. Backends

| Backend    | Encryption | Install cost | Notes                                        |
|------------|-----------|--------------|----------------------------------------------|
| `seal_cpp` | yes       | `brew install seal nlohmann-json cmake` | Recommended on Apple Silicon; timings free of Python overhead |
| `tenseal`  | yes       | `pip install tenseal` | Simplest, when a wheel exists for your Python |
| `numpy`    | **no**    | none         | Reference only: validates metrics and harness |

The pipeline picks the strongest backend available and records `"secure": false`
in the JSON whenever the plaintext reference was used, so a result can never be
mistaken for an encrypted one.

## 5. Quick start

See `RUNBOOK.md` for the full, copy-pasteable procedure. Short version:

```bash
make setup            # venv (Python 3.12) + editable install
make cpp              # build the SEAL driver
make check            # which backends are usable here
make run              # full pipeline -> reports/results.md
```

## 6. What is measured

* **Accuracy, AUC, EER** on the plaintext baseline, with the decision threshold
  selected on the *train* split and applied to *test* (no evaluation leakage).
* **Encrypted accuracy** recomputed from decrypted scores, plus MAE / max
  absolute error against the plaintext scores — this quantifies CKKS noise.
* **Latency**: key generation, encryption per template, homomorphic dot product
  per pair, decryption per pair.
* **Bandwidth**: serialised ciphertext size and Galois key size.
* **PCA study**: 512 → 128 / 64 / 32 dimensions, accuracy loss vs. speed and
  size gain.

## 7. Known limitations

1. **Approximate arithmetic.** CKKS returns the score with a small error; the
   error must stay far below the gap between the genuine and impostor
   distributions, which the report verifies numerically.
2. **Score leakage.** Returning a real-valued score to the client enables
   hill-climbing attacks over repeated queries. Mitigations (returning only the
   thresholded bit, rate limiting, comparison under FHE) are future work.
3. **Semi-honest only.** No integrity guarantee on the server's computation.
4. **1:1 verification.** 1:N identification against an encrypted gallery scales
   linearly and needs batching to be practical.
5. **Single-key.** A production deployment would need multi-key or
   threshold FHE so that the matching service and the enrolment database do not
   trust the same secret key.
6. The embedding model itself runs in plaintext on the client. Encrypting the
   *inference* (as CryptoFace does) is a much harder and separate problem.

## 8. Background reading

* Cheon, Kim, Kim, Song, *Homomorphic Encryption for Arithmetic of Approximate
  Numbers* (CKKS), ASIACRYPT 2017.
* Boddeti, *Secure Face Matching Using Fully Homomorphic Encryption*, BTAS 2018.
* Engelsma, Jain, Boddeti, *HERS: Homomorphically Encrypted Representation
  Search*, IEEE T-BIOM 2022.
* Microsoft SEAL (release 4.x), Microsoft Research.
* Recent work on FHE-friendly face-recognition networks (e.g. CryptoFace, 2025)
  for the encrypted-inference direction.

Check each reference before citing it in a written report; venues and years
should be verified against the published version.

## 9. Licence

Code released for academic use. LFW is redistributed by scikit-learn under its
own terms; check them before publishing derived data.
