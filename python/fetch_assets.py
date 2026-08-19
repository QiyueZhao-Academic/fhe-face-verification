#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Acquires the LFW images, the pair protocol and a face model pack.

The canonical host for LFW, vis-www.cs.umass.edu, is unreachable from a growing
number of networks: torchvision now ships the dataset with automatic download
disabled for that reason. This module therefore treats acquisition as a search
over sources, and it verifies whatever it finds.

  1. Local sources come first. An LFW image tree or archive already on the
     machine is used where one exists, opened read-only.
  2. Remote mirrors are tried in order, each over three transports: urllib,
     curl, and curl aimed at an address resolved through DNS-over-HTTPS. The
     third transport succeeds when the machine's own resolver is what failed.
  3. Everything is verified. The published MD5 of each official file is checked
     when the file is one of them, and every image tree is checked structurally.

Nothing is written outside the cache directory.

    python3 python/fetch_assets.py --cache ~/FHE/ffv-cache --model-pack buffalo_l
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

# Published MD5 digests of the official files, as recorded by torchvision. Any
# mirror serving one of them can be verified byte for byte.
OFFICIAL_MD5 = {
    "lfw-deepfunneled.tgz": "68331da3eb755a505a502b5aacb3c201",
    "lfw-funneled.tgz": "1b42dfed7d15c9b2dd63d5e5840c86ad",
    "lfw.tgz": "a17d05bd522c52d84eca14327a23d494",
    "pairs.txt": "9f1ba174e4e1c508ff7cdf10ac338a7d",
}

# Sources for the pair protocol. The GitHub copy is byte-identical to the
# official file, which the MD5 check confirms on every run.
PAIRS_SOURCES = [
    "https://vis-www.cs.umass.edu/lfw/pairs.txt",
    "https://raw.githubusercontent.com/davidsandberg/facenet/master/data/pairs.txt",
    "http://vis-www.cs.umass.edu/lfw/pairs.txt",
    "https://ndownloader.figshare.com/files/5976006",
]

# Sources for the images. The first two are the official deep-funnelled archive.
# The third is the funnelled archive that scikit-learn distributes, which this
# pipeline handles equally well because it runs its own detector and aligner.
# The fourth is the Internet Archive mirror, which serves a zip.
IMAGE_SOURCES = [
    ("lfw-deepfunneled.tgz", "https://vis-www.cs.umass.edu/lfw/lfw-deepfunneled.tgz"),
    ("lfw-deepfunneled.tgz", "http://vis-www.cs.umass.edu/lfw/lfw-deepfunneled.tgz"),
    ("lfw-funneled.tgz", "https://ndownloader.figshare.com/files/5976015"),
    ("lfw-deepfunneled.zip", "https://archive.org/download/lfw-dataset/lfw-deepfunneled.zip"),
]

MODEL_PACKS = {
    # SCRFD-10G detector with a ResNet50 recogniser: the accurate default.
    "buffalo_l": "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip",
    # SCRFD-500M detector with a MobileFaceNet recogniser: roughly six times
    # faster over the whole dataset, at a small cost in accuracy.
    "buffalo_s": "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_s.zip",
}


