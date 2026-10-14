# Battleship in Malbolge Unshackled.
#
#   make            build the interpreter and the game
#   make play       build, then start a game against the computer
#   make test       fast tests: Python and Rust versions against the recorded
#                   Malbolge sessions, fleet rules, compiler checks (~10 s)
#   make test-all   also re-run the Malbolge program itself (~2 min, ~4 GB per run)
#   make bench      measure all three versions; rewrites compare/chart.svg
#   make clean      remove build artifacts
#
# Assembling the game needs LMFAO (the Malbolge Unshackled assembler).  Point
# LMFAO at your binary, or let the monorepo's toolchain provide it:
#   make LMFAO=/path/to/lmfao

# TODO (monorepo): once the Rust interpreter lands at the repo root
# (interpreter/), switch MU to that shared binary instead of the vendored
# tools/mu and drop tools/mu.c.
MU    ?= tools/mu
LMFAO ?= lmfao
CC    ?= cc
PY    ?= python3

SRC := compiler/battleship.py compiler/lang.py compiler/backend.py compiler/getc.py

all: tools/mu game/battleship.mu

tools/mu: tools/mu.c
	$(CC) -O2 -o $@ $<

game/battleship.hell: $(SRC)
	@mkdir -p game
	$(PY) compiler/battleship.py $@

game/battleship.mu: game/battleship.hell
	$(LMFAO) -o $@ $<

# Nothing but the interpreter runs at play time.
play: all
	$(MU) game/battleship.mu

PYTEST ?= pytest

test:
	$(PYTEST) -q

test-all: all
	BATTLESHIP_MALBOLGE=1 $(PYTEST) -q

bench: all
	$(PY) compare/bench.py

clean:
	rm -f tools/mu game/battleship.mu game/battleship.hell
	rm -rf compare/rust/target compare/measure

.PHONY: all play test test-all bench clean
