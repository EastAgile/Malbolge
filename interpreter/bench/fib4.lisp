(defun fib4 (n) (#0 (
    iterateN n (lambda (x) (
        tie (#1 x) [(#0 x) + (#1 x)])) '(0 1))))
(fib4 6)