def local_search_paths(cache, extra):
    """Directories searched for an LFW copy already on the machine.

    Each is opened read-only, and a hit avoids a download of about 110 MB.
    """
    home = os.path.expanduser("~")
    paths = [os.path.join(cache, "lfw")]
    paths += [os.path.abspath(os.path.expanduser(p)) for p in extra if p]
    paths += [
        os.path.join(home, "FHE"),
        os.path.join(home, "Crypto"),
        os.path.join(home, "Downloads"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Desktop"),
        os.path.join(home, "Datasets"),
        os.path.join(home, "data"),
    ]
    seen, out = set(), []
    for path in paths:
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


# ---------------------------------------------------------------------------
# Reporting and hashing
# ---------------------------------------------------------------------------


def human(size):
    size = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


def say(text):
    print(f"  {text}", flush=True)


def detail(text):
    """Prints one indented line, collapsing any embedded newlines."""
    flat = " ".join(str(text).split())
    print(f"      {flat}", flush=True)


def _digest(path, algorithm):
    digest = algorithm()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md5_of(path):
    return _digest(path, hashlib.md5)


def sha256_of(path):
    return _digest(path, hashlib.sha256)


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------


def resolve_via_doh(host):
    """Resolves a hostname through DNS-over-HTTPS.

    This is the escape hatch for a machine whose own resolver fails on one name
    while reaching the rest of the internet normally, which is what happens with
    the LFW host on some networks.
    """
    endpoints = [
        "https://cloudflare-dns.com/dns-query?name={}&type=A",
        "https://dns.google/resolve?name={}&type=A",
    ]
    for template in endpoints:
        try:
            request = urllib.request.Request(
                template.format(host), headers={"Accept": "application/dns-json"}
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            for answer in payload.get("Answer", []):
                if answer.get("type") == 1:  # an A record holds an IPv4 address
                    return answer["data"]
        except Exception:
            continue
    return None


def _urllib_fetch(url, partial):
    with urllib.request.urlopen(url, timeout=120) as response, open(partial, "wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)
            done += len(chunk)
            if total:
                sys.stdout.write(f"\r        {human(done)} / {human(total)}")
                sys.stdout.flush()
        if total:
            sys.stdout.write("\n")


def _curl_fetch(url, partial, resolve=None):
    if not shutil.which("curl"):
        raise RuntimeError("curl is unavailable")
    command = [
        "curl", "--fail", "--location", "--silent", "--show-error",
        "--connect-timeout", "20", "--max-time", "1800",
        # One retry covers a dropped transfer. A name that does not resolve will
        # not resolve on a second attempt either, and the next mirror is tried
        # instead of waiting here.
        "--retry", "1", "--retry-delay", "1",
        "--output", partial, url,
    ]
    if resolve:
        command[1:1] = ["--resolve", resolve]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        # curl repeats its message once per attempt. The distinct lines are joined
        # so the caller logs one indented line instead of several unindented ones.
        lines = []
        for line in (result.stderr or "").splitlines():
            line = line.strip()
            if line and line not in lines:
                lines.append(line)
        raise RuntimeError("; ".join(lines) or f"curl exited {result.returncode}")


def download(url, destination, label, expect_md5=None):
    """Fetches one URL over three transports. Returns True when it succeeds."""
    if os.path.isfile(destination) and os.path.getsize(destination) > 0:
        if expect_md5 and md5_of(destination) != expect_md5:
            detail("the cached copy fails its checksum and is discarded")
            os.remove(destination)
        else:
            say(f"{label}: already present ({human(os.path.getsize(destination))})")
            return True

    os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
    partial = destination + ".part"
    host = url.split("/")[2].split("@")[-1].split(":")[0]
    port = "443" if url.startswith("https") else "80"

    got_file = False
    for name, action in (("urllib", lambda: _urllib_fetch(url, partial)),
                         ("curl", lambda: _curl_fetch(url, partial))):
        try:
            detail(f"{name}: {url}")
            action()
            if os.path.getsize(partial) == 0:
                raise RuntimeError("the server returned an empty body")
            got_file = True
            break
        except Exception as error:
            if os.path.exists(partial):
                os.remove(partial)
            detail(f"{name} failed: {error}")

    if not got_file:
        # Both transports used the machine's resolver. Resolve the name through
        # DNS-over-HTTPS and aim curl at the address directly.
        address = resolve_via_doh(host)
        if not address:
            return False
        detail(f"resolved {host} to {address} over DNS-over-HTTPS")
        try:
            _curl_fetch(url, partial, resolve=f"{host}:{port}:{address}")
            if os.path.getsize(partial) == 0:
                raise RuntimeError("the server returned an empty body")
        except Exception as error:
            if os.path.exists(partial):
                os.remove(partial)
            detail(f"curl with a resolved address failed: {error}")
            return False

    if expect_md5:
        got = md5_of(partial)
        if got != expect_md5:
            os.remove(partial)
            detail(f"checksum mismatch: expected {expect_md5}, received {got}")
            return False
        detail("checksum verified against the published digest")
    os.replace(partial, destination)
    say(f"{label}: {human(os.path.getsize(destination))}")
    return True


# ---------------------------------------------------------------------------
# LFW image trees
# ---------------------------------------------------------------------------


def inspect_tree(root, cap=0):
    """Counts identity directories and images in a candidate LFW tree."""
    if not os.path.isdir(root):
        return 0, 0
    identities = images = 0
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return 0, 0
    for entry in entries:
        person = os.path.join(root, entry)
        if not os.path.isdir(person):
            continue
        try:
            files = [f for f in os.listdir(person) if f.lower().endswith(".jpg")]
        except OSError:
            continue
        # An LFW identity directory holds files prefixed with its own name.
        if files and any(f.startswith(entry + "_") for f in files):
            identities += 1
            images += len(files)
            if cap and identities >= cap:
                break
    return identities, images


def find_tree_under(directory, depth=2, min_identities=20):
    """Looks for an LFW image tree at or below `directory`.

    `min_identities` is the evidence required before a directory is called an LFW
    tree. Scanning uses a high bar so an unrelated photo folder is passed over;
    an explicit --lfw-root uses a low one, because the caller has asserted it.
    """
    if not os.path.isdir(directory):
        return None
    identities, _ = inspect_tree(directory, cap=max(min_identities, 5))
    if identities >= min_identities:
        return directory
    if depth <= 0:
        return None
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return None
    for entry in entries:
        if entry.startswith("."):
            continue
        child = os.path.join(directory, entry)
        if not os.path.isdir(child):
            continue
        # At the outermost level only names that plausibly hold the dataset are
        # descended into, which keeps the scan bounded on a large home directory.
        if depth == 1 and "lfw" not in entry.lower():
            continue
        found = find_tree_under(child, depth - 1, min_identities)
        if found:
            return found
    return None


def find_local_archive(directory, depth=1):
    """Looks for an LFW archive in `directory` or one level below it.

    One level of descent covers an archive left inside a subdirectory of a
    searched location, which is where a browser download often ends up.
    """
    if not os.path.isdir(directory):
        return None
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return None
    for entry in entries:
        lowered = entry.lower()
        if not lowered.startswith("lfw") or lowered.endswith(".part"):
            continue
        if lowered.endswith((".tgz", ".tar.gz", ".zip")):
            path = os.path.join(directory, entry)
            # A megabyte excludes stray small files while accepting any real
            # archive. What the file actually contains is verified after
            # extraction, so this threshold only ranks candidates.
            if os.path.isfile(path) and os.path.getsize(path) > 1 << 20:
                return path
    if depth > 0:
        for entry in entries:
            if entry.startswith("."):
                continue
            child = os.path.join(directory, entry)
            if os.path.isdir(child):
                found = find_local_archive(child, depth - 1)
                if found:
                    return found
    return None


def extract_archive(archive, into):
    """Extracts a tar or zip archive and returns the image tree inside it."""
    os.makedirs(into, exist_ok=True)
    if archive.lower().endswith(".zip"):
        with zipfile.ZipFile(archive) as handle:
            handle.extractall(into)
    else:
        with tarfile.open(archive, "r:*") as handle:
            handle.extractall(into)
    found = find_tree_under(into, depth=3)
    if not found:
        raise SystemExit(
            f"{archive} extracted into {into} without producing a directory of identity "
            "subdirectories. Extract it by hand and pass the result with --lfw-root."
        )
    return found


def acquire_images(cache, explicit_root, search_paths, allow_download):
    """Returns (image_root, provenance), or exits with instructions."""
    if explicit_root:
        root = os.path.abspath(os.path.expanduser(explicit_root))
        # The caller named this path, so a handful of identities is enough.
        found = find_tree_under(root, depth=2, min_identities=3)
        if not found:
            raise SystemExit(
                f"--lfw-root {root} holds no directory of identity subdirectories. The tree "
                "should contain one directory per person, each holding files named like "
                "Person_Name_0001.jpg."
            )
        identities, images = inspect_tree(found)
        say(f"images: {identities} identities, {images} files at {found} (read-only)")
        return found, "a local LFW image tree given on the command line"

    # 1. An extracted tree already on the machine.
    for directory in search_paths:
        found = find_tree_under(directory, depth=2)
        if found:
            identities, images = inspect_tree(found)
            if identities >= 100:
                say(f"images: found {identities} identities, {images} files at {found}")
                detail("this tree is opened read-only and is left unchanged")
                return found, "a local LFW image tree already on the machine"

    # 2. An archive already on the machine.
    for directory in search_paths:
        archive = find_local_archive(directory)
        if archive:
            say(f"images: extracting the local archive {archive}")
            name = os.path.basename(archive)
            if name in OFFICIAL_MD5:
                got = md5_of(archive)
                if got == OFFICIAL_MD5[name]:
                    detail("checksum matches the published digest")
                else:
                    detail(f"checksum differs from the published digest ({got})")
            root = extract_archive(archive, os.path.join(cache, "lfw"))
            identities, images = inspect_tree(root)
            say(f"images: {identities} identities, {images} files at {root}")
            return root, "a local LFW archive extracted into the cache"

    if not allow_download:
        raise SystemExit(
            "no local LFW copy was found and downloading is switched off. Pass --lfw-root "
            "with the path to an LFW image tree."
        )

    # 3. Remote mirrors.
    for name, url in IMAGE_SOURCES:
        say(f"images: trying {url.split('/')[2]}")
        target = os.path.join(cache, "lfw", name)
        if download(url, target, f"images ({name})", OFFICIAL_MD5.get(name)):
            root = extract_archive(target, os.path.join(cache, "lfw"))
            identities, images = inspect_tree(root)
            say(f"images: {identities} identities, {images} files at {root}")
            return root, f"the official archive downloaded from {url.split('/')[2]}"

    raise SystemExit(manual_instructions(cache))


def manual_instructions(cache):
    target = os.path.join(cache, "lfw")
    return "\n".join([
        "",
        "Every source for the LFW images was unreachable from this machine.",
        "",
        "The canonical host, vis-www.cs.umass.edu, fails to resolve on some networks, and",
        "torchvision disabled its own automatic download of this dataset for that reason.",
        "One manual step fixes it permanently.",
        "",
        "Download either archive in a browser:",
        "",
        "    https://vis-www.cs.umass.edu/lfw/lfw-deepfunneled.tgz",
        "    https://archive.org/details/lfw-dataset          (file lfw-deepfunneled.zip)",
        "",
        "Leaving it in ~/Downloads is enough, because that directory is searched. To be",
        "explicit instead:",
        "",
        f"    mkdir -p {target}",
        f"    mv ~/Downloads/lfw-deepfunneled.* {target}/",
        "    bash run.sh --only assets",
        "",
        "An already-extracted tree works too:",
        "",
        "    bash run.sh --lfw-root /path/to/lfw-deepfunneled",
        "",
    ])


def acquire_pairs(cache):
    target = os.path.join(cache, "lfw", "pairs.txt")
    expect = OFFICIAL_MD5["pairs.txt"]
    if os.path.isfile(target) and md5_of(target) == expect:
        say("protocol: pairs.txt already present, checksum verified")
        return target
    for url in PAIRS_SOURCES:
        if download(url, target, "protocol (pairs.txt)", expect):
            return target
    # A verified copy sitting in one of the search directories is the last resort.
    for directory in local_search_paths(cache, []):
        candidate = os.path.join(directory, "pairs.txt")
        if os.path.isfile(candidate) and md5_of(candidate) == expect:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(candidate, target)
            say(f"protocol: copied a verified pairs.txt from {candidate}")
            return target
    raise SystemExit(
        "pairs.txt could not be obtained from any source. Download it from\n"
        "    https://vis-www.cs.umass.edu/lfw/pairs.txt\n"
        f"and place it at {target}"
    )


def acquire_model_pack(cache, name):
    if name not in MODEL_PACKS:
        raise SystemExit(f"unknown model pack '{name}'; choose from {', '.join(MODEL_PACKS)}")
    target = os.path.join(cache, "models", name)
    have = os.path.isdir(target) and [f for f in os.listdir(target) if f.endswith(".onnx")]
    if not have:
        archive = os.path.join(cache, "models", f"{name}.zip")
        if not download(MODEL_PACKS[name], archive, f"models ({name})"):
            raise SystemExit(
                f"the model pack {name} could not be downloaded from\n"
                f"    {MODEL_PACKS[name]}\n"
                f"Download it in a browser, place it at {archive}, and run the stage again."
            )
        say(f"models: extracting {name}")
        with zipfile.ZipFile(archive) as handle:
            handle.extractall(target)
        # Some packs nest the models one directory deeper.
        if not any(f.endswith(".onnx") for f in os.listdir(target)):
            for entry in list(os.listdir(target)):
                nested = os.path.join(target, entry)
                if os.path.isdir(nested):
                    for item in os.listdir(nested):
                        shutil.move(os.path.join(nested, item), os.path.join(target, item))

    kept = [f for f in sorted(os.listdir(target)) if f.endswith(".onnx")]
    if not any(f.startswith("det_") for f in kept) or not any(
        f.startswith("w600k_") for f in kept
    ):
        raise SystemExit(
            f"{target} holds {', '.join(kept) or 'no ONNX file'}, and this pipeline needs a "
            "det_*.onnx detector together with a w600k_*.onnx recogniser. Delete the directory "
            "and run the stage again to fetch the pack afresh."
        )
    say(f"models: {name} ready ({', '.join(kept)})")
    return target


# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", required=True, help="directory that holds every download")
    parser.add_argument("--model-pack", default="buffalo_l", choices=sorted(MODEL_PACKS))
    parser.add_argument("--lfw-root", default="",
                        help="use this LFW image tree, opened read-only")
    parser.add_argument("--search", action="append", default=[],
                        help="an extra directory to search for a local LFW copy; repeatable")
    parser.add_argument("--no-download", action="store_true", help="use local sources alone")
    parser.add_argument("--skip-images", action="store_true",
                        help="fetch the protocol and the model pack alone")
    parser.add_argument("--print-manifest", action="store_true")
    args = parser.parse_args()

    cache = os.path.abspath(os.path.expanduser(args.cache))
    os.makedirs(cache, exist_ok=True)
    print(f"cache: {cache}")

    pairs = acquire_pairs(cache)

    images, provenance = "", "images were not requested"
    if not args.skip_images:
        images, provenance = acquire_images(
            cache,
            args.lfw_root,
            local_search_paths(cache, args.search),
            allow_download=not args.no_download,
        )

    models = acquire_model_pack(cache, args.model_pack)

    manifest = os.path.join(cache, "manifest.txt")
    with open(manifest, "w", encoding="utf-8") as handle:
        handle.write(f"pairs {pairs}\n")
        handle.write(f"images {images}\n")
        handle.write(f"models {models}\n")
        handle.write(f"model_pack {args.model_pack}\n")
        handle.write(f"images_provenance {provenance}\n")
        if images:
            identities, count = inspect_tree(images)
            handle.write(f"images_identities {identities}\n")
            handle.write(f"images_files {count}\n")
        handle.write(f"pairs_md5 {md5_of(pairs)}\n")
        for name in sorted(os.listdir(models)):
            if name.endswith(".onnx"):
                handle.write(f"sha256 {name} {sha256_of(os.path.join(models, name))}\n")
    print(f"manifest: {manifest}")
    if args.print_manifest:
        print(open(manifest, encoding="utf-8").read(), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
