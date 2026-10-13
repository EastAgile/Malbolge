#!/usr/bin/env bash
#
# Differential test for the grep: compares our matcher against GNU grep.
#
# By default it tests the NATIVE reference build (src/grep.c compiled with cc),
# which is fast and exercises exactly the same matching code that is compiled to
# Malbolge. Run with MALBOLGE=1 to instead drive the real Malbolge program
# (build/grep.mu) through the bundled interpreter - correct but very slow, so it
# uses a reduced set of tiny inputs.
#
set -u
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

REF="$tmp/grep-ref"
cc -O2 -o "$REF" "$here/src/grep.c"

# Build the reference as a header-driven filter identical to the Malbolge one.
run_ref() { printf '%s\n%s\n' "$1" "$2" | cat - "$3" | "$REF"; }

MU="${MU:-$here/build/mu}"
run_mb() { printf '%s\n%s\n' "$1" "$2" | cat - "$3" | "$MU" "$here/build/grep.mu"; }

run_gnu() {
  if [ -n "$1" ]; then grep -"$1" -- "$2" "$3" 2>/dev/null
  else grep -- "$2" "$3" 2>/dev/null; fi
}

corpus="$tmp/corpus.txt"
cat > "$corpus" <<'EOF'
The quick brown fox
jumps over 42 lazy dogs
Foo bar BAZ
foobar
f00bar
Hello, World!
hello world
2026-10-12 log line
ERROR: something failed
error lowercase
end$sign and ^caret
   leading spaces
EOF

# flags  pattern
CASES=(
  "::foo"
  "i::foo"
  "v::foo"
  "n::foo"
  "c::o"
  "in::^f"
  "::bar$"
  "::f.o"
  "::fo*bar"
  "i::baz"
  "::[0-9]"
  "::[0-9][0-9]"
  "::[^a-zA-Z ]"
  "::l.*o"
  "::."
  "::xyzzy"
  "::[A-Z][a-z]*"
  "::\\$"
  "::^The"
  "::dogs$"
  "vi::error"
)

pass=0; fail=0
use_mb=0; [ "${MALBOLGE:-0}" = 1 ] && use_mb=1
# Malbolge mode: use a tiny corpus and a short list (each run is slow).
if [ "$use_mb" = 1 ]; then
  cat > "$corpus" <<'EOF'
foobar
Foo
nope
EOF
  CASES=("::foo" "i::foo" "v::foo" "n::foo" "c::o")
fi

for spec in "${CASES[@]}"; do
  flags="${spec%%::*}"; pat="${spec#*::}"
  if [ "$use_mb" = 1 ]; then got="$(run_mb "$flags" "$pat" "$corpus")"
  else got="$(run_ref "$flags" "$pat" "$corpus")"; fi
  want="$(run_gnu "$flags" "$pat" "$corpus")"
  if [ "$got" = "$want" ]; then pass=$((pass+1));
  else fail=$((fail+1)); printf 'FAIL flags=%q pat=%q\n  got : %q\n  want: %q\n' "$flags" "$pat" "$got" "$want"; fi
done

echo "passed $pass, failed $fail"
[ "$fail" = 0 ]
