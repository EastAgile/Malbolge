/*
 * grep.c - a streaming grep, written in C to be compiled to Malbolge Unshackled
 *          through the ELVM toolchain (8cc -> elc -hell -> LMFAO).
 *
 * Malbolge has no argv and no files: the only channels are stdin and stdout.
 * So the launcher (grep.mal) encodes the request as a short header on stdin,
 * ahead of the data to search:
 *
 *     line 1   flag letters, e.g. "ivn", or empty      (terminated by '\n')
 *     line 2   the pattern                             (terminated by '\n')
 *     rest     the input to search, line by line
 *
 * The program reads the two header lines, then streams the input one line at a
 * time through a fixed-size line buffer. Memory use is therefore bounded and
 * independent of how much input is piped in: any number of lines, each up to
 * MAXLINE-1 bytes (longer lines are matched and printed on their first
 * MAXLINE-1 bytes).
 *
 * Supported pattern syntax (a documented subset of POSIX BRE):
 *     literal characters        c
 *     any character             .
 *     zero or more              X*        (X is a single atom below)
 *     start / end anchors       ^   $
 *     character class           [abc] [a-z] [^0-9]
 *     escape                    \c        (match c literally)
 * Supported flags: -i (ignore case) -v (invert) -n (line numbers) -c (count).
 */

#include <stdio.h>

#define MAXLINE 4096
#define MAXPAT 1024

static char g_pat[MAXPAT];
static char buf[MAXLINE];

static int f_ignorecase = 0;
static int f_invert = 0;
static int f_number = 0;
static int f_count = 0;

static int lc(int c) {
  if (c >= 'A' && c <= 'Z') return c + ('a' - 'A');
  return c;
}

static int eqc(int a, int b) {
  if (f_ignorecase) return lc(a) == lc(b);
  return a == b;
}

/* end index of the atom that starts at g_pat[pi] */
static int atom_end(int pi) {
  int c = g_pat[pi];
  if (c == '\\') return (g_pat[pi + 1] ? pi + 2 : pi + 1);
  if (c == '[') {
    int j = pi + 1;
    if (g_pat[j] == '^') j++;
    if (g_pat[j] == ']') j++; /* a ] right after [ or [^ is a literal ] */
    while (g_pat[j] && g_pat[j] != ']') j++;
    if (g_pat[j] == ']') j++;
    return j;
  }
  return pi + 1;
}

/* does the atom g_pat[pi..ae) match the single character ch? */
static int atom_matches(int pi, int ae, int ch) {
  int c = g_pat[pi];
  if (c == '.') return 1;
  if (c == '\\') return eqc(g_pat[pi + 1], ch);
  if (c == '[') {
    int j = pi + 1;
    int neg = 0;
    int hit = 0;
    if (g_pat[j] == '^') { neg = 1; j++; }
    while (j < ae - 1) {
      if (g_pat[j + 1] == '-' && j + 2 < ae - 1) {
        int loa = g_pat[j], hia = g_pat[j + 2];
        int x = f_ignorecase ? lc(ch) : ch;
        if ((f_ignorecase ? lc(loa) : loa) <= x && x <= (f_ignorecase ? lc(hia) : hia)) hit = 1;
        j += 3;
      } else {
        if (eqc(g_pat[j], ch)) hit = 1;
        j++;
      }
    }
    return neg ? !hit : hit;
  }
  return eqc(c, ch);
}

static int matchhere(int pi, int ti);

/* match zero or more of the atom at pi (ending at ae), then the rest at ae... */
static int matchstar(int pi, int ae, int ti) {
  int rest = ae + 1; /* skip the '*' */
  for (;;) {
    if (matchhere(rest, ti)) return 1;
    if (buf[ti] == 0 || !atom_matches(pi, ae, buf[ti])) return 0;
    ti++;
  }
}

static int matchhere(int pi, int ti) {
  int ae;
  if (g_pat[pi] == 0) return 1;
  if (g_pat[pi] == '$' && g_pat[pi + 1] == 0) return buf[ti] == 0;
  ae = atom_end(pi);
  if (g_pat[ae] == '*') return matchstar(pi, ae, ti);
  if (buf[ti] != 0 && atom_matches(pi, ae, buf[ti])) return matchhere(ae, ti + 1);
  return 0;
}

static int matchline(void) {
  int pi = 0;
  int ti = 0;
  if (g_pat[0] == '^') return matchhere(1, 0);
  do {
    if (matchhere(pi, ti)) return 1;
  } while (buf[ti++] != 0);
  return 0;
}

static void print_uint(int n) {
  if (n >= 10) print_uint(n / 10);
  putchar('0' + n % 10);
}

static int read_line(char *dst, int cap) {
  /* read until '\n' or EOF; returns -1 at EOF with no chars, else length.
   * always consumes to end of line even if the buffer fills. */
  int n = 0;
  int c = getchar();
  if (c == EOF) return -1;
  while (c != EOF && c != '\n') {
    if (n < cap - 1) dst[n++] = (char)c;
    c = getchar();
  }
  dst[n] = 0;
  return n;
}

int main(void) {
  int i, n, lineno = 0, count = 0;

  /* header line 1: flags */
  n = read_line(buf, MAXLINE);
  if (n > 0) {
    for (i = 0; i < n; i++) {
      int c = buf[i];
      if (c == 'i') f_ignorecase = 1;
      else if (c == 'v') f_invert = 1;
      else if (c == 'n') f_number = 1;
      else if (c == 'c') f_count = 1;
    }
  }

  /* header line 2: pattern */
  n = read_line(g_pat, MAXPAT);
  if (n < 0) g_pat[0] = 0;

  /* stream the body */
  for (;;) {
    n = read_line(buf, MAXLINE);
    if (n < 0) break;
    lineno++;
    int m = matchline();
    if (f_invert) m = !m;
    if (m) {
      count++;
      if (!f_count) {
        if (f_number) { print_uint(lineno); putchar(':'); }
        for (i = 0; buf[i]; i++) putchar(buf[i]);
        putchar('\n');
      }
    }
  }
  if (f_count) { print_uint(count); putchar('\n'); }
  return 0;
}
