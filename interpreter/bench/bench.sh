#!/usr/bin/env bash
# Benchmark fastbolge against fast20.c on MalbolgeLisp.
#
#   bench.sh FASTBOLGE FAST20 MALBOLGE_LISP_DIR [RUNS]
#
# MALBOLGE_LISP_DIR is a checkout of https://github.com/iczelia/malbolge-lisp
# with lisp.zip unpacked and lisp.mb built (cat init_module.mb core.mb).
# Each workload runs RUNS times per interpreter (default 3) after one
# warm-up read of lisp.mb, and outputs are checked to be identical.
set -euo pipefail
FB=$1 F20=$2 L=$3 RUNS=${4:-3}
HERE=$(cd "$(dirname "$0")" && pwd)
cat "$L/lisp.mb" > /dev/null   # warm the page cache
printf '(+ 1 2)\n' > /tmp/fb-startup.lisp
for w in startup fib4 fib1; do
  case $w in
    startup) in=/tmp/fb-startup.lisp ;;
    *) in=$HERE/$w.lisp ;;
  esac
  for name in fast20 fastbolge; do
    if [ $name = fast20 ]; then cmd=("$F20" "$L/lisp.mb"); else cmd=("$FB" -m fast20 "$L/lisp.mb"); fi
    for r in $(seq "$RUNS"); do
      s=$(date +%s.%N)
      "${cmd[@]}" < "$in" > "/tmp/fb-$w-$name.out"
      e=$(date +%s.%N)
      printf '%s\t%s\t%d\t%.2f\n' "$w" "$name" "$r" "$(echo "$e - $s" | bc)"
    done
  done
  cmp -s "/tmp/fb-$w-fast20.out" "/tmp/fb-$w-fastbolge.out" && echo "# $w: outputs identical" || echo "# $w: OUTPUTS DIFFER"
done
