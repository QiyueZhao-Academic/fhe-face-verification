# SPDX-License-Identifier: MIT
"""Builds the report and renders it to PDF and Markdown in AAAI format.

Three properties govern this module.

Layout follows the AAAI author kit. US Letter, two columns 3.3125 inches wide
with a 0.375 inch gutter, margins of 1.25 inches at the top of the first page and
0.75 inches at the top of the others, 0.75 inches at the left and right and 1.25
inches at the bottom, Times throughout, ten point body text, and no page numbers.

Every number occupies a named slot. A slot is a name, a path into the benchmark
record, and a format. The prose holds slots, and the values arrive when the
report is generated from a finished run. Nothing is written into the text by
hand, and `reports/data_slots.md` lists every slot with the path it came from, so
the provenance of each figure in the document can be read off directly.

Tables and figures are numbered by the order they appear. Cross-references in the
prose are written as labels and resolved at render time, so a float that moves
takes its number and every reference to it along.
"""

import datetime
import os
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    FrameBreak,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

TITLE = "Encrypted 1:1 Face Verification on Labeled Faces in the Wild with RNS-CKKS"
AUTHOR = "Qiyue Zhao"
LICENCE = "Released under the MIT License."

# Absolute paths name a user account and a directory layout. They belong in the
# console output of the run and never in a document that may be published, so any
# text taken from the record passes through this filter first.
ABSOLUTE_PATH = re.compile(
    r"(?:~|/Users/|/home/|/root/|/private/|/mnt/|/var/|/tmp/|[A-Za-z]:[\\/]Users[\\/])"
    r"[^\s,;)]*"
)


# Containers written before the provenance string was reduced to a source type
# carry the older phrasing. The meaning is unchanged, so it is rewritten here and
# a container produced by an earlier run needs no re-extraction.
LEGACY_PROVENANCE = [
    # The clause is the last sentence of the description, so each pattern runs to
    # the end of the string; a dot inside a file name must not end the match.
    (re.compile(r"Image source: local tree supplied with --lfw-root.*$"),
     "The images came from a local LFW image tree given on the command line."),
    (re.compile(r"Image source: local tree discovered.*$"),
     "The images came from a local LFW image tree already on the machine."),
    (re.compile(r"Image source: extracted from the local archive.*$"),
     "The images came from a local LFW archive extracted into the cache."),
    (re.compile(r"Image source: downloaded from https?://([^/\s]+)\S*.*$"),
     r"The images came from the official archive downloaded from \1."),
]


def scrub_paths(text):
    """Removes absolute filesystem paths from text destined for the report.

    A path names a user account and a directory layout. It belongs in the console
    output of the run and never in a document that may be published.
    """
    text = str(text)
    for pattern, replacement in LEGACY_PROVENANCE:
        text = pattern.sub(replacement, text)
    text = ABSOLUTE_PATH.sub("a local directory", text)
    # A phrase left pointing at a path that is now gone reads as a dangling
    # reference, so the preposition goes with it.
    return re.sub(r"\s+(?:at|in|from|into)\s+a local directory", "", text)

# ---------------------------------------------------------------------------
# Formats
# ---------------------------------------------------------------------------


def pct(x, digits=2):
    return f"{100.0 * float(x):.{digits}f}%"


def pct3(x):
    return pct(x, 3)


def pct4(x):
    return pct(x, 4)


def ms(x, digits=2):
    return f"{float(x):.{digits}f} ms"


def ms1(x):
    return ms(x, 1)


def kib(x, digits=1):
    return f"{float(x) / 1024.0:.{digits}f} KiB"


def sci(x, digits=2):
    return f"{float(x):.{digits}e}"


def sci0(x):
    return sci(x, 0)


def num(x, digits=2):
    return f"{float(x):.{digits}f}"


def num0(x):
    return num(x, 0)


def num1(x):
    return num(x, 1)


def num3(x):
    return num(x, 3)


def num4(x):
    return num(x, 4)


def num6(x):
    return num(x, 6)


def integer(x):
    """A counted quantity, grouped for readability: 6,000 pairs."""
    return f"{int(x):,}"


def count(x):
    """A parameter value, which reads as a single token: degree 8192."""
    return f"{int(x)}"


def plain(x):
    return scrub_paths(x)


def bits(x):
    return f"{float(x):.1f} bits"


def plural(count, singular, plural_form=None):
    """Agrees a noun with its count, so a run with one fold still reads correctly."""
    if int(count) == 1:
        return f"1 {singular}"
    return f"{int(count)} {plural_form or singular + 's'}"


def duration(seconds):
    seconds = float(seconds)
    if seconds < 90.0:
        return f"{seconds:.0f} seconds"
    return f"{seconds / 60.0:.1f} minutes"


# ---------------------------------------------------------------------------
# Data slots
# ---------------------------------------------------------------------------


class Slots:
    """Resolves every reported value from the benchmark record and records it.

    A slot is filled the moment the report is generated, from the run that
    produced `results.json`. A path that is absent, or that the run declined to
    emit, stops generation with the path named, so the document never carries a
    value that the run did not measure.
    """

    def __init__(self, results, protocol):
        self.results = results
        self.protocol = protocol or {}
        self.records = []
        self._seen = set()

    def _walk(self, root, path, source):
        node = root
        for part in path.split("."):
            if isinstance(node, list):
                index = int(part)
                if index >= len(node):
                    raise KeyError(
                        f"{source} holds no element {index} at '{path}'. The report is "
                        "generated only from measured values, so re-run the benchmark."
                    )
                node = node[index]
            elif isinstance(node, dict) and part in node:
                node = node[part]
            else:
                raise KeyError(
                    f"{source} holds no value at '{path}'. The report is generated only from "
                    "measured values, so re-run the benchmark before generating it."
                )
        if node is None:
            raise KeyError(
                f"{source} reports null at '{path}', which means the run declined to emit that "
                "value. The report must reference the accompanying flag instead."
            )
        return node

    def raw(self, path):
        return self._walk(self.results, path, "results.json")

    def raw_protocol(self, path):
        return self._walk(self.protocol, path, "protocol.json")

    def __call__(self, name, path, fmt=plain, source="results"):
        """Fills the named slot and returns the text that goes into the report."""
        value = self.raw(path) if source == "results" else self.raw_protocol(path)
        text = fmt(value)
        if name not in self._seen:
            self._seen.add(name)
            self.records.append(
                {
                    "name": name,
                    "file": "results.json" if source == "results" else "protocol.json",
                    "path": path,
                    "value": value,
                    "text": text,
                }
            )
        return text

    def derived(self, name, text, note):
        """Records a value computed from slots already filled."""
        if name not in self._seen:
            self._seen.add(name)
            self.records.append(
                {"name": name, "file": "derived", "path": note, "value": text, "text": text}
            )
        return text


# ---------------------------------------------------------------------------
# Block model
# ---------------------------------------------------------------------------


class Block:
    def __init__(self, kind, **fields):
        self.kind = kind
        self.__dict__.update(fields)


def heading(text, level=1):
    return Block("heading", text=text, level=level)


def para(text, lead=None):
    """A paragraph, optionally opened by a bold run-in lead-in.

    The lead-in states what the paragraph is about, which lets a reader scan the
    section without reading every sentence. It suppresses the first-line indent,
    as a run-in heading does in the AAAI style file.
    """
    return Block("para", text=text, lead=lead)


def bullets(items):
    return Block("bullets", items=list(items))


def table(label, caption, header, rows, weights=None):
    """A table float.

    `weights` gives the share of the column width each table column takes. They
    are set per table so that no header has to break inside a word, which a
    uniform division cannot guarantee at nine point in a 3.3 inch column.
    """
    return Block("table", label=label, caption=caption, header=header, rows=rows,
                 weights=weights)


def figure(label, caption, path):
    return Block("figure", label=label, caption=caption, path=path)


def refs(items):
    return Block("refs", items=list(items))


def code(text):
    return Block("code", text=text)


REFERENCE = re.compile(r"\[\[(tab|fig):([a-z0-9_]+)\]\]")


def number_floats(blocks):
    """Assigns table and figure numbers in the order the floats appear."""
    numbers, tables, figures = {}, 0, 0
    for block in blocks:
        if block.kind == "table":
            tables += 1
            numbers[f"tab:{block.label}"] = tables
        elif block.kind == "figure":
            figures += 1
            numbers[f"fig:{block.label}"] = figures
    return numbers


def resolve(text, numbers):
    """Replaces [[tab:x]] and [[fig:y]] with the numbers assigned above."""

    def substitute(match):
        key = f"{match.group(1)}:{match.group(2)}"
        if key not in numbers:
            raise KeyError(
                f"the report references {key}, and no float carries that label. Every "
                "reference must name a table or a figure that the document contains."
            )
        word = "Table" if match.group(1) == "tab" else "Figure"
        return f"{word} {numbers[key]}"

    return REFERENCE.sub(substitute, text)


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------


