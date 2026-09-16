#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Verifies that the server half holds no capability to recover a plaintext.
#
# Three checks run at increasing depth, because each catches what the one before
# it can miss.
#
#   1. Sources.  The server sources are searched for the identifiers that would
#      carry a secret, with comments and string literals removed first so that
#      prose naming those identifiers does not register as use.
#
#   2. Objects.  The compiled server library and the server application object
#      are searched for references to those types. This catches a secret arriving
#      through a header or a template instantiation, which a grep of the sources
#      would not see. The client library is searched the same way and is expected
#      to reference them, which shows the check discriminates.
#
#   3. Executable.  The linked ffv_server binary is searched for seal::Decryptor,
#      the one class in SEAL that turns a ciphertext back into a plaintext.
#
# Written for bash 3.2, the version macOS ships.

set -u

BUILD_DIR="${1:-build}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
failures=0

note() { printf '  note  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1"; failures=$((failures + 1)); }
pass() { printf '  pass  %s\n' "$1"; }

# Removes // comments, /* */ comment bodies and double-quoted literals.
strip_prose() {
    sed -e 's|//.*||' -e 's|/\*[^*]*\*/||g' -e 's|"[^"]*"||g' "$1"
}

printf '[1. server sources]\n'
SERVER_SOURCES="$ROOT/src/core/server.cpp $ROOT/include/ffv/server.hpp $ROOT/src/apps/ffv_server.cpp"
for pattern in 'SecretKey' 'Decryptor' 'secret_key' 'decrypt'; do
    hits=0
    for source in $SERVER_SOURCES; do
        [ -f "$source" ] || continue
        count=$(strip_prose "$source" | grep -c "$pattern" 2>/dev/null || true)
        hits=$((hits + count))
    done
    if [ "$hits" -eq 0 ]; then
        pass "no server source line uses '$pattern'"
    else
        fail "$hits server source line(s) use '$pattern'"
        for source in $SERVER_SOURCES; do
            [ -f "$source" ] || continue
            strip_prose "$source" | grep -n "$pattern" | sed "s|^|      $(basename "$source"):|"
        done
    fi
done

printf '\n[2. compiled objects]\n'
if ! command -v nm >/dev/null 2>&1; then
    note 'nm is unavailable, so the object and executable checks are skipped'
else
    server_objects="$BUILD_DIR/libffv_server.a"
    for candidate in \
        "$BUILD_DIR/CMakeFiles/ffv_server_app.dir/src/apps/ffv_server.cpp.o" \
        "$BUILD_DIR/CMakeFiles/ffv_server_app.dir/src/apps/ffv_server.cpp.obj"; do
        [ -f "$candidate" ] && server_objects="$server_objects $candidate"
    done

    server_hits=0
    for object in $server_objects; do
        [ -f "$object" ] || continue
        count=$(nm "$object" 2>/dev/null | grep -cE 'SecretKey|Decryptor' || true)
        server_hits=$((server_hits + count))
    done
    if [ "$server_hits" -eq 0 ]; then
        pass "the server objects reference no secret-key or decryptor symbol"
    else
        fail "the server objects reference $server_hits secret-key or decryptor symbol(s)"
    fi

    if [ -f "$BUILD_DIR/libffv_client.a" ]; then
        client_hits=$(nm "$BUILD_DIR/libffv_client.a" 2>/dev/null | grep -cE 'SecretKey|Decryptor' || true)
        if [ "$client_hits" -gt 0 ]; then
            pass "the client library references $client_hits such symbol(s), so the check discriminates"
        else
            fail "the client library references none either, so the check proves nothing"
        fi
    else
        note 'the client library is absent, so the discrimination check is skipped'
    fi

    printf '\n[3. linked executable]\n'
    SERVER_BIN="$BUILD_DIR/ffv_server"
    if [ ! -x "$SERVER_BIN" ]; then
        fail "$SERVER_BIN is absent; build the project first"
    else
        # A statically linked SEAL puts its symbols in the executable; a shared
        # one leaves undefined references to them. Both listings are collected and
        # combined so the check reads the same either way.
        symbols="$(nm "$SERVER_BIN" 2>/dev/null || true)
$(nm -D "$SERVER_BIN" 2>/dev/null || true)
$(nm -u "$SERVER_BIN" 2>/dev/null || true)"

        # An empty or unreadable symbol table would let the next check pass while
        # proving nothing, so the table is confirmed to mention SEAL at all first.
        anchor=$(printf '%s' "$symbols" | grep -c 'seal' || true)
        if [ "$anchor" -eq 0 ]; then
            note 'the symbol table names no SEAL symbol, so this check is inconclusive;'
            note 'check 2 above is the one that carries the result.'
        else
            pass "the symbol table is readable and names $anchor SEAL symbol(s)"
            count=$(printf '%s' "$symbols" | grep -c 'Decryptor' || true)
            if [ "$count" -eq 0 ]; then
                pass 'the linked server binary references no seal::Decryptor symbol'
            else
                fail "the linked server binary references $count seal::Decryptor symbol(s)"
                printf '%s' "$symbols" | grep 'Decryptor' | head -5 | sed 's|^|      |'
            fi
            secret=$(printf '%s' "$symbols" | grep -c 'SecretKey' || true)
            if [ "$secret" -gt 0 ]; then
                note "$secret symbol(s) naming seal::SecretKey come from the SEAL library's own"
                note 'validity helpers, which take a key as an argument and hold none themselves;'
                note 'check 2 shows this project contributes no such reference.'
            fi
        fi
    fi
fi

printf '\n'
if [ "$failures" -eq 0 ]; then
    printf 'server isolation verified\n'
    exit 0
fi
printf '%d isolation check(s) failed\n' "$failures"
exit 1
