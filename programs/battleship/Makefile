# Battleship in Malbolge Unshackled.
#
#   make            build the interpreter and the game
#   make play       build, then start a game against the computer
#   make clean      remove build artifacts (keeps the downloaded LMFAO)
#
# Assembling the game needs LMFAO, the Malbolge Unshackled assembler.  If an
# `lmfao` is on your PATH it is used; otherwise `make` downloads LMFAO's source
# and builds tools/lmfao (needs git, flex and bison 3; on macOS:
# `brew install bison`).  Or point at your own: make LMFAO=/path/to/lmfao

# TODO (monorepo): once the Rust interpreter lands at the repo root
# (interpreter/), switch MU to that shared binary instead of the vendored
# tools/mu and drop tools/mu.c.
MU    ?= tools/mu
CC    ?= cc
PY    ?= python3
LMFAO ?= $(shell command -v lmfao 2>/dev/null || echo tools/lmfao)

# LMFAO's grammar needs bison 3; macOS ships 2.3, so prefer Homebrew's.
BISON ?= $(firstword $(wildcard /opt/homebrew/opt/bison/bin/bison /usr/local/opt/bison/bin/bison) bison)
FLEX  ?= flex
LMFAO_REPO := https://github.com/esoteric-programmer/LMFAO
LMFAO_REV  := c62bbe32937d3266cb7251b2e4d38fb23481de43
LMFAO_SRC  := tools/lmfao-src

SRC := compiler/battleship.py compiler/lang.py compiler/backend.py compiler/getc.py

all: $(MU) game/battleship.mu

tools/mu: tools/mu.c
	$(CC) -O2 -o $@ $<

game/battleship.hell: $(SRC)
	@mkdir -p game
	$(PY) compiler/battleship.py $@

game/battleship.mu: game/battleship.hell | $(LMFAO)
	$(LMFAO) -o $@ $<

# Build LMFAO from source without its own Makefile, which hardcodes gcc,
# -lfl and <malloc.h> and so fails on macOS.
tools/lmfao:
	@test -d $(LMFAO_SRC) || git clone -q $(LMFAO_REPO) $(LMFAO_SRC)
	cd $(LMFAO_SRC) && git checkout -q $(LMFAO_REV)
	@mkdir -p $(LMFAO_SRC)/build
	echo '#include <stdlib.h>' > $(LMFAO_SRC)/build/malloc.h
	echo 'int yywrap(void) { return 1; }' > $(LMFAO_SRC)/build/yywrap.c
	$(BISON) -d -o $(LMFAO_SRC)/build/lmfao.tab.c $(LMFAO_SRC)/src/lmfao.y
	$(FLEX) -o $(LMFAO_SRC)/build/lex.yy.c $(LMFAO_SRC)/src/lmfao.l
	$(CC) -O2 -w -I$(LMFAO_SRC)/build -I$(LMFAO_SRC)/src -o $@ \
	  $(LMFAO_SRC)/build/lmfao.tab.c $(LMFAO_SRC)/build/lex.yy.c \
	  $(LMFAO_SRC)/build/yywrap.c \
	  $(addprefix $(LMFAO_SRC)/src/,initialize.c highlevel_initializer.c main.c malbolge.c)

play: all
	$(PY) launcher.py

clean:
	rm -f tools/mu game/battleship.mu game/battleship.hell

.PHONY: all play clean