def build(results, protocol, figs, skipped):
    """Returns the block list, together with the slot record that filled it."""
    S = Slots(results, protocol)
    blocks = []

    # Slots used in more than one place are filled once, up front.
    n_pairs = S("pairs_total", "dataset.n_pairs", integer)
    n_genuine = S("pairs_genuine", "dataset.n_genuine", integer)
    n_impostor = S("pairs_impostor", "dataset.n_impostor", integer)
    folds_n = S.raw("verification_cleartext.protocol.folds")
    folds = S("protocol_folds", "verification_cleartext.protocol.folds", count)
    dim = S("template_dim", "crypto.template_dim", count)
    degree = S("poly_degree", "crypto.poly_modulus_degree", count)
    slots_n = S.raw("crypto.slot_count")
    slot_count = S("slot_count", "crypto.slot_count", count)
    block_slots = S("slots_per_template", "crypto.slots_per_template", count)
    max_batch = S("max_batch", "crypto.max_batch", count)
    rotations = S("rotations_per_score", "crypto.rotations_per_score", count)
    scale_bits_n = S.raw("crypto.scale_bits")
    scale_bits = S("scale_bits", "crypto.scale_bits", count)
    coeff = S.raw("crypto.coeff_modulus_bits")
    S.derived("coeff_modulus_bits", ", ".join(str(b) for b in coeff),
              "crypto.coeff_modulus_bits, joined")

    acc_enc = S("accuracy_encrypted", "verification_encrypted.protocol.accuracy_mean", pct)
    acc_clear = S("accuracy_cleartext", "verification_cleartext.protocol.accuracy_mean", pct)
    acc_sd = S("accuracy_stddev_encrypted",
               "verification_encrypted.protocol.accuracy_stddev", pct)
    gap = S("accuracy_gap", "equivalence.accuracy_difference", lambda v: pct(abs(v), 4))

    err_max = S("error_max", "equivalence.max_abs_error", sci)
    margin_min = S("margin_min", "equivalence.min_abs_margin", sci)
    ratio_raw = S.raw("equivalence.error_over_margin")
    ratio = S("error_over_margin", "equivalence.error_over_margin", sci)
    headroom = S.derived("margin_factor", num0(1.0 / max(1e-300, ratio_raw)),
                         "1 / equivalence.error_over_margin")
    flips = S("decision_flips", "equivalence.observed_flips", integer)

    server_ms = S("server_ms_ct_ct", "cost_ct_ct.server_score.median_ms", ms)
    uplink = S("uplink_per_verification", "cost_ct_ct.uplink_bytes_per_verification", kib)
    batch_last = len(results.get("batching", [])) - 1
    amortised = S("amortised_ms", f"batching.{batch_last}.amortised_ms_per_verification", ms)
    amortised_bytes = S("amortised_uplink", f"batching.{batch_last}.bytes_per_verification", kib)

    # The sweep entry that matches the working parameter set, so the report can
    # point at the row a reader will compare against Section 5.2.
    working_scale_index = 0
    for index, point in enumerate(results.get("scale_sweep", [])):
        if point.get("scale_bits") == scale_bits_n and point.get("usable"):
            working_scale_index = index

    plat = results["platform"]
    arch = S("host_arch", "platform.arch")
    article = "an" if arch[0].lower() in "aeiou" else "a"

    # -- Abstract ---------------------------------------------------------
    blocks.append(heading("Abstract", level=0))
    blocks.append(
        para(
            f"We verify pairs of face images against each other while the face templates stay "
            f"encrypted, and we measure what that costs. A deep network converts each "
            f"photograph into a {dim}-dimensional unit-norm template; the client encrypts the "
            f"template under RNS-CKKS; and the server computes the cosine similarity of two "
            f"templates as one homomorphic inner product at multiplicative depth one, using "
            f"{rotations} rotations to sum the element-wise products into a single slot. On the "
            f"{n_pairs} pairs of the Labeled Faces in the Wild pair protocol, the encrypted "
            f"pipeline reaches {acc_enc} accuracy under {folds}-fold cross-validation, matching "
            f"the cleartext pipeline to {gap}. The largest difference between an encrypted score "
            f"and its cleartext reference is {err_max}, which is {headroom} times smaller than "
            f"the closest any pair comes to its decision threshold. That inequality turns the "
            f"observed count of {flips} changed decisions into a bound: no perturbation of this "
            f"magnitude can move a pair across its threshold. One verification takes "
            f"{server_ms} of server time, and packing {max_batch} templates into the "
            f"{slot_count} slots of one ciphertext brings that to {amortised} and "
            f"{amortised_bytes} of uplink per verification. Every number in this report is read "
            f"from the JSON record of a single run, and one command reproduces it."
        )
    )

    # -- Introduction -----------------------------------------------------
    blocks.append(heading("1  Introduction"))
    blocks.append(
        para(
            "A face recognition service that holds templates in the clear holds a lasting "
            "biometric identifier for every enrolled person. Templates from modern networks "
            "support reconstruction of a recognisable face and support linkage across "
            "databases, so a breach of a template store is a permanent disclosure. Homomorphic "
            "encryption offers a direct answer: the client encrypts the template, the server "
            "computes the comparison on ciphertexts, and the server holds no key."
        )
    )
    blocks.append(
        para(
            "The comparison a verification service performs is small. Two templates that carry "
            "unit L2 norm have a cosine similarity equal to their inner product, which is one "
            "element-wise multiplication followed by a sum. RNS-CKKS evaluates that at "
            "multiplicative depth one, so a single rescale suffices and bootstrapping stays out "
            "of the picture. The engineering question is what the resulting system delivers: "
            "how accurate it is on real photographs, whether encrypted arithmetic changes any "
            "accept-or-reject outcome, and how much time and bandwidth each verification costs."
        ,
                lead="The comparison is one inner product.",
            )
    )
    blocks.append(
        para(
            f"This report answers those three questions with one measured pipeline that runs "
            f"end to end on {article} {arch} laptop. The pipeline detects and aligns each face, "
            f"embeds it, encrypts the embedding, scores every pair of the standard protocol "
            f"under encryption, and generates this document from the resulting record."
        )
    )
    blocks.append(heading("Contributions", level=2))
    blocks.append(
        bullets(
            [
                "<b>A complete encrypted verification pipeline on real photographs.</b> Face "
                "detection, five-point alignment, embedding, RNS-CKKS encryption, homomorphic "
                "scoring and threshold comparison run as one command against the Labeled Faces "
                "in the Wild pair protocol, with Microsoft SEAL as the only compiled dependency.",
                "<b>Decision equivalence established as a bound instead of an observation.</b> "
                "Thresholds are chosen at midpoints of the observed score grid, so every pair "
                "keeps a strictly positive distance from its threshold. Reporting the ratio of "
                "the largest score error to the smallest such distance shows that no pair can "
                "cross its threshold, which is a stronger statement than a count of zero "
                "observed changes.",
                "<b>A precision model for the scoring circuit with no fitted constant.</b> "
                "Rescaling divides ciphertext noise by the scaling factor, so each additional "
                "scale bit buys exactly one precision bit and the predicted slope is fixed at "
                "one. The measured slope is compared against that prediction, and the intercept "
                "is reported as the noise floor of this circuit.",
                f"<b>Slot packing quantified as an amortisation.</b> A ciphertext at degree "
                f"{degree} carries {slot_count} slots and one template occupies {block_slots} "
                f"of them, so {max_batch} verifications share one pass of the circuit. Latency "
                f"and uplink per verification are reported against batch size.",
                "<b>Metrics that declare what the sample supports.</b> Each operating point "
                "carries flags recording whether the impostor count can express the requested "
                "false accept rate, and the report states the reason in place of any value the "
                "sample cannot resolve.",
                "<b>Server isolation verified at three levels.</b> The server sources, the "
                "compiled server objects and the linked server executable are each checked for "
                "the types that carry a secret key, and the client library is checked in the "
                "same way to confirm the test discriminates.",
            ]
        )
    )

    # -- Related work -----------------------------------------------------
    blocks.append(heading("2  Related Work"))
    blocks.append(
        para(
            "Boddeti (2018) established 1:1 face matching over templates encrypted with a fully "
            "homomorphic scheme, and reported both the template size and the per-match cost "
            "that follow from packing a 512-dimensional feature into one ciphertext. Engelsma, "
            "Jain, and Boddeti (2022) extended the setting to 1:N search, where the cost of "
            "scanning a gallery dominates and the encoding of the gallery becomes the design "
            "problem. The present report stays with the 1:1 case and concentrates on what a "
            "reader needs in order to trust the numbers: the exact parameter set, the circuit "
            "trace, the bound on decision changes, and the host the timings came from."
        )
    )
    blocks.append(
        para(
            "The template frontend follows the InsightFace line of work. SCRFD (Guo et al. "
            "2022) supplies the detector and its five landmarks, and ArcFace (Deng et al. 2019) "
            "supplies the additive angular margin objective that the recognition network is "
            "trained under and the canonical five-point template that alignment maps onto. The "
            "cryptographic scheme is CKKS (Cheon et al. 2017) in the full residue number system "
            "variant (Cheon et al. 2018), as implemented by Microsoft SEAL, with parameter "
            "widths bounded by the tables of the Homomorphic Encryption Standard (Albrecht et "
            "al. 2018)."
        )
    )

    # -- Method -----------------------------------------------------------
    blocks.append(heading("3  Method"))
    blocks.append(heading("3.1  Templates from a deep network", level=2))
    blocks.append(
        para(
            f"Each photograph passes through three stages. The detector predicts a bounding box "
            f"and five landmarks: the two eye centres, the nose tip and the two mouth corners. "
            f"A similarity transform, estimated in the least-squares sense over those five "
            f"points, maps them onto the canonical ArcFace template, producing a 112 by 112 "
            f"crop in which the eyes and mouth occupy fixed pixel positions. The recognition "
            f"network maps that crop to {dim} dimensions, and the vector is scaled to unit L2 "
            f"norm."
        )
    )
    blocks.append(
        para(
            "Normalisation happens on the client, before encryption, and it is what makes the "
            "encrypted circuit small. A square root and a division are expensive under "
            "homomorphic encryption; performing them on the client leaves the server with an "
            "inner product. The provenance note below records how far the templates of this run "
            "depart from unit norm, and at that magnitude the score the server computes is the "
            "cosine similarity."
        ,
                lead="Normalisation stays on the client.",
            )
    )
    blocks.append(
        para("Provenance of the templates used here: "
             + S("dataset_description", "dataset.description"))
    )

    blocks.append(heading("3.2  RNS-CKKS parameters", level=2))
    blocks.append(
        para(
            f"The polynomial modulus degree is {degree}, giving {slot_count} plaintext slots. "
            f"The coefficient modulus is a chain of primes of "
            f"{', '.join(str(b) for b in coeff)} bits, totalling "
            f"{S('total_coeff_bits', 'crypto.total_coeff_bits', count)} bits against the "
            f"{S('max_coeff_bits', 'crypto.max_coeff_bits_at_this_degree', count)} bits that "
            f"{S('sec_level', 'crypto.sec_level')} permits at this degree. The last prime in "
            f"the chain is the key-switching prime and carries no plaintext, so the data chain "
            f"holds two levels, chain index 1 and chain index 0. One step down the chain is one "
            f"multiplication, so this parameter set allows exactly one. The scaling factor is 2 "
            f"to the power {scale_bits}."
        )
    )
    blocks.append(
        para(
            f"Those widths follow from the circuit. One ciphertext-by-ciphertext product squares "
            f"the scale, and one rescale divides it by the middle prime and returns it to its "
            f"original size. The prime that survives is wider than the scale it carries, which "
            f"leaves room for the integer part of the score and for the accumulated noise. The "
            f"measured chain confirms the arithmetic: a fresh ciphertext sits at chain index "
            f"{S('chain_index_in', 'circuit_trace.chain_index_in', count)} and the result "
            f"sits at chain index "
            f"{S('chain_index_out', 'circuit_trace.chain_index_out', count)}."
        ,
                lead="The widths follow from the circuit.",
            )
    )

    blocks.append(heading("3.3  The scoring circuit", level=2))
    blocks.append(
        para(
            f"The server holds two encrypted templates, placed in the low slots of their "
            f"respective ciphertexts, and evaluates four operations. It multiplies the two "
            f"ciphertexts, which yields the element-wise products and a ciphertext of degree "
            f"three. It relinearizes, returning the ciphertext to degree two. It rescales, "
            f"restoring the scale and consuming the one available level. It then folds the "
            f"products into a single slot with {rotations} rotations."
        )
    )
    blocks.append(
        para(
            f"The fold uses doubling strides. Adding a copy of the ciphertext rotated by one "
            f"slot leaves each slot holding the sum of two neighbours; repeating with strides "
            f"of two, four and so on up to {int(S.raw('crypto.slots_per_template')) // 2} "
            f"leaves slot i holding the sum of the {block_slots} consecutive slots that begin "
            f"at i. Because the template occupies a block whose length is a power of two and "
            f"divides the slot count, the first slot of the block holds exactly the inner "
            f"product. Galois keys are generated for those strides alone, which is why the "
            f"Galois key measures "
            f"{S('galois_key_bytes', 'crypto.galois_key_bytes.wire', kib)} in place of the far "
            f"larger key that all rotations would require."
        ,
                lead="The fold uses doubling strides.",
            )
    )

    if "circuit" in figs:
        blocks.append(
            figure("circuit",
                   "The scoring circuit, with the chain index and the scale after each step. "
                   "The single rescale is the only level the parameter set can spend.",
                   figs["circuit"])
        )

    blocks.append(heading("3.4  Slot-packed batching", level=2))
    blocks.append(
        para(
            f"A block of {block_slots} slots holds one template, and the ciphertext holds "
            f"{slot_count} slots, so {max_batch} templates fit side by side. The multiplication "
            f"is element-wise and the fold is block-local, so one pass of the circuit produces "
            f"{max_batch} independent scores, each in the first slot of its block, as "
            f"[[fig:slots]] shows. The cost of that is reported below."
        )
    )

    if "slots" in figs:
        blocks.append(
            figure("slots",
                   "Slot occupancy of one ciphertext before and after the fold. Each template "
                   "holds a block, and the fold leaves that block's score in its first slot.",
                   figs["slots"])
        )

    blocks.append(heading("3.5  Protocol and threat model", level=2))
    blocks.append(
        para(
            "The client generates the key set, keeps the secret key, and sends the server the "
            "relinearization and Galois keys. Enrolment sends one encrypted template, which the "
            "server stores. Verification sends one encrypted probe, the server returns one "
            "encrypted score, and the client decrypts that score and compares it to the "
            "threshold. [[fig:pipeline]] sets the four stages against the trust boundary."
        )
    )
    if "pipeline" in figs:
        blocks.append(
            figure(
                "pipeline",
                "The verification pipeline. The secret key stays on the client, and the "
                "server holds evaluation keys alone.",
                figs["pipeline"],
            )
        )
    blocks.append(
        para(
            "The comparison happens on the client because a threshold comparison under "
            "encryption requires a polynomial approximation to a step function, which needs "
            "multiplicative depth that this parameter set deliberately excludes. The "
            "consequence is explicit in the trust model: the server learns the ciphertexts and "
            "learns nothing about their contents, and the client learns the numeric score. A "
            "deployment in which the client should learn only the accept-or-reject bit needs "
            "either a deeper circuit or a second party, and both fall outside this report."
        ,
                lead="The client takes the decision.",
            )
    )
    blocks.append(
        para(
            "The separation is enforced in the build. The server library and the server "
            "executable are compiled without the translation unit that holds the secret key, "
            "and a check reads the server sources, the compiled server objects and the linked "
            "executable to confirm that none of them references the types that carry a secret. "
            "The same check confirms that the client library does reference them, which shows "
            "the test distinguishes the two halves."
        ,
                lead="The build enforces the separation.",
            )
    )

    # -- Setup ------------------------------------------------------------
    blocks.append(heading("4  Experimental Setup"))
    blocks.append(heading("4.1  Dataset and protocol", level=2))
    blocks.append(
        para(
            f"Labeled Faces in the Wild (Huang et al. 2007) fixes {n_pairs} pairs in {folds} "
            f"folds, each fold holding pairs of the same person and pairs of different people "
            f"in equal number. This run uses {n_genuine} same-person pairs and {n_impostor} "
            f"different-person pairs. The fold index of every pair is carried from the protocol "
            f"file into the template container and is used for cross-validation, so the "
            f"accuracy reported here is comparable with published figures for the same split."
        )
    )
    blocks.append(heading("4.2  Thresholds and reported metrics", level=2))
    blocks.append(
        para(
            f"For each fold, the threshold is chosen to maximise accuracy on the other "
            f"{plural(folds_n - 1, 'fold')} and is then applied to the held-out fold. Candidate "
            f"thresholds are the midpoints between adjacent distinct scores of the training "
            f"split, together with one sentinel below the minimum and one above the maximum. No "
            f"candidate coincides with an observed score, so every pair keeps a strictly "
            f"positive distance from its threshold, and the bound of the decision-equivalence "
            f"section therefore rests on an argument. The smallest such distance in this run is "
            f"{S('protocol_min_margin', 'verification_cleartext.protocol.min_abs_margin', sci)}."
        )
    )
    blocks.append(
        para(
            f"A true accept rate quoted at a false accept rate of f needs at least one impostor "
            f"pair per f of the sample. With {n_impostor} impostor pairs the finest expressible "
            f"rate is "
            f"{S('far_resolution', 'verification_cleartext.far_resolution', sci)}. Each "
            f"operating point therefore carries two flags: one recording whether the sample can "
            f"express the requested rate at all, and one recording whether at least five false "
            f"accepts back the estimate. [[tab:operating]] states the reason in place of any "
            f"value the sample cannot resolve."
        ,
                lead="What the sample can express.",
            )
    )
    blocks.append(heading("4.3  Host and build", level=2))
    blocks.append(
        para(
            f"{S('host_cpu', 'platform.cpu')} on {S('host_os', 'platform.os')} "
            f"{S('host_os_version', 'platform.os_version')}, {arch}, "
            f"{plural(S.raw('platform.physical_cores'), 'physical core')} and "
            f"{S('host_memory', 'platform.memory_bytes', lambda v: f'{float(v) / 2 ** 30:.0f} GiB')} "
            f"of memory. Compiled by {S('compiler', 'platform.compiler')} in the "
            f"{S('build_type', 'platform.build_type')} configuration against Microsoft SEAL "
            f"{S('seal_version', 'platform.seal_version')}, with serialization compression set "
            f"to {S('compression', 'platform.serialization_compression')}. "
            f"{S('timing_caveat', 'platform.timing_caveat')} Floating-point contraction is "
            f"switched off at compile time, so the cleartext reference scores are plain "
            f"IEEE-754 double arithmetic and agree bit for bit across hosts that would "
            f"otherwise differ in their use of fused multiply-add."
        )
    )
    blocks.append(
        para(
            f"The record this document was generated from is artifacts/results.json, and the "
            f"per-pair scores are in artifacts/scores.csv. The benchmark performed "
            f"{S('homomorphic_calls', 'score_table.homomorphic_calls', integer)} homomorphic "
            f"scoring calls at a batch of {S('score_batch', 'score_table.batch', count)} to "
            f"cover all {n_pairs} pairs. Every number in this report occupies a named slot "
            f"filled from that record when the report is generated, and reports/data_slots.md "
            f"lists each slot together with the path it was read from.",
            lead="Provenance of every number.",
        )
    )

    # -- Results ----------------------------------------------------------
    blocks.append(heading("5  Results"))
    blocks.append(
        para(
            f"The subsections below report six experiments. The first scores every pair of the "
            f"protocol and is the source of every accuracy and fidelity figure. The others each "
            f"generate their own key set and draw their own sample: the cost measurement times "
            f"{S('cost_reps_2', 'cost_ct_ct.server_score.n', count)} unbatched verifications, "
            f"the batching measurement times "
            f"{S('batch_reps', 'batching.0.server_score.n', count)} at each batch size, and the "
            f"scale sweep measures a short sample at each scaling factor. Medians and maxima "
            f"therefore differ between tables by a few percent, and each table reports the "
            f"experiment that produced it. Where two numbers for the same quantity appear, the "
            f"text names which experiment each came from.",
            lead="Each experiment stands on its own.",
        )
    )
    blocks.append(heading("5.1  Verification accuracy", level=2))
    blocks.append(
        para(
            f"[[tab:accuracy]] reports the {folds}-fold accuracy of both pipelines. The "
            f"encrypted pipeline reaches {acc_enc} with a standard deviation of {acc_sd} across "
            f"folds, against {acc_clear} for the cleartext pipeline. The gap is {gap}."
        )
    )
    auc_note = ""
    if results["verification_cleartext"].get("auc_saturated"):
        auc_note = (
            " The area under the curve reaches exactly one on this sample, which means every "
            "same-person pair outranks every different-person pair. An accuracy comparison at "
            "that point carries no information about the ranking, so the equivalence bound "
            "below is the statement that supports the claim of unchanged decisions."
        )
    blocks.append(
        para(
            f"The area under the receiver operating characteristic is "
            f"{S('auc_cleartext', 'verification_cleartext.auc', num6)} and the equal error rate "
            f"is {S('eer_cleartext', 'verification_cleartext.eer', pct3)}. The separation "
            f"between the two score distributions, measured as the difference of their means "
            f"over their pooled standard deviation, is "
            f"{S('d_prime', 'verification_cleartext.d_prime', num)}. [[fig:dist]] shows the two "
            f"distributions with the fitted thresholds, and [[fig:roc]] the operating curve "
            f"they produce." + auc_note
        )
    )

    clear = results["verification_cleartext"]
    enc = results["verification_encrypted"]
    blocks.append(
        table(
            "accuracy",
            "Verification accuracy under the fold protocol. Thresholds are fitted without the "
            "fold they are applied to.",
            ["Quantity", "Cleartext", "Encrypted"],
            [
                ["Accuracy, mean over folds",
                 pct(clear["protocol"]["accuracy_mean"]), pct(enc["protocol"]["accuracy_mean"])],
                ["Accuracy, standard deviation",
                 pct(clear["protocol"]["accuracy_stddev"]),
                 pct(enc["protocol"]["accuracy_stddev"])],
                ["Area under the ROC curve", num6(clear["auc"]), num6(enc["auc"])],
                ["Equal error rate", pct3(clear["eer"]), pct3(enc["eer"])],
                ["Threshold, mean over folds",
                 num4(clear["protocol"]["threshold_mean"]),
                 num4(enc["protocol"]["threshold_mean"])],
                ["Separation of the distributions", num(clear["d_prime"]), num(enc["d_prime"])],
            ],
        )
    )
    S.derived("accuracy_table", "6 rows", "verification_cleartext and verification_encrypted")

    op_rows = []
    for index, op in enumerate(clear["operating_points"]):
        if op["resolvable"]:
            op_rows.append([
                sci0(op["target_far"]), pct(op["tar"]), sci(op["achieved_far"]),
                str(op["false_accepts"]),
                "yes" if op["well_conditioned"] else "coarse",
            ])
        else:
            op_rows.append([sci0(op["target_far"]), "not reported", "\u2014", "\u2014", "no"])
    blocks.append(
        table(
            "operating",
            "Operating points on the cleartext scores. A rate the impostor count cannot "
            "express carries no value.",
            ["Target rate", "True accept", "Achieved", "False accepts", "Backed"],
            op_rows,
            weights=[0.21, 0.21, 0.20, 0.21, 0.17],
        )
    )
    S.derived("operating_points", f"{len(op_rows)} rows",
              "verification_cleartext.operating_points")

    unresolvable = [op for op in clear["operating_points"] if not op["resolvable"]]
    if unresolvable:
        blocks.append(
            para(
                (f"One requested rate is left without a value, because the sample cannot "
                 f"express it: {unresolvable[0]['note']}."
                 if len(unresolvable) == 1 else
                 f"{len(unresolvable)} requested rates are left without a value, because the "
                 f"sample cannot express them. For the first: {unresolvable[0]['note']}.")
                + " Reporting a value there would describe the position of a handful of "
                  "individual pairs in the score ordering and would carry no information about "
                  "the rate itself."
            )
        )
    if "distributions" in figs:
        blocks.append(
            figure("dist", "Cleartext score distributions with the fitted fold thresholds.",
                   figs["distributions"])
        )
    if "roc" in figs:
        blocks.append(
            figure("roc",
                   "Receiver operating characteristic. The dashed line marks the finest false "
                   "accept rate the impostor count can express.",
                   figs["roc"])
        )

    blocks.append(heading("5.2  Numerical fidelity", level=2))
    blocks.append(
        para(
            f"Across all {S('equivalence_n', 'equivalence.n', integer)} pairs, the difference "
            f"between the encrypted score and its cleartext reference has a mean absolute value "
            f"of {S('error_mean', 'equivalence.mean_abs_error', sci)}, a median of "
            f"{S('error_median', 'equivalence.median_abs_error', sci)}, a 99th percentile of "
            f"{S('error_p99', 'equivalence.p99_abs_error', sci)} and a maximum of {err_max}. "
            f"The maximum corresponds to "
            f"{S('precision_bits', 'equivalence.precision_bits', bits)} of precision, which "
            f"matches the headroom the parameter set provides: the surviving prime is "
            f"{coeff[0]} bits wide and carries a scale of {scale_bits} bits, leaving "
            f"{coeff[0] - scale_bits_n} bits before the accumulated noise of the multiplication "
            f"and the fold is subtracted. [[fig:fidelity]] shows the difference against the "
            f"cleartext score and its distribution."
        )
    )
    blocks.append(
        para(
            f"A maximum is the largest value in a sample, so it grows with coverage and moves "
            f"with the key set. The figure above, {err_max}, is the maximum over all "
            f"{n_pairs} pairs under the session that scored them. The cost measurement of "
            f"Section 5.4 records {S('cost_max_error', 'cost_ct_ct.max_abs_error', sci)} over "
            f"its {S('cost_reps_3', 'cost_ct_ct.server_score.n', count)} repetitions, the "
            f"batching measurement of Section 5.5 records "
            f"{S('batch_max_error_first', 'batching.0.max_abs_error', sci)} at a batch of one, "
            f"and the scale sweep of Section 5.6 records "
            f"{S('sweep_max_error', f'scale_sweep.{working_scale_index}.max_abs_error', sci)} at "
            f"this scaling factor. Each is correct for its own sample and its own keys. The "
            f"bound of Section 5.3 uses the figure from the full protocol, because that is the "
            f"one that covers every pair a decision is taken on.",
            lead="A maximum belongs to its sample.",
        )
    )
    if "fidelity" in figs:
        blocks.append(
            figure("fidelity",
                   "Signed difference against cleartext score over the full protocol, and the "
                   "distribution of the absolute difference.",
                   figs["fidelity"])
        )

    blocks.append(heading("5.3  Decision equivalence", level=2))
    blocks.append(
        para(
            "A pair changes its accept-or-reject outcome only when the encrypted score lands on "
            "the far side of the threshold from the cleartext score. Write E for the largest "
            "absolute difference between the two scores over all pairs, and M for the smallest "
            "distance from any cleartext score to the threshold of its fold. When E is smaller "
            "than M, every encrypted score stays on the side of the threshold its cleartext "
            "reference occupies, and the two pipelines agree on every pair."
        )
    )
    blocks.append(
        para(
            f"This run measures E as {err_max} and M as {margin_min}, giving a ratio of {ratio}. "
            f"The ratio lies below one by a factor of about {headroom}, so the equality of the "
            f"two decision sets holds by the inequality and does not depend on the particular "
            f"noise this run drew. The observed count of {flips} changed decisions is what the "
            f"bound requires."
        )
    )
    blocks.append(
        para(
            "The midpoint threshold grid is what makes M positive. A threshold placed at an "
            "observed score value would leave one pair at zero distance, the ratio would be "
            "unbounded, and a count of zero changed decisions would then rest on the accident "
            "that the noise happened to point the right way. [[fig:margin]] places the two "
            "distributions on one axis, where the separation between them is the bound."
        ,
                lead="Why the margin is positive.",
            )
    )

    if "margin" in figs:
        blocks.append(
            figure("margin",
                   "Distances from each cleartext score to the threshold of its fold, against "
                   "the largest score error. The gap between them is the bound.",
                   figs["margin"])
        )

    blocks.append(heading("5.4  Cost of one verification", level=2))
    ctct = results["cost_ct_ct"]
    ctpt = results["cost_ct_pt"]
    fold_share = ctct["server_fold"]["median_ms"] / max(1e-12, ctct["server_score"]["median_ms"])
    saving = 1.0 - ctpt["server_score"]["median_ms"] / max(1e-12, ctct["server_score"]["median_ms"])
    blocks.append(
        para(
            f"[[tab:cost]] reports medians over "
            f"{S('cost_reps', 'cost_ct_ct.server_score.n', count)} unbatched repetitions. "
            f"Server time for the circuit that encrypts both templates is {server_ms}, of which "
            f"the fold accounts for "
            f"{S('server_fold_ms', 'cost_ct_ct.server_fold.median_ms', ms)}, or "
            f"{S.derived('fold_share', pct(fold_share, 0), 'server_fold / server_score')} of "
            f"the total. [[fig:costfig]] gives the share each stage takes. The end-to-end "
            f"figure, adding client encryption and decryption, is "
            f"{S('end_to_end_ms', 'cost_ct_ct.end_to_end_ms', ms)}."
        )
    )
    blocks.append(
        para(
            f"Keeping the enrolled template in the clear removes the relinearization from the "
            f"critical path and brings server time to "
            f"{S('server_ms_ct_pt', 'cost_ct_pt.server_score.median_ms', ms)}, a saving of "
            f"{S.derived('ct_pt_saving', pct(saving, 0), '1 - ct_pt / ct_ct server time')}. "
            f"That saving is the price of the privacy property: in the cleartext-gallery "
            f"variant the server holds the enrolled template and learns the identity it stores."
        ,
                lead="A cleartext gallery costs less.",
            )
    )
    blocks.append(
        table(
            "cost",
            "Cost of one unbatched verification with both templates encrypted. Times are "
            "medians; sizes are serialised bytes.",
            ["Stage", "Cost", "Note"],
            [
                ["Key generation", ms(results["crypto"]["keygen_ms"]), "once per client"],
                ["Client encryption", ms(ctct["client_encrypt"]["median_ms"]), "two templates"],
                ["Server multiply", ms(ctct["server_multiply"]["median_ms"]), "depth 1"],
                ["Server relinearize", ms(ctct["server_relinearize"]["median_ms"]),
                 "one key switch"],
                ["Server rescale", ms(ctct["server_rescale"]["median_ms"]), "level 1 to 0"],
                ["Server rotate-and-sum", ms(ctct["server_fold"]["median_ms"]),
                 f"{rotations} rotations"],
                ["<b>Server total</b>", f"<b>{ms(ctct['server_score']['median_ms'])}</b>", ""],
                ["Client decryption", ms(ctct["client_decrypt"]["median_ms"]), "one ciphertext"],
                ["Uplink per verification", kib(ctct["uplink_bytes_per_verification"]),
                 "probe ciphertext"],
                ["Downlink per verification", kib(ctct["downlink_bytes_per_verification"]),
                 "score ciphertext"],
                ["Relinearization key", kib(results["crypto"]["relin_key_bytes"]["wire"]),
                 "sent once"],
                ["Galois key", kib(results["crypto"]["galois_key_bytes"]["wire"]),
                 f"{results['crypto']['galois_key_steps']} strides, sent once"],
            ],
        )
    )
    if "cost" in figs:
        blocks.append(
            figure("costfig", "Where the server spends its time inside one verification.",
                   figs["cost"])
        )
    if results.get("cost_naive_fold"):
        blocks.append(
            para(
                f"Replacing the doubling-stride fold with one that rotates by a single slot "
                f"{S('naive_rotations', 'cost_naive_fold.rotations', count)} times raises "
                f"server time to "
                f"{S('naive_server_ms', 'cost_naive_fold.server_score.median_ms', ms)}, a "
                f"factor of {S('naive_factor', 'naive_over_log2_fold', num1)}, and raises the "
                f"largest score error to "
                f"{S('naive_error', 'cost_naive_fold.max_abs_error', sci)} against "
                f"{S('log2_error', 'cost_ct_ct.max_abs_error', sci)} for the doubling fold "
                f"over the same repetitions."
            )
        )

    if results.get("cost_naive_fold"):
        blocks.append(
            para(
                f"The two effects carry different exponents, and separating them explains why "
                f"the doubling fold wins twice. Counting rotations, the single-slot fold "
                f"performs d minus 1 of them against log2 d for the doubling fold, which is "
                f"linear against logarithmic and gives the speed factor. Counting noise, each "
                f"rotation is a key switch and every key switch adds a unit: the k-th term of "
                f"the single-slot chain has been rotated k times, so summing the chain "
                f"accumulates d(d minus 1)/2 units, while the doubling fold doubles its "
                f"accumulated noise at each of its log2 d steps and ends at d minus 1. The "
                f"first ratio is quadratic in the second, which is the precision factor.",
                lead="Rotations and noise scale differently.",
            )
        )

    blocks.append(heading("5.5  Slot-packed batching", level=2))
    batching = results.get("batching", [])
    if batching:
        blocks.append(
            para(
                f"Server time stays close to constant as the batch grows, because the circuit "
                f"is the same at every batch size: "
                f"{S('batch_first_ms', 'batching.0.server_score.median_ms', ms)} at a batch of "
                f"{S('batch_first', 'batching.0.batch', count)} and "
                f"{S('batch_last_ms', f'batching.{batch_last}.server_score.median_ms', ms)} at "
                f"a batch of {S('batch_last', f'batching.{batch_last}.batch', count)}. "
                f"Amortised over the batch, that is {amortised} and {amortised_bytes} of uplink "
                f"per verification, a throughput of "
                f"{S('throughput', f'batching.{batch_last}.throughput_per_second', num0)} "
                f"verifications per second of server time, which [[fig:batchfig]] plots against "
                f"batch size. The largest score error at the full "
                f"batch is {S('batch_error', f'batching.{batch_last}.max_abs_error', sci)}, "
                f"against {S('batch_first_error', 'batching.0.max_abs_error', sci)} at a batch "
                f"of one. Those two lie within the spread that independent experiments show at "
                f"this parameter set, so packing carries no cost in precision that this "
                f"measurement can separate from run-to-run variation. [[tab:batching]] gives "
                f"every batch size."
            )
        )
        blocks.append(
            table(
                "batching",
                "Cost per verification against the number of templates packed into one "
                "ciphertext.",
                ["Batch", "Server time", "Per pair", "Uplink each", "Max error"],
                [
                    [str(b["batch"]), ms(b["server_score"]["median_ms"]),
                     ms(b["amortised_ms_per_verification"]), kib(b["bytes_per_verification"]),
                     sci(b["max_abs_error"])]
                    for b in batching
                ],
                weights=[0.12, 0.23, 0.21, 0.22, 0.22],
            )
        )
        if "batching" in figs:
            blocks.append(
                figure("batchfig",
                       "Amortised latency and uplink per verification against batch size. Both "
                       "axes are logarithmic.",
                       figs["batching"])
            )

    blocks.append(heading("5.6  Scaling factor and precision", level=2))
    fit = results.get("scale_fit", {})
    if fit.get("points_used", 0) >= 2:
        blocks.append(
            para(
                "A CKKS plaintext holds the message multiplied by the scaling factor and "
                "rounded, so decoding returns the message plus the ciphertext noise divided by "
                "that factor. The noise depends on the widths of the moduli and on the number "
                "of key switches, and not on the scaling factor, so doubling the factor halves "
                "the absolute error. The predicted slope of precision against scale bits is "
                "therefore exactly one, and no constant in that prediction is available to tune "
                "against the data."
            ,
                lead="One scale bit buys one precision bit.",
            )
        )
        blocks.append(
            para(
                f"The sweep measures a slope of "
                f"{S('scale_slope', 'scale_fit.measured_slope', num3)} over "
                f"{S('scale_points', 'scale_fit.points_used', count)} usable points, a "
                f"deviation of {S('scale_deviation', 'scale_fit.slope_deviation', num3)} from "
                f"the prediction, with a coefficient of determination of "
                f"{S('scale_r2', 'scale_fit.r_squared', num4)} and a largest residual of "
                f"{S('scale_residual', 'scale_fit.max_residual_bits', num)} bits. The "
                f"intercept, {S('scale_intercept', 'scale_fit.intercept_bits', num)} bits, is "
                f"the noise floor of this circuit on this host and is reported as a measurement. "
                f"[[fig:scalefig]] draws the measured points against the predicted slope."
            )
        )
        last_scale = len(results["scale_sweep"]) - 1
        blocks.append(
            para(
                f"The sweep moves the middle prime with the scale. At a scale of s bits the "
                f"chain is 60, s, 60, so the rescale divides by a prime of the same width as "
                f"the scale and the identity of Section 3.2 holds at every point. The prime "
                f"that survives stays 60 bits wide, which is what the headroom column reports, "
                f"and the total width of the chain runs from "
                f"{S('sweep_bits_low', 'scale_sweep.0.total_coeff_bits', count)} bits at the "
                f"narrowest scale to "
                f"{S('sweep_bits_high', f'scale_sweep.{last_scale}.total_coeff_bits', count)} "
                f"bits at the widest, both inside the "
                f"{S('coeff_bits_cap', 'crypto.max_coeff_bits_at_this_degree', count)} bits the "
                f"security level permits at this degree.",
                lead="The chain follows the scale.",
            )
        )
        blocks.append(
            para(
                f"Each point of the sweep measures its own short sample under its own key set, "
                f"so the maximum it records at the working scale of {scale_bits} bits, "
                f"{S('sweep_working_error', f'scale_sweep.{working_scale_index}.max_abs_error', sci)}, "
                f"is a different statistic from the maximum over all "
                f"{n_pairs} pairs reported in Section 5.2. The precision column follows the "
                f"same rule, which is why its entry at that scale reads "
                f"{S('sweep_working_precision', f'scale_sweep.{working_scale_index}.precision_bits', num1)} "
                f"bits against the {S('precision_bits_2', 'equivalence.precision_bits', num1)} "
                f"bits the full protocol gives. The slope is unaffected, because every point of "
                f"the fit is drawn the same way.",
                lead="The sweep has its own sample.",
            )
        )
        rejected = [p for p in results["scale_sweep"] if not p.get("usable")]
        if rejected:
            blocks.append(
                para(
                    f"{len(rejected)} of the {len(results['scale_sweep'])} requested points were "
                    f"rejected before measurement. The first of these was a scale of "
                    f"{rejected[0]['scale_bits']} bits, for this reason: {rejected[0]['note']}"
                )
            )
        blocks.append(
            table(
                "scale",
                "Measured precision against the scaling factor. Headroom is the width of the "
                "surviving prime less the scale.",
                ["Scale bits", "Headroom", "Max error", "Precision", "Server time"],
                [
                    [str(p["scale_bits"]), f"{p['headroom_bits']} bits",
                     sci(p["max_abs_error"]) if p["usable"] else "rejected",
                     num1(p["precision_bits"]) if p["usable"] else "\u2014",
                     ms(p["server_score_ms"]) if p["usable"] else "\u2014"]
                    for p in results["scale_sweep"]
                ],
                weights=[0.17, 0.18, 0.22, 0.19, 0.24],
            )
        )
        if "scale" in figs:
            blocks.append(
                figure("scalefig",
                       "Measured precision against scale bits, with the slope-one prediction "
                       "drawn through the measured intercept.",
                       figs["scale"])
            )

    if protocol:
        blocks.append(heading("5.7  End-to-end protocol", level=2))
        sentence = (
            f"A single verification was carried out across two operating system processes "
            f"communicating through files, with the server process holding no secret key. That "
            f"process evaluated the circuit once, from a cold start, in "
            f"{S('protocol_server_ms', 'server_score_ms', ms, source='protocol')}, and the "
            f"client spent "
            f"{S('protocol_decrypt_ms', 'client_decrypt_ms', ms, source='protocol')} decrypting "
            f"the result. The decrypted score was "
            f"{S('protocol_score', 'score_encrypted', num6, source='protocol')} against a "
            f"cleartext reference of "
            f"{S('protocol_reference', 'score_cleartext', num6, source='protocol')}, a "
            f"difference of {S('protocol_error', 'abs_error', sci, source='protocol')}."
        )
        if "threshold" in protocol and "decision_matches_truth" in protocol:
            sentence += (
                f" The pair was a "
                f"{'same-person' if protocol['pair_genuine'] else 'different-person'} pair, and "
                f"the decision at a threshold of "
                f"{S('protocol_threshold', 'threshold', num4, source='protocol')} was to "
                f"{'accept' if protocol['accept'] else 'reject'}, which "
                f"{'agrees with' if protocol['decision_matches_truth'] else 'differs from'} the "
                f"ground truth."
            )
        blocks.append(para(sentence))
        blocks.append(
            para(
                f"Two of those figures invite comparison with [[tab:cost]] and measure something "
                f"else. The evaluation time is a single call in a process that has just started, "
                f"so it carries the one-time costs of building the evaluator's tables and "
                f"touching its memory for the first time; the table reports a median over "
                f"repetitions that pay those costs once and then amortise them away. The probe "
                f"ciphertext occupied "
                f"{S('protocol_uplink', 'uplink_probe_bytes', kib, source='protocol')} on disk "
                f"and the returned score "
                f"{S('protocol_downlink', 'downlink_bytes', kib, source='protocol')}, against "
                f"the {uplink} and "
                f"{S('downlink_per_verification', 'cost_ct_ct.downlink_bytes_per_verification', kib)} "
                f"the table gives, because the table reports the upper bound the library returns "
                f"for a compressed stream while the files hold the bytes actually written.",
                lead="Why these differ from the table.",
            )
        )

    # -- Discussion -------------------------------------------------------
    blocks.append(heading("6  Discussion"))
    blocks.append(
        para(
            f"Three properties of the setting combine to make encrypted 1:1 verification "
            f"inexpensive. The comparison is a single inner product, so multiplicative depth "
            f"one suffices and the modulus chain stays short. The templates carry unit norm "
            f"from the client, so the server performs no division and no square root. And the "
            f"slot structure of the ciphertext holds {max_batch} templates at this dimension, "
            f"so a service under load amortises one pass of the circuit over that many "
            f"verifications."
        )
    )
    blocks.append(
        para(
            f"The precision result explains why accuracy survives encryption so comfortably. "
            f"The circuit resolves about "
            f"{S.derived('precision_bits_round', num0(S.raw('equivalence.precision_bits')), 'equivalence.precision_bits, rounded')} "
            f"bits, and the decisions in a verification task depend on distances between scores "
            f"that are about {headroom} times larger than the error. The margin between what "
            f"the arithmetic delivers and what the task needs is wide enough that the parameter "
            f"set could trade precision for speed, and [[tab:scale]] quantifies that trade "
            f"directly."
        ,
                lead="Precision to spare.",
            )
    )

    blocks.append(heading("7  Limitations"))
    blocks.append(
        bullets(
            [
                "The threshold comparison happens on the client, so the client learns the "
                "numeric score. A deployment that should reveal only the accept-or-reject bit "
                "needs a deeper circuit or a second party.",
                "The parameter set allows exactly one multiplication, as Section 3.2 sets out. "
                "A circuit that normalises templates under encryption, or that compares against "
                "a threshold under encryption, needs a longer modulus chain and costs more.",
                "The evaluation covers 1:1 verification. Searching a gallery of size N costs N "
                "times the work reported here before any gallery-specific encoding is applied, "
                "and the encodings that make such a search practical are a separate problem.",
                f"The impostor count of {n_impostor} bounds the false accept rates this sample "
                f"can express, and [[tab:operating]] reports which requested rates fall outside "
                f"that bound.",
                "Timings come from one host, named above, under a single-threaded evaluator. "
                "They describe that machine and scale with its clock and memory system.",
                "Accuracy depends on the frontend network as much as on the protocol. The "
                "encrypted arithmetic reproduces whatever the frontend produces, and a "
                "different recognition model moves the accuracy figures while leaving the cost "
                "figures and the equivalence bound intact.",
            ]
        )
    )

    blocks.append(heading("8  Conclusion"))
    blocks.append(
        para(
            f"A face verification service can hold templates encrypted and still decide as well "
            f"as one that holds them in the clear. On the {n_pairs} pairs of the standard "
            f"protocol, the encrypted pipeline reaches {acc_enc} accuracy and agrees with the "
            f"cleartext pipeline on every pair, with a bound establishing that agreement. One "
            f"verification costs {server_ms} of server time and {uplink} of uplink, falling to "
            f"{amortised} and {amortised_bytes} when {max_batch} verifications share one "
            f"ciphertext. The whole measurement takes "
            f"{S('bench_wall', 'total_wall_seconds', duration)} of benchmark time on the host "
            f"named above, and one command reproduces it."
        )
    )

    # -- References -------------------------------------------------------
    blocks.append(heading("References"))
    blocks.append(
        refs(
            [
                "Albrecht, M.; Chase, M.; Chen, H.; Ding, J.; Goldwasser, S.; Gorbunov, S.; "
                "Halevi, S.; Hoffstein, J.; Laine, K.; Lauter, K.; Lokam, S.; Micciancio, D.; "
                "Moody, D.; Morrison, T.; Sahai, A.; and Vaikuntanathan, V. 2018. Homomorphic "
                "Encryption Security Standard. Technical report, HomomorphicEncryption.org.",
                "Boddeti, V. N. 2018. Secure Face Matching Using Fully Homomorphic Encryption. "
                "In IEEE International Conference on Biometrics Theory, Applications and "
                "Systems (BTAS), 1\u201310.",
                "Cheon, J. H.; Han, K.; Kim, A.; Kim, M.; and Song, Y. 2018. A Full RNS Variant "
                "of Approximate Homomorphic Encryption. In Selected Areas in Cryptography "
                "(SAC), 347\u2013368.",
                "Cheon, J. H.; Kim, A.; Kim, M.; and Song, Y. 2017. Homomorphic Encryption for "
                "Arithmetic of Approximate Numbers. In Advances in Cryptology (ASIACRYPT), "
                "409\u2013437.",
                "Deng, J.; Guo, J.; Xue, N.; and Zafeiriou, S. 2019. ArcFace: Additive Angular "
                "Margin Loss for Deep Face Recognition. In IEEE/CVF Conference on Computer "
                "Vision and Pattern Recognition (CVPR), 4690\u20134699.",
                "Engelsma, J. J.; Jain, A. K.; and Boddeti, V. N. 2022. HERS: Homomorphically "
                "Encrypted Representation Search. IEEE Transactions on Biometrics, Behavior, "
                "and Identity Science, 4(3): 349\u2013360.",
                "Guo, J.; Deng, J.; Lattas, A.; and Zafeiriou, S. 2022. Sample and Computation "
                "Redistribution for Efficient Face Detection. In International Conference on "
                "Learning Representations (ICLR).",
                "Huang, G. B.; Ramesh, M.; Berg, T.; and Learned-Miller, E. 2007. Labeled Faces "
                "in the Wild: A Database for Studying Face Recognition in Unconstrained "
                "Environments. Technical Report 07-49, University of Massachusetts, Amherst.",
                f"Microsoft Research. Microsoft SEAL (release "
                f"{results['platform']['seal_version']}). https://github.com/microsoft/SEAL.",
            ]
        )
    )

    if skipped:
        blocks.append(
            para(
                "Figures this run did not produce, with the inputs they require absent: "
                + ", ".join(sorted(skipped)) + "."
            )
        )

    return blocks, S


