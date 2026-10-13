/*
 * mu - a Malbolge Unshackled interpreter.
 *
 * Values are 3-adic trit strings whose leading trit repeats forever. A value is
 * stored as (lead, delta): the all-`lead` string ...ttt plus a signed integer
 * offset, the same representation LMFAO uses. So ...0000 + 5 is 5, ...1111 + 0
 * is C1, ...2222 + 0 is C2 (-1 as a 3-adic integer).
 *
 * Semantics follow the Malbolge Unshackled page on the esolangs wiki:
 *   - rotation width starts at 10 and is widened when a MovD makes D wider than
 *     half the rotation width (we widen to exactly twice D's width);
 *   - rotation acts on the low `rotwidth` trits, higher trits are untouched;
 *   - x mod 94 treats ...111 as 0t1111111111 (8) and ...222 as 0t2222222222 (16);
 *   - input: '\n' reads as ...21, EOF reads as ...22; output of ...21 is '\n';
 *     other natural values are written as Unicode code points (UTF-8).
 *
 * Usage: mu [-b] [-s] program.mu
 *   -b  byte mode: read input bytes as code points 0-255 and write code points
 *       below 256 as single bytes (lossless for arbitrary binary data).
 *   -s  print the executed step count to stderr on exit.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { int64_t d; uint8_t t; } V; /* value = ...ttt + d */

static const char XLAT2[] =
    "5z]&gqtyfr$(we4{WP)H-Zn,[%\\3dL+Q;>U!pJS72FhOA1CB6v^=I_0/8|jsb9m<.TVac`uY*MK'X~xDl}REokN:#?G\"i@";
static const uint8_t CRZ[3][3] = {{1, 0, 0}, {1, 0, 2}, {2, 2, 1}}; /* [d][a] */

static uint64_t P3[41];
static int rotwidth = 10;
static int maxdwidth = 0;
static int bytemode = 0;

static inline V norm(V v) {
  if (v.t == 0 && v.d < 0) { v.t = 2; v.d += 1; }
  else if (v.t == 2 && v.d > 0) { v.t = 0; v.d -= 1; }
  return v;
}

/* base value of w copies of trit t */
static inline int64_t base(int t, int w) { return t == 0 ? 0 : (int64_t)(t * ((P3[w] - 1) / 2)); }

/* number of trits not equal to the repeating lead trit */
static int width(V v) {
  v = norm(v);
  if (v.t == 0 && v.d == 0) return 0;
  for (int w = 1; w <= 39; w++) {
    int64_t lo = (int64_t)base(v.t, w) + v.d;
    if (lo >= 0 && (uint64_t)lo < P3[w]) {
      /* low w trits hold the value; check that it isn't shorter */
      return w;
    }
  }
  fprintf(stderr, "mu: value too wide\n");
  exit(3);
}

/* low w trits of v (requires width(v) <= w) */
static inline uint64_t lowtrits(V v, int w) { return (uint64_t)(base(v.t, w) + v.d); }
static inline V fromlow(uint64_t lo, int t, int w) { V r = {(int64_t)lo - base(t, w), (uint8_t)t}; return norm(r); }

static V crz(V a, V d) {
  a = norm(a); d = norm(d);
  int wa = width(a), wd = width(d);
  int w = (wa > wd ? wa : wd) + 1;
  if (w > 39) { fprintf(stderr, "mu: crz too wide\n"); exit(3); }
  uint64_t la = lowtrits(a, w), ld = lowtrits(d, w), r = 0;
  for (int i = 0; i < w; i++) {
    r += P3[i] * CRZ[ld % 3][la % 3];
    la /= 3; ld /= 3;
  }
  return fromlow(r, CRZ[d.t][a.t], w);
}

static V rot(V v) {
  v = norm(v);
  int w = width(v);
  if (w < rotwidth) w = rotwidth;
  if (w > 39) { fprintf(stderr, "mu: rot too wide\n"); exit(3); }
  uint64_t lo = lowtrits(v, w);
  uint64_t low = lo % P3[rotwidth], high = lo - low;
  low = low / 3 + (low % 3) * P3[rotwidth - 1];
  return fromlow(high + low, v.t, w);
}

static inline int mod94(V v) {
  int64_t x = v.d + (v.t == 1 ? 8 : v.t == 2 ? 16 : 0);
  x %= 94;
  return (int)(x < 0 ? x + 94 : x);
}

/* ---- memory: three growable arrays keyed by lead trit ---- */
typedef struct { V *pos; int64_t npos; V *neg; int64_t nneg; } Region;
static Region R[3];
static int64_t proglen;

static void grow(V **arr, int64_t *n, int64_t need) {
  int64_t m = *n ? *n : 1024;
  while (m <= need) m *= 2;
  *arr = realloc(*arr, (size_t)m * sizeof(V));
  if (!*arr) { fprintf(stderr, "mu: out of memory\n"); exit(1); }
  for (int64_t i = *n; i < m; i++) { (*arr)[i].d = INT64_MIN; (*arr)[i].t = 0; }
  *n = m;
}

static int64_t filled; /* natural cells [0, filled) hold their initial values */

static inline V *slot(V a) {
  Region *r = &R[a.t];
  if (a.d >= 0) { if (a.d >= r->npos) grow(&r->pos, &r->npos, a.d); return &r->pos[a.d]; }
  int64_t k = -a.d - 1;
  if (k >= r->nneg) grow(&r->neg, &r->nneg, k);
  return &r->neg[k];
}

