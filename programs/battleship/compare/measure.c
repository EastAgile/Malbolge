/*
 * measure - run a command with stdin from a file and report its wall time and
 * peak resident memory.  A tiny C parent keeps the child's inherited memory
 * negligible, which a Python parent would not (a forked child is charged for
 * the parent's pages until it execs).
 *
 * Usage: measure REPORT INPUT CMD [ARGS...]
 * Writes "SECONDS MAXRSS_KB" to the file REPORT; the command's stdout and
 * stderr pass through.
 */
#include <fcntl.h>
#include <stdio.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

int main(int argc, char **argv) {
  if (argc < 4) { fprintf(stderr, "usage: measure REPORT INPUT CMD [ARGS...]\n"); return 2; }
  struct timespec t0, t1;
  clock_gettime(CLOCK_MONOTONIC, &t0);
  pid_t pid = fork();
  if (pid == 0) {
    int fd = open(argv[2], O_RDONLY);
    if (fd < 0 || dup2(fd, 0) < 0) { perror(argv[2]); _exit(127); }
    execvp(argv[3], argv + 3);
    perror(argv[3]);
    _exit(127);
  }
  int status;
  struct rusage ru;
  if (wait4(pid, &status, 0, &ru) < 0) { perror("wait4"); return 2; }
  clock_gettime(CLOCK_MONOTONIC, &t1);
  FILE *rep = fopen(argv[1], "w");
  if (!rep) { perror(argv[1]); return 2; }
  fprintf(rep, "%f %ld\n", (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9, ru.ru_maxrss);
  fclose(rep);
  return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
