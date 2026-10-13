# Battleship in Malbolge Unshackled.
#
#   make            build the interpreter and the game
#   make play       build, then start a game against the computer
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

play: all
	$(PY) launcher.py

clean:
	rm -f tools/mu game/battleship.mu game/battleship.hell

.PHONY: all play clean