static void fill_to(int64_t i) {
  /* cells after the program: [k] = crz([k-1], [k-2]) */
  if (i >= R[0].npos) grow(&R[0].pos, &R[0].npos, i);
  for (; filled <= i; filled++) R[0].pos[filled] = crz(R[0].pos[filled - 1], R[0].pos[filled - 2]);
}

static V *cell(V a) {
  a = norm(a);
  if (a.t == 0 && a.d >= filled) fill_to(a.d);
  V *p = slot(a);
  if (p->d == INT64_MIN) {
    /* never-written non-natural cell: continue the 6-periodic fill pattern */
    int64_t base_i = proglen + 12;
    fill_to(base_i + 6);
    int64_t idx = ((a.d % 6) + 6) % 6;
    int64_t k = base_i + ((idx - base_i) % 6 + 6) % 6;
    V v = R[0].pos[k];
    p = slot(a);
    *p = v;
  }
  return p;
}

/* ---- I/O ---- */
static V input(void) {
  int ch = getchar();
  if (ch == EOF) return (V){0, 2};
  if (ch == '\n') return (V){-1, 2};
  if (!bytemode && ch >= 0x80) {
    int n = ch >= 0xF0 ? 3 : ch >= 0xE0 ? 2 : ch >= 0xC0 ? 1 : 0;
    int cp = ch & (0x3F >> n);
    for (int k = 0; k < n; k++) { int c2 = getchar(); if (c2 == EOF) break; cp = (cp << 6) | (c2 & 0x3F); }
    ch = cp;
  }
  return (V){ch, 0};
}

static void output(V v) {
  v = norm(v);
  if (v.t == 2 && v.d == -1) { putchar('\n'); return; }
  if (v.t != 0) { fprintf(stderr, "mu: output of reserved value\n"); exit(3); }
  int64_t cp = v.d;
  if (bytemode || cp < 0x80) { putchar((int)(cp & 0xFF)); return; }
  if (cp < 0x800) { putchar(0xC0 | (int)(cp >> 6)); putchar(0x80 | (int)(cp & 0x3F)); }
  else if (cp < 0x10000) { putchar(0xE0 | (int)(cp >> 12)); putchar(0x80 | (int)((cp >> 6) & 0x3F)); putchar(0x80 | (int)(cp & 0x3F)); }
  else { putchar(0xF0 | (int)(cp >> 18)); putchar(0x80 | (int)((cp >> 12) & 0x3F)); putchar(0x80 | (int)((cp >> 6) & 0x3F)); putchar(0x80 | (int)(cp & 0x3F)); }
}

int main(int argc, char **argv) {
  int stats = 0;
  const char *path = NULL;
  for (int i = 1; i < argc; i++) {
    if (!strcmp(argv[i], "-b")) bytemode = 1;
    else if (!strcmp(argv[i], "-s")) stats = 1;
    else path = argv[i];
  }
  if (!path) { fprintf(stderr, "usage: mu [-b] [-s] program.mu\n"); return 1; }
  P3[0] = 1;
  for (int i = 1; i <= 40; i++) P3[i] = P3[i - 1] * 3;

  FILE *f = fopen(path, "rb");
  if (!f) { perror(path); return 1; }
  int ch;
  int64_t n = 0;
  while ((ch = fgetc(f)) != EOF) {
    if (ch == ' ' || ch == '\t' || ch == '\n' || ch == '\r') continue;
    if (ch < 33 || ch > 126) { fprintf(stderr, "mu: invalid character in program\n"); return 2; }
    int op = (int)((ch + n) % 94);
    if (op != 4 && op != 5 && op != 23 && op != 39 && op != 40 && op != 62 && op != 68 && op != 81) {
      fprintf(stderr, "mu: invalid instruction at %lld\n", (long long)n);
      return 2;
    }
    V *p = slot((V){n, 0});
    p->d = ch; p->t = 0;
    n++;
  }
  fclose(f);
  if (n < 2) { fprintf(stderr, "mu: program too short\n"); return 2; }
  proglen = n;
  filled = n;

  V a = {0, 0}, c = {0, 0}, d = {0, 0};
  uint64_t steps = 0;
  for (;;) {
    V *pc = cell(c);
    V instr = *pc;
    if (instr.t != 0 || instr.d < 33 || instr.d > 126) { fprintf(stderr, "mu: invalid instruction at c\n"); return 3; }
    steps++;
    int op = mod94((V){c.d + instr.d, c.t});
    switch (op) {
    case 4: /* jmp */
      c = *cell(d);
      pc = cell(c);
      break;
    case 5: output(a); break;
    case 23: a = input(); break;
    case 39: { V *pd = cell(d); a = *pd = rot(*pd); break; }
    case 40: {
      d = *cell(d);
      int w = width(d);
      if (w > maxdwidth) {
        maxdwidth = w;
        if (2 * w > rotwidth) rotwidth = 2 * w;
        if (rotwidth > 39) { fprintf(stderr, "mu: rotation width too large\n"); return 3; }
      }
      break;
    }
    case 62: { V *pd = cell(d); a = *pd = crz(a, *pd); break; }
    case 81: goto done;
    default: break; /* nop */
    }
    if (pc->t == 0 && pc->d >= 33 && pc->d <= 126) pc->d = XLAT2[pc->d - 33];
    c.d++; c = norm(c);
    d.d++; d = norm(d);
  }
done:
  fflush(stdout);
  if (stats) fprintf(stderr, "mu: %llu steps, rotwidth %d\n", (unsigned long long)steps, rotwidth);
  return 0;
}
