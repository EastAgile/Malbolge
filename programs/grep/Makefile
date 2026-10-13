# grep.mal - build the Malbolge grep and its reference interpreter.
#
# Targets:
#   make mu       build the bundled Malbolge Unshackled interpreter (build/mu)
#   make grep.mu  assemble the Malbolge program from build/grep.hell (needs LMFAO)
#   make grep     compile src/grep.c all the way to build/grep.mu (needs ELVM + LMFAO)
#   make test     run the native reference against GNU grep (fast)
#   make clean
#
# The committed, ready-to-assemble form is build/grep.hell.xz (HeLL assembly).
# Turning it into build/grep.mu needs LMFAO (the Malbolge Unshackled assembler);
# regenerating the HeLL from src/grep.c additionally needs the ELVM toolchain.
# Point the variables below at your checkouts, or put the tools on your PATH.

CC      ?= cc
CFLAGS  ?= -O2 -Wall

ELVM    ?=              # path to an ELVM checkout (provides out/8cc, out/elc)
LMFAO   ?= lmfao        # the LMFAO binary (Malbolge Unshackled assembler)

BUILD   := build

.PHONY: all mu grep.mu grep test clean
all: mu grep.mu

mu: $(BUILD)/mu
$(BUILD)/mu: tools/mu.c
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) -o $@ $<

# Assemble the committed HeLL into a runnable Malbolge program.
grep.mu: $(BUILD)/grep.mu
$(BUILD)/grep.mu: $(BUILD)/grep.hell
	@command -v $(LMFAO) >/dev/null 2>&1 || { \
	  echo "LMFAO not found. Get it from https://github.com/esoteric-programmer/LMFAO"; \
	  echo "and set LMFAO=/path/to/lmfao (or put it on PATH)."; exit 1; }
	$(LMFAO) $< -o $@

$(BUILD)/grep.hell: $(BUILD)/grep.hell.xz
	xz -dk -f $<

# Recompile the whole pipeline from C (only needed to change the program).
grep:
	@test -n "$(ELVM)" || { echo "Set ELVM=/path/to/elvm (needs out/8cc and out/elc)."; exit 1; }
	@mkdir -p $(BUILD)
	$(ELVM)/out/8cc -S -I$(ELVM) -I$(ELVM)/libc -o $(BUILD)/grep.eir src/grep.c
	$(ELVM)/out/elc -hell $(BUILD)/grep.eir > $(BUILD)/grep.hell
	$(MAKE) $(BUILD)/grep.mu

test: tests/run.sh
	ELVM="$(ELVM)" tests/run.sh

clean:
	rm -f $(BUILD)/mu $(BUILD)/grep.eir $(BUILD)/grep.hell $(BUILD)/grep.mu $(BUILD)/grep-ref
