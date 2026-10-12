(defun fib1 (n) (
    if [n < 2]
        n
        [(fib1 [n - 1]) + (fib1 [n - 2])]))
(fib1 6)
