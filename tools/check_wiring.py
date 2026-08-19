#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Checks the contracts that join one file of this project to another.

The pipeline crosses three language boundaries: Python writes a binary container
that C++ reads, C++ writes JSON and CSV that Python reads, and a shell script
drives all of it through command-line flags. A rename on one side of any of those
boundaries compiles and runs and then fails at the worst moment. This script
reads the sources and verifies that both sides still agree.

It uses the standard library alone and needs no build, so it runs before anything
is compiled or downloaded.

    python3 tools/check_wiring.py            # from the project root
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILURES = []
CHECKS = 0


def read(*parts):
    path = os.path.join(ROOT, *parts)
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def strip_comments(text):
    """Removes // and /* */ comments so prose does not count as code."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def group(name):
    print(f"\n[{name}]")


def check(condition, what, detail=""):
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"  pass  {what}" + (f"  ({detail})" if detail else ""))
    else:
        FAILURES.append(what)
        print(f"  FAIL  {what}" + (f"  ({detail})" if detail else ""))


# ---------------------------------------------------------------------------
# 1. The .ffvemb container: Python writes it, C++ reads it
# ---------------------------------------------------------------------------


def check_container():
    group("template container, python writer against C++ reader")
    py = read("python", "ffv", "lfw.py")
    cpp = read("src", "core", "templates.cpp")
    hpp = read("include", "ffv", "templates.hpp")

    py_magic = re.search(r'MAGIC\s*=\s*b"([^"]+)"', py)
    cpp_magic = re.search(r'std::memcmp\(magic,\s*"([^"]+)"', cpp)
    check(
        py_magic and cpp_magic and py_magic.group(1) == cpp_magic.group(1),
        "the magic string matches on both sides",
        f"{py_magic.group(1) if py_magic else '?'} against "
        f"{cpp_magic.group(1) if cpp_magic else '?'}",
    )
    check(
        py_magic and len(py_magic.group(1)) == 8 and ", 8)" in cpp,
        "the magic occupies the eight bytes the reader consumes",
    )

    # The header is six unsigned 32-bit fields on both sides.
    py_header = re.search(r'struct\.pack\(\s*\n?\s*"<(\d)I"', py)
    cpp_header_fields = len(
        re.findall(r"read_exact\(in, &(?:dim|n_pairs|n_folds|flags|len_source|len_desc), 4\)", cpp)
    )
    check(
        py_header and py_header.group(1) == "6" and cpp_header_fields == 6,
        "the header holds six 32-bit fields on both sides",
        f"python <{py_header.group(1) if py_header else '?'}I, C++ {cpp_header_fields} reads",
    )

    check(
        'struct.pack("<BHB"' in py.replace(" ", "").replace('struct.pack("<BHB"', 'struct.pack("<BHB"')
        or 'struct.pack("<BHB"' in py,
        "the per-pair trailer is packed as u8, u16, u8 by the writer",
    )
    check(
        "read_exact(in, &label, 1)" in cpp
        and "read_exact(in, &fold, 2)" in cpp
        and "read_exact(in, &padding, 1)" in cpp,
        "the per-pair trailer is read as u8, u16, u8 by the reader",
    )
    check(
        'astype("<f4")' in py and "std::vector<float> buf" in cpp,
        "template values are little-endian float32 on both sides",
    )
    # The reader documents the same layout it implements.
    for field in ("magic", "dim", "n_pairs", "n_folds", "flags", "len_source", "len_desc"):
        pass
    check(
        all(field in hpp for field in ("FFVEMB03", "n_pairs", "n_folds", "float32")),
        "the header comment documents the layout the reader implements",
    )


# ---------------------------------------------------------------------------
# 2. JSON and CSV: C++ writes them, Python reads them
# ---------------------------------------------------------------------------


def _helper_relative_paths(text):
    """Relative paths each emit_* helper in the emitter contributes.

    A helper such as emit_stat opens an object named by its argument and writes
    fixed keys inside it, so its contribution is the set of those key names.
    """
    helpers = {}
    for match in re.finditer(r"\nvoid (emit_\w+)\(Json& j[^)]*\)\s*\n\{", text):
        name = match.group(1)
        body, depth, index = "", 0, match.end()
        while index < len(text):
            body += text[index]
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                if depth == 0:
                    break
                depth -= 1
            index += 1
        helpers[name] = body
    resolved = {name: _walk_emitter(body, {}) for name, body in helpers.items()}
    for _ in range(3):
        resolved = {name: _walk_emitter(body, resolved) for name, body in helpers.items()}
    return resolved


def _walk_emitter(body, nested_helpers):
    """Dotted paths a block of emitter calls produces, tracking nesting.

    Tracking the object stack is what makes the check path-aware: renaming one
    of several identically named keys is then caught, because the path changes
    even though the name still appears elsewhere.
    """
    paths, stack = set(), []
    pattern = re.compile(
        r'j\.(begin_object|begin_array|end_object|end_array|key_\w+)\(\s*(?:"([^"]*)")?'
        r'|(emit_\w+)\(\s*j\s*,\s*"([^"]+)"'
    )
    for match in pattern.finditer(body):
        call, name, helper, helper_name = match.groups()
        if helper:
            prefix = ".".join([p for p in stack + [helper_name] if p])
            paths.add(prefix)
            for relative in nested_helpers.get(helper, set()):
                paths.add(f"{prefix}.{relative}")
            continue
        if call == "begin_object" or call == "begin_array":
            if name:
                stack.append(name)
            else:
                # The outermost anonymous object is the document root and adds no
                # segment; an anonymous object inside an array is an element.
                stack.append("[]" if stack else "")
        elif call in ("end_object", "end_array"):
            if stack:
                stack.pop()
        elif call and call.startswith("key_") and name:
            paths.add(".".join([p for p in stack + [name] if p]))
    return paths


def emitted_json_paths():
    """Every dotted path the C++ side can write into a JSON record.

    Two emitters exist: emit_json.cpp writes results.json and ffv_client.cpp
    writes the protocol record.
    """
    paths = set()
    for parts in (("src", "bench", "emit_json.cpp"), ("src", "apps", "ffv_client.cpp")):
        text = strip_comments(read(*parts))
        helpers = _helper_relative_paths(text)
        body = text[text.index("bool write_json"):] if "bool write_json" in text else text
        paths |= _walk_emitter(body, helpers)
    # The top-level object contributes an empty prefix, so leading dots are
    # trimmed and the bare object name is kept alongside its children.
    return {p.lstrip(".") for p in paths if p.strip(".")}


def emitted_json_names(paths):
    names = set()
    for path in paths:
        names.update(part for part in path.split(".") if part != "[]")
    return names


def referenced_json_paths():
    """Dotted paths the python side reads, resolving its local aliases."""
    direct, names = set(), set()
    for module in (("python", "ffv", "report.py"), ("python", "ffv", "figures.py"),
                   ("python", "crosscheck.py")):
        text = read(*module)
        # Aliases such as: crypto = r["crypto"]
        alias = {}
        for variable, key in re.findall(r"^\s*(\w+)\s*=\s*r(?:esults)?\[[\"']([^\"']+)[\"']\]",
                                        text, flags=re.M):
            alias[variable] = key
        # pick(r, "a.b.c")
        for path in re.findall(r"pick\(\s*\w+\s*,\s*[\"']([^\"']+)[\"']", text):
            direct.add(path)
        # results["a"]["b"] and alias["b"]["c"]
        for variable, chain in re.findall(
            r"\b(results|r|" + "|".join(sorted(alias) or ["__none__"]) +
            r")((?:\[[\"'][^\"']+[\"']\])+)", text
        ):
            parts = re.findall(r"[\"']([^\"']+)[\"']", chain)
            prefix = [] if variable in ("results", "r") else [alias[variable]]
            direct.add(".".join(prefix + parts))
            names.update(parts)
        for part in re.findall(r"\.get\(\s*[\"']([^\"']+)[\"']", text):
            names.add(part)
    return direct, names


def check_results_json():
    group("results.json, C++ emitter against python readers")
    emitted_paths = emitted_json_paths()
    emitted = emitted_json_names(emitted_paths)
    check(len(emitted_paths) > 80, "the emitter defines a substantial path set",
          f"{len(emitted_paths)} paths, {len(emitted)} distinct names")

    referenced_paths, referenced_names = referenced_json_paths()

    def flatten(path):
        # Numeric indices and array-element markers name no key, so they are
        # removed and the remaining segments carry the whole contract.
        parts = [p for p in path.split(".") if p and p != "[]" and not p.lstrip("-").isdigit()]
        return ".".join(parts)

    flat_emitted = {flatten(p) for p in emitted_paths}
    unresolved = sorted(
        f for f in {flatten(p) for p in referenced_paths}
        if f and f not in flat_emitted and not any(e.startswith(f + ".") for e in flat_emitted)
    )
    check(not unresolved, "every dotted path the python side reads is emitted at that path",
          "unresolved: " + ", ".join(unresolved[:6]) if unresolved
          else f"{len(referenced_paths)} paths resolved")

    referenced = referenced_names | {part for p in referenced_paths for part in p.split(".")}
    # Names that belong to other files or to local dictionaries, not to
    # results.json, and so are outside this contract.
    outside = {
        "schema", "figures", "pipeline", "distributions", "roc", "fidelity", "scale",
        "batching", "cost", "title", "level", "text", "items", "caption", "path", "wide",
        "header", "rows", "body", "kind", "Answer", "type", "data",
    }
    missing = sorted(n for n in referenced - emitted - outside)
    check(not missing, "every key the python side reads is emitted by the C++ side",
          "missing: " + ", ".join(missing[:10]) if missing else f"{len(referenced)} referenced")

    # The schema string is the version handshake between the two halves.
    cpp_schema = re.search(r'key_string\("schema",\s*"([^"]+)"\)', read("src", "bench", "emit_json.cpp"))
    py_schema = re.search(r'!=\s*"([^"]+)"', read("python", "make_report.py"))
    check(
        cpp_schema and py_schema and cpp_schema.group(1) == py_schema.group(1),
        "the results schema name matches on both sides",
        f"{cpp_schema.group(1) if cpp_schema else '?'} against "
        f"{py_schema.group(1) if py_schema else '?'}",
    )
    cross_schema = re.search(r'schema.\)\s*!=\s*"([^"]+)"', read("python", "crosscheck.py"))
    if cross_schema:
        check(cpp_schema and cross_schema.group(1) == cpp_schema.group(1),
              "the cross-check expects the same schema name")

    # The protocol record written by the client.
    client_schema = re.search(r'key_string\("schema",\s*"([^"]+)"\)', read("src", "apps", "ffv_client.cpp"))
    check(bool(client_schema), "the client stamps its protocol record with a schema name",
          client_schema.group(1) if client_schema else "absent")


def check_scores_csv():
    group("scores.csv, C++ writer against python readers")
    writer = read("src", "bench", "exp_scores.cpp")
    header = re.search(r'fprintf\(f,\s*"([^"\\]+)\\n"\)', writer)
    columns = set(header.group(1).split(",")) if header else set()
    check(bool(columns), "the writer emits a header row", ", ".join(sorted(columns)))

    readers = read("python", "ffv", "figures.py") + read("python", "crosscheck.py")
    wanted = set(re.findall(r'row\[[\"\']([^\"\']+)[\"\']\]', readers))
    missing = sorted(wanted - columns)
    check(not missing, "every column the readers request is written",
          "missing: " + ", ".join(missing) if missing else ", ".join(sorted(wanted)))

    # The writer's format string must supply one value per column.
    values = re.search(r'fprintf\(f,\s*"([^"]*%[^"]*)\\n"', writer)
    if values and columns:
        specifiers = len(re.findall(r"%[-0-9.#+ ]*[a-zA-Z]", values.group(1)))
        check(specifiers == len(columns),
              "the row format supplies one value per column",
              f"{specifiers} specifiers for {len(columns)} columns")


# ---------------------------------------------------------------------------
# 3. Session and protocol file names, shared by four translation units
# ---------------------------------------------------------------------------


def check_session_files():
    group("session file names across the client, the server and the core")
    client_core = strip_comments(read("src", "core", "client.cpp"))
    server_core = strip_comments(read("src", "core", "server.cpp"))
    client_app = strip_comments(read("src", "apps", "ffv_client.cpp"))
    server_app = strip_comments(read("src", "apps", "ffv_server.cpp"))

    for name in ("session.txt", "relin.key", "galois.key"):
        in_core = f'"{name}"' in client_core
        in_server = f'"{name}"' in server_core
        check(in_core and in_server, f"'{name}' is named by both the writer and the reader",
              f"client core {in_core}, server core {in_server}")

    check('"public.key"' in client_core and '"public.key"' not in server_core,
          "'public.key' is written by the client and left unread by the server")
    check('"secret.key"' in client_core and '"secret.key"' not in server_core,
          "the secret key file is named by the client alone")

    # Request and response names must agree between the two executables.
    for name in ("probe.ct", "enrolled.ct", "meta.txt", "READY", "DONE", "score.ct"):
        in_client = f'"{name}"' in client_app
        in_server = f'"{name}"' in server_app
        check(in_client and in_server, f"'{name}' is named by both processes",
              f"client {in_client}, server {in_server}")

    check('"enrolled.txt"' in client_app and '"enrolled.txt"' in server_app,
          "the cleartext enrolled template file is named by both processes")

    # Subdirectory layout.
    for sub in ("public", "private", "request", "response"):
        check(f'"{sub}"' in client_app, f"the client defines the '{sub}' subdirectory")
    check('"public"' in server_app and '"request"' in server_app and '"response"' in server_app,
          "the server opens the public, request and response subdirectories")


# ---------------------------------------------------------------------------
# 4. Command-line flags that run.sh passes
# ---------------------------------------------------------------------------


def flags_in(text):
    return set(re.findall(r'"(--[a-z][a-z0-9-]*)"', text))


def check_flags():
    group("flags run.sh passes against the parsers that accept them")
    shell = read("run.sh")

    programs = {
        "ffv_bench": strip_comments(read("src", "bench", "main.cpp")),
        "ffv_client": strip_comments(read("src", "apps", "ffv_client.cpp")),
        "ffv_server": strip_comments(read("src", "apps", "ffv_server.cpp")),
        "ffv_selftest": strip_comments(read("src", "apps", "ffv_selftest.cpp")),
    }
    # Flags the shell hands to each binary, taken from the invocation lines and
    # the argument strings assembled just above them.
    used = {
        "ffv_bench": {"--templates", "--out-dir", "--cost-reps"},
        "ffv_client": {"--session", "--templates", "--pair", "--threshold"},
        "ffv_server": {"--session", "--once", "--timeout"},
        "ffv_selftest": {"--tmp"},
    }
    for program, wanted in used.items():
        accepted = flags_in(programs[program])
        missing = sorted(wanted - accepted)
        check(not missing, f"{program} accepts every flag run.sh passes",
              "missing: " + ", ".join(missing) if missing else ", ".join(sorted(wanted)))
        check(f"$BUILD_DIR/{program}" in shell or f"/{program}\"" in shell,
              f"run.sh invokes {program}")

    # Flags the shell documents for itself must exist in its own parser.
    documented = set(re.findall(r"^  (--[a-z][a-z0-9-]*)", shell, flags=re.M))
    handled = set(re.findall(r"^\s+(--[a-z][a-z0-9-]*)\)", shell, flags=re.M))
    orphan_doc = sorted(documented - handled)
    check(not orphan_doc, "every flag run.sh documents is handled by its parser",
          "undocumented handling: " + ", ".join(orphan_doc) if orphan_doc else
          f"{len(handled)} flags")
    orphan_handled = sorted(handled - documented - {"--help"})
    check(not orphan_handled, "every flag run.sh handles appears in its help text",
          "missing from help: " + ", ".join(orphan_handled) if orphan_handled else "")


# ---------------------------------------------------------------------------
# 5. Python entry points, modules and requirements
# ---------------------------------------------------------------------------


def check_python_wiring():
    group("python entry points, modules and requirements")
    shell = read("run.sh")
    for script in re.findall(r"PROJECT_DIR/(python/[a-z_]+\.py)", shell):
        check(os.path.isfile(os.path.join(ROOT, script)), f"run.sh references {script}")

    # Flags the shell passes to each python entry point must be declared there.
    for script, wanted in (
        ("python/fetch_assets.py", {"--cache", "--model-pack", "--search", "--lfw-root",
                                    "--no-download"}),
        ("python/extract_embeddings.py", {"--lfw-root", "--pairs", "--models", "--out",
                                          "--detector-size", "--limit-pairs"}),
        ("python/make_report.py", {"--results", "--scores", "--protocol", "--out-dir"}),
        ("python/crosscheck.py", {"--results", "--scores", "--markdown"}),
    ):
        text = read(*script.split("/"))
        declared = set(re.findall(r'add_argument\(\s*"(--[a-z][a-z0-9-]*)"', text))
        missing = sorted(wanted - declared)
        check(not missing, f"{os.path.basename(script)} declares every flag run.sh passes",
              "missing: " + ", ".join(missing) if missing else f"{len(wanted)} flags")

    # Local package modules imported by the entry points must exist.
    for script in ("python/extract_embeddings.py", "python/make_report.py"):
        text = read(*script.split("/"))
        for names in re.findall(r"^from ffv import ([^#\n]+)", text, flags=re.M):
            for name in [n.strip() for n in names.split(",")]:
                check(os.path.isfile(os.path.join(ROOT, "python", "ffv", f"{name}.py")),
                      f"{os.path.basename(script)} imports ffv.{name}, which exists")
    check(os.path.isfile(os.path.join(ROOT, "python", "ffv", "__init__.py")),
          "the ffv package has an __init__.py, so the import works from any directory")

    # Third-party imports must be covered by requirements.txt.
    requirements = read("python", "requirements.txt").lower()
    distribution = {"cv2": "opencv-python-headless", "numpy": "numpy",
                    "onnxruntime": "onnxruntime", "matplotlib": "matplotlib",
                    "reportlab": "reportlab"}
    imported = set()
    for base, _, files in os.walk(os.path.join(ROOT, "python")):
        for name in files:
            if not name.endswith(".py"):
                continue
            with open(os.path.join(base, name), encoding="utf-8") as handle:
                text = handle.read()
            for module in re.findall(r"^(?:import|from)\s+([a-z_][a-z0-9_]*)", text, flags=re.M):
                if module in distribution:
                    imported.add(module)
    missing = sorted(distribution[m] for m in imported if distribution[m] not in requirements)
    check(not missing, "requirements.txt covers every third-party import",
          "missing: " + ", ".join(missing) if missing else
          ", ".join(sorted(distribution[m] for m in imported)))


# ---------------------------------------------------------------------------
# 6. Build graph and the server isolation promise
# ---------------------------------------------------------------------------


def check_build_graph():
    group("build graph")
    cmake = read("CMakeLists.txt")
    for source in re.findall(r"(src/[a-z_/]+\.cpp)", cmake):
        check(os.path.isfile(os.path.join(ROOT, source)), f"CMakeLists names {source}, which exists")

    # SEAL exports a differently named target depending on how it was built, and
    # Homebrew ships the shared build. Both names must be handled.
    check("TARGET SEAL::seal)" in cmake and "TARGET SEAL::seal_shared)" in cmake,
          "CMakeLists handles both the static and the shared SEAL target names")
    check("SEAL::seal " not in cmake.replace("TARGET SEAL::seal ", "")
          or "${FFV_SEAL_TARGET}" in cmake,
          "the SEAL target is linked through the discovered variable")
    check("get_target_property(FFV_SEAL_TYPE ${FFV_SEAL_TARGET}" in cmake,
          "the library type is queried on the discovered target")

    check("target_link_libraries(ffv_server_app PRIVATE ffv_server)" in cmake
          and "ffv_client" not in cmake.split("ffv_server_app")[-1],
          "the server executable links the server library and not the client library")
    check("src/core/client.cpp" in cmake.split("add_library(ffv_client")[-1][:200],
          "the client library holds client.cpp alone")
    check("-ffp-contract=off" in cmake,
          "floating-point contraction is switched off for cross-host agreement")

    isolation = read("tools", "check_isolation.sh")
    check("libffv_server.a" in isolation and "libffv_client.a" in isolation,
          "the isolation check inspects both libraries the build produces")
    check("src/core/server.cpp" in isolation and "src/apps/ffv_server.cpp" in isolation,
          "the isolation check inspects the server sources the build compiles")

    # Headers included by the sources must exist.
    for base, _, files in os.walk(os.path.join(ROOT, "src")):
        for name in files:
            if not name.endswith((".cpp", ".hpp")):
                continue
            with open(os.path.join(base, name), encoding="utf-8") as handle:
                for header in re.findall(r'#include "(ffv/[a-z_]+\.hpp)"', handle.read()):
                    if header.endswith("build_info.hpp"):
                        continue  # generated by CMake at configure time
                    check(os.path.isfile(os.path.join(ROOT, "include", header)),
                          f"{name} includes {header}, which exists")


# ---------------------------------------------------------------------------
# 7. Standard includes, for the toolchains this project targets
# ---------------------------------------------------------------------------

# Apple's libc++ removes transitive includes over time, so a source that reaches
# a name through another header compiles on Linux and fails on macOS. Each
# identifier below is required to appear together with the header that declares
# it, in the same file.
REQUIRED_INCLUDES = [
    ("std::greater", "<functional>"),
    ("std::pair<", "<utility>"),
    ("std::fopen", "<cstdio>"),
    ("std::fprintf", "<cstdio>"),
    ("std::snprintf", "<cstdio>"),
    ("std::remove(", "<cstdio>"),
    ("std::fabs", "<cmath>"),
    ("std::sqrt", "<cmath>"),
    ("std::log2", "<cmath>"),
    ("std::pow", "<cmath>"),
    ("std::isfinite", "<cmath>"),
    ("std::max(", "<algorithm>"),
    ("std::min(", "<algorithm>"),
    ("std::sort", "<algorithm>"),
    ("std::memcpy", "<cstring>"),
    ("std::memcmp", "<cstring>"),
    ("std::shared_ptr", "<memory>"),
    ("std::unique_ptr", "<memory>"),
    ("std::make_unique", "<memory>"),
    ("std::int64_t", "<cstdint>"),
    ("std::uint32_t", "<cstdint>"),
    ("std::size_t", "<cstddef>"),
    ("std::ofstream", "<fstream>"),
    ("std::ifstream", "<fstream>"),
    ("std::ostringstream", "<sstream>"),
    ("std::stringstream", "<sstream>"),
    ("std::runtime_error", "<stdexcept>"),
    ("std::invalid_argument", "<stdexcept>"),
    ("std::atoi", "<cstdlib>"),
    ("std::atof", "<cstdlib>"),
]

def _resolve_includes(path, seen=None):
    """System headers a file gets, directly and through its own project headers.

    The graph is resolved instead of tabulated, so a header that starts or stops
    including something is accounted for without anyone updating a list here.
    """
    if seen is None:
        seen = set()
    real = os.path.abspath(path)
    if real in seen or not os.path.isfile(real):
        return set()
    seen.add(real)
    with open(real, encoding="utf-8") as handle:
        text = handle.read()
    headers = set(re.findall(r"#include\s+(<[a-z_]+>)", text))
    for local in re.findall(r'#include\s+"([A-Za-z0-9_/]+\.hpp)"', text):
        for root in (os.path.join(ROOT, "include"), os.path.dirname(real),
                     os.path.join(ROOT, "src", "bench")):
            candidate = os.path.join(root, local)
            if os.path.isfile(candidate):
                headers |= _resolve_includes(candidate, seen)
                break
    return headers


def check_includes():
    group("standard includes, for libstdc++ and Apple's libc++")
    sources = []
    for base, _, files in os.walk(os.path.join(ROOT, "src")):
        for name in sorted(files):
            if name.endswith((".cpp", ".hpp")):
                sources.append(os.path.join(base, name))
    for name in sorted(os.listdir(os.path.join(ROOT, "include", "ffv"))):
        sources.append(os.path.join(ROOT, "include", "ffv", name))

    problems = []
    for path in sources:
        with open(path, encoding="utf-8") as handle:
            code = strip_comments(handle.read())
        available = _resolve_includes(path)
        for identifier, header in REQUIRED_INCLUDES:
            if identifier in code and header not in available:
                problems.append(
                    f"{os.path.relpath(path, ROOT)} uses {identifier} without {header}")

    check(not problems, "every source includes the header for each name it uses",
          "; ".join(problems[:4]) if problems else f"{len(sources)} files")


# ---------------------------------------------------------------------------
# 8. Documentation against reality
# ---------------------------------------------------------------------------


def check_docs():
    group("documentation against the tree")
    for document in ("README.md", "RUNBOOK.md"):
        text = read(document)
        for path in set(re.findall(r"`((?:python|src|tools|include|cmake)/[A-Za-z0-9_./-]+)`", text)):
            if path.endswith("/"):
                continue
            full = os.path.join(ROOT, path)
            check(os.path.exists(full), f"{document} names {path}, which exists")
    shell = read("run.sh")
    implemented = set(re.findall(r"^\s*if want (\w+)", shell, flags=re.M))
    implemented |= set(re.findall(r"want (\w+) &&", shell))
    check(len(implemented) >= 8, "run.sh implements a full set of stages",
          ", ".join(sorted(implemented)))
    for document in ("README.md", "RUNBOOK.md"):
        text = read(document)
        named = set(re.findall(r"--only (\w+)", text)) - {"STAGE"}
        missing = sorted(named - implemented)
        check(not missing, f"{document} names only stages run.sh implements",
              "unimplemented: " + ", ".join(missing) if missing else ", ".join(sorted(named)))
        # And the help text of run.sh must list every stage it implements.
        listed = re.search(r"--only STAGE\s+run one stage: ([^\n]+(?:\n\s+[a-z, ]+)?)", shell)
        if listed:
            advertised = set(re.findall(r"[a-z]+", listed.group(1))) - {"run", "one", "stage"}
            absent = sorted(implemented - advertised)
            check(not absent, "the help text lists every stage run.sh implements",
                  "absent from help: " + ", ".join(absent) if absent else "")


def main():
    print(f"wiring check for {ROOT}")
    check_container()
    check_results_json()
    check_scores_csv()
    check_session_files()
    check_flags()
    check_python_wiring()
    check_build_graph()
    check_includes()
    check_docs()

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} wiring checks passed")
    if FAILURES:
        print(f"{len(FAILURES)} failed:")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