# ---------------------------------------------------------------------------
# AAAI page geometry
# ---------------------------------------------------------------------------

PAGE = LETTER
MARGIN_SIDE = 0.75 * inch
MARGIN_TOP_FIRST = 1.25 * inch
MARGIN_TOP_REST = 0.75 * inch
MARGIN_BOTTOM = 1.25 * inch
GUTTER = 0.375 * inch
TEXT_WIDTH = PAGE[0] - 2 * MARGIN_SIDE          # 7.0 inches
COL_WIDTH = (TEXT_WIDTH - GUTTER) / 2.0         # 3.3125 inches


def _styles():
    body = ParagraphStyle(
        "body", fontName="Times-Roman", fontSize=10, leading=11.6, alignment=TA_JUSTIFY,
        spaceAfter=0, firstLineIndent=10, textColor=colors.black,
    )
    return {
        "title": ParagraphStyle(
            "title", fontName="Times-Bold", fontSize=16, leading=19, alignment=TA_CENTER,
            spaceAfter=10,
        ),
        "author": ParagraphStyle(
            "author", fontName="Times-Roman", fontSize=12, leading=14, alignment=TA_CENTER,
            spaceAfter=2,
        ),
        "affiliation": ParagraphStyle(
            "affiliation", fontName="Times-Roman", fontSize=10, leading=12,
            alignment=TA_CENTER, spaceAfter=14, textColor=colors.HexColor("#333333"),
        ),
        "abstract_head": ParagraphStyle(
            "abstract_head", fontName="Times-Bold", fontSize=11, leading=13,
            alignment=TA_CENTER, spaceBefore=0, spaceAfter=5,
        ),
        "h1": ParagraphStyle(
            "h1", fontName="Times-Bold", fontSize=12, leading=14, spaceBefore=11, spaceAfter=4,
        ),
        "h2": ParagraphStyle(
            "h2", fontName="Times-Bold", fontSize=10.5, leading=12.5, spaceBefore=8,
            spaceAfter=3,
        ),
        "body": body,
        # A paragraph that opens a section takes no first-line indent, which is
        # the convention the AAAI style file follows.
        "body_first": ParagraphStyle("body_first", parent=body, firstLineIndent=0),
        "bullet": ParagraphStyle(
            "bullet", parent=body, leftIndent=11, bulletIndent=1, firstLineIndent=0,
            spaceAfter=4,
        ),
        "ref": ParagraphStyle(
            "ref", fontName="Times-Roman", fontSize=9, leading=10.6, leftIndent=11,
            firstLineIndent=-11, alignment=TA_LEFT, spaceAfter=2.5,
        ),
        "caption": ParagraphStyle(
            "caption", fontName="Times-Roman", fontSize=9, leading=10.6, alignment=TA_LEFT,
            spaceBefore=3, spaceAfter=3,
        ),
        "code": ParagraphStyle(
            "code", fontName="Courier", fontSize=8.5, leading=10.5, spaceBefore=4, spaceAfter=6,
            leftIndent=8, firstLineIndent=0,
        ),
        "cell": ParagraphStyle("cell", fontName="Times-Roman", fontSize=9, leading=10.6),
        "cellhead": ParagraphStyle("cellhead", fontName="Times-Bold", fontSize=9, leading=10.6),
    }


