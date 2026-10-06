"""Tiny evaluator for the subset of FFmpeg expression syntax the music envelope uses."""
import re


def evaluate(expr: str, **variables: float) -> float:
    def clip(x, lo, hi):
        return max(lo, min(hi, x))
    def between(x, lo, hi):
        return 1.0 if lo <= x <= hi else 0.0
    safe = {"max": max, "min": min, "clip": clip, "between": between, "pow": pow, **variables}
    return float(eval(re.sub(r"[^0-9a-zA-Z_+\-*/(),. ]", "", expr), {"__builtins__": {}}, safe))