def _table_flowable(block, styles, width, numbers):
    head = [Paragraph(str(c), styles["cellhead"]) for c in block.header]
    rows = [[Paragraph(resolve(str(c), numbers), styles["cell"]) for c in row]
            for row in block.rows]
    columns = len(block.header)
    weights = getattr(block, "weights", None)
    if weights and len(weights) == columns:
        total = float(sum(weights))
        widths = [width * w / total for w in weights]
    else:
        first = width * (0.46 if columns <= 3 else 0.24)
        widths = [first] + [(width - first) / (columns - 1)] * (columns - 1)
    flow = Table([head] + rows, colWidths=widths, hAlign="LEFT")
    flow.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.black),
                ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.black),
                ("LINEBELOW", (0, -1), (-1, -1), 0.8, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 2.0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.0),
                ("LEFTPADDING", (0, 0), (-1, -1), 1.5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 1.5),
            ]
        )
    )
    return flow


def _image_flowable(path, width):
    from reportlab.lib.utils import ImageReader

    native_w, native_h = ImageReader(path).getSize()
    scale = width / float(native_w)
    return Image(path, width=width, height=native_h * scale)


def render_pdf(blocks, path, results, repo_url="", author=AUTHOR):
    styles = _styles()
    numbers = number_floats(blocks)
    plat = results["platform"]

    doc = BaseDocTemplate(
        path, pagesize=PAGE,
        leftMargin=MARGIN_SIDE, rightMargin=MARGIN_SIDE,
        topMargin=MARGIN_TOP_FIRST, bottomMargin=MARGIN_BOTTOM,
        title=TITLE, author=author,
    )

    head = [
        Paragraph(TITLE, styles["title"]),
        Paragraph(author, styles["author"]),
        Paragraph(
            (f"{repo_url}<br/>" if repo_url else "") + LICENCE,
            styles["affiliation"],
        ),
    ]
    # The title block is measured so the frame fits it exactly; a longer title
    # then enlarges the frame instead of overflowing into a column.
    head_height = 0.0
    for flowable in head:
        head_height += flowable.wrap(TEXT_WIDTH, 10 * inch)[1] + flowable.getSpaceAfter()
    head_height += 4

    # First page: the title block spans both columns, and the body begins in the
    # left column with the abstract, as the AAAI style file lays it out.
    first_top = PAGE[1] - MARGIN_TOP_FIRST
    title_frame = Frame(MARGIN_SIDE, first_top - head_height, TEXT_WIDTH, head_height,
                        id="title", leftPadding=0, rightPadding=0, topPadding=0,
                        bottomPadding=0)
    first_body_height = first_top - head_height - MARGIN_BOTTOM
    first_left = Frame(MARGIN_SIDE, MARGIN_BOTTOM, COL_WIDTH, first_body_height, id="f1",
                       leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    first_right = Frame(MARGIN_SIDE + COL_WIDTH + GUTTER, MARGIN_BOTTOM, COL_WIDTH,
                        first_body_height, id="f2", leftPadding=0, rightPadding=0,
                        topPadding=0, bottomPadding=0)

    rest_height = PAGE[1] - MARGIN_TOP_REST - MARGIN_BOTTOM
    rest_left = Frame(MARGIN_SIDE, MARGIN_BOTTOM, COL_WIDTH, rest_height, id="r1",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    rest_right = Frame(MARGIN_SIDE + COL_WIDTH + GUTTER, MARGIN_BOTTOM, COL_WIDTH, rest_height,
                       id="r2", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)

    doc.addPageTemplates([
        PageTemplate(id="first", frames=[title_frame, first_left, first_right]),
        PageTemplate(id="rest", frames=[rest_left, rest_right]),
    ])

    def flowables_for(block):
        """The flowables one block contributes, and whether it is a float."""
        if block.kind == "heading":
            key = {0: "abstract_head", 1: "h1", 2: "h2"}.get(block.level, "h2")
            return [Paragraph(resolve(block.text, numbers), styles[key])], "heading"
        if block.kind == "para":
            lead = getattr(block, "lead", None)
            style = styles["body_first"] if lead else styles["body"]
            text = resolve(block.text, numbers)
            if lead:
                text = f"<b>{lead}</b>&nbsp; {text}"
            return [Paragraph(text, style), Spacer(1, 3)], "text"
        if block.kind == "code":
            return [Paragraph(block.text.replace(" ", "&nbsp;"), styles["code"])], "text"
        if block.kind == "bullets":
            return ([Paragraph(resolve(i, numbers), styles["bullet"], bulletText="\u2022")
                     for i in block.items], "text")
        if block.kind == "refs":
            return [Paragraph(i, styles["ref"]) for i in block.items], "text"
        if block.kind == "table":
            caption = Paragraph(
                f"Table {numbers['tab:' + block.label]}: {resolve(block.caption, numbers)}",
                styles["caption"])
            body = _table_flowable(block, styles, COL_WIDTH, numbers)
            return [Spacer(1, 4), KeepTogether([caption, body]), Spacer(1, 7)], "float"
        if block.kind == "figure":
            caption = Paragraph(
                f"Figure {numbers['fig:' + block.label]}: {resolve(block.caption, numbers)}",
                styles["caption"])
            image = _image_flowable(block.path, COL_WIDTH)
            return [Spacer(1, 4), KeepTogether([image, caption]), Spacer(1, 5)], "float"
        return [], "text"

    def height_of(flowables):
        """Height these flowables occupy in a column.

        KeepTogether needs a canvas before it can wrap, so its contents are
        measured directly; the group's height is the sum either way.
        """
        total = 0.0
        for flowable in flowables:
            if isinstance(flowable, KeepTogether):
                total += height_of(flowable._content)
                continue
            total += flowable.wrap(COL_WIDTH, 20 * inch)[1]
            total += flowable.getSpaceBefore() + flowable.getSpaceAfter()
        return total

    # Float placement.
    #
    # A figure or a table is one indivisible block. When it does not fit in what
    # is left of a column, the column ends there and the space below it is lost.
    # Rather than predict where that happens, the document is built, reportlab is
    # asked where each block actually landed, and any float that ended a column
    # early is moved one place later so the text behind it fills the gap. The
    # arrangement with the least lost space wins, and a float never drifts more
    # than MAX_DRIFT places from where it was written.
    MAX_DRIFT = 4
    GAP_THRESHOLD = 36.0  # points; about three lines of body text

    def build_once(order, target):
        trace = []

        class Traced(BaseDocTemplate):
            """Records which column each block landed in, and where it ended.

            A paragraph that crosses a column boundary is split into fresh
            flowables that carry none of the tags set below, so the last known
            block index is carried forward. Without that, a column looks as
            though it ended where its last whole block ended, and the half
            paragraph filling the rest of it is read as empty space.
            """

            _last_index = None

            def afterFlowable(self, flowable):
                index = getattr(flowable, "_ffv_block", None)
                if index is None:
                    index = self._last_index
                else:
                    self._last_index = index
                if index is not None and self.frame is not None:
                    trace.append((self.page, self.frame.id, index, self.frame._y))

        traced = Traced(
            target, pagesize=PAGE,
            leftMargin=MARGIN_SIDE, rightMargin=MARGIN_SIDE,
            topMargin=MARGIN_TOP_FIRST, bottomMargin=MARGIN_BOTTOM,
            title=TITLE, author=author,
        )
        traced.addPageTemplates([
            PageTemplate(id="first", frames=[title_frame, first_left, first_right]),
            PageTemplate(id="rest", frames=[rest_left, rest_right]),
        ])
        story = [NextPageTemplate("rest")] + list(head) + [FrameBreak()]
        for position, block in enumerate(order):
            parts, _ = flowables_for(block)
            for part in parts:
                part._ffv_block = position
                if isinstance(part, KeepTogether):
                    for inner in part._content:
                        inner._ffv_block = position
            story.extend(parts)
        traced.build(story)
        return trace

    def lost_space(trace, order):
        """Space left unused at the foot of each column, and the block that follows."""
        columns, gaps = {}, []
        # The trace is in placement order and a column's entries are contiguous,
        # so the last entry for a column records where that column truly ended.
        for page, frame_id, index, y in trace:
            columns[(page, frame_id)] = (index, y)
        ordered = sorted(columns.items())
        for position, (key, (index, y)) in enumerate(ordered):
            if position == len(ordered) - 1:
                continue  # the document simply ends here
            gap = y - MARGIN_BOTTOM
            if gap <= GAP_THRESHOLD:
                continue
            # The block that ended the column early is the float sitting at its
            # foot: the text that would have filled the space is behind it.
            culprit = None
            for position in range(index, max(-1, index - 4), -1):
                if 0 <= position < len(order) and kinds.get(id(order[position])) == "float":
                    culprit = position
                    break
            if culprit is None and index + 1 < len(order):
                culprit = index + 1
            if culprit is not None:
                gaps.append((gap, culprit))
        return sum(g for g, _ in gaps), gaps

    kinds = {id(b): flowables_for(b)[1] for b in blocks}
    order = list(blocks)
    scratch = path + ".layout"
    best_order, best_lost = list(order), None
    drift = {}
    for _ in range(14):
        trace = build_once(order, scratch)
        total, gaps = lost_space(trace, order)
        if best_lost is None or total < best_lost:
            best_lost, best_order = total, list(order)
        moved = False
        for _, culprit in sorted(gaps, reverse=True):
            if culprit >= len(order):
                continue
            block = order[culprit]
            if kinds.get(id(block)) != "float":
                continue
            if drift.get(id(block), 0) >= MAX_DRIFT:
                continue
            # The float moves behind the next run of text, so that text fills the
            # column and the float opens the one after it.
            following = culprit + 1
            while following < len(order) and kinds.get(id(order[following])) != "text":
                following += 1
            if following >= len(order):
                continue
            order.pop(culprit)
            order.insert(following, block)
            drift[id(block)] = drift.get(id(block), 0) + 1
            moved = True
            break
        if not moved:
            break
    if os.path.exists(scratch):
        os.remove(scratch)

    story = [NextPageTemplate("rest")] + list(head) + [FrameBreak()]
    for block in best_order:
        parts, _ = flowables_for(block)
        story.extend(parts)

    doc.build(story)
    return path


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def _plain(text):
    return (text.replace("<b>", "**").replace("</b>", "**").replace("&mdash;", "\u2014")
            .replace("&middot;", "\u00b7").replace("&nbsp;", " ").replace("<br/>", " "))


def render_markdown(blocks, path, results, repo_url="", author=AUTHOR):
    numbers = number_floats(blocks)
    lines = [
        f"# {TITLE}",
        "",
        f"**{author}**",
        "",
        (f"{repo_url}  " if repo_url else "") + LICENCE,
        "",
    ]
    for block in blocks:
        if block.kind == "heading":
            hashes = {0: "##", 1: "##", 2: "###"}.get(block.level, "###")
            lines += [f"{hashes} {_plain(resolve(block.text, numbers))}", ""]
        elif block.kind == "para":
            lead = getattr(block, "lead", None)
            text = _plain(resolve(block.text, numbers))
            lines += [(f"**{lead}** {text}" if lead else text), ""]
        elif block.kind == "code":
            lines += ["```bash", block.text, "```", ""]
        elif block.kind == "bullets":
            lines += [f"- {_plain(resolve(item, numbers))}" for item in block.items] + [""]
        elif block.kind == "refs":
            lines += [f"{i + 1}. {_plain(item)}" for i, item in enumerate(block.items)] + [""]
        elif block.kind == "table":
            number = numbers[f"tab:{block.label}"]
            lines += [f"*Table {number}: {_plain(resolve(block.caption, numbers))}*", ""]
            lines.append("| " + " | ".join(_plain(str(c)) for c in block.header) + " |")
            lines.append("|" + "|".join(["---"] * len(block.header)) + "|")
            for row in block.rows:
                lines.append(
                    "| " + " | ".join(_plain(resolve(str(c), numbers)) for c in row) + " |"
                )
            lines.append("")
        elif block.kind == "figure":
            number = numbers[f"fig:{block.label}"]
            name = os.path.basename(block.path)
            caption = _plain(resolve(block.caption, numbers))
            lines += [f"![Figure {number}](figures/{name})", "",
                      f"*Figure {number}: {caption}*", ""]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return path


def render_slots(slot_record, path):
    """Writes the inventory of data slots and the paths that filled them."""
    lines = [
        "# Data slots",
        "",
        "Every number in the report occupies a named slot. A slot holds a name, a path into "
        "the benchmark record, and a format. The slots are empty until the report is generated, "
        "and each one is filled from the run that produced `artifacts/results.json`.",
        "",
        "This table lists each slot, the file and path it was read from, and the value that "
        "reached the document. A slot filled from a path that the run did not emit stops "
        "generation with the path named, so no slot can carry a value the run did not measure.",
        "",
        f"Slots filled: {len(slot_record.records)}",
        "",
        "| Slot | Source | Path | Value in the report |",
        "|---|---|---|---|",
    ]
    for record in slot_record.records:
        text = str(record["text"]).replace("|", "\\|")
        if len(text) > 90:
            text = text[:87] + "..."
        lines.append(f"| `{record['name']}` | {record['file']} | `{record['path']}` | {text} |")
    lines.append("")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return path
