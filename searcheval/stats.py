"""Paired significance testing for A/B search comparisons.

Both engines answer the *same* queries, so per-query scores are paired. That
lets us test the mean per-query difference with far less variance than an
unpaired test. We use a paired bootstrap over the per-query differences, which
is distribution-free (IR metrics are skewed and bounded, so a t-test's normality
assumption is shaky) and needs no third-party dependency.

Decision rule: if the 95% CI of ``mean(a - b)`` excludes 0, the difference is
significant at that level. Reporting the interval (not just a p-value) also shows
effect size and whether a category is a genuine tie vs. merely underpowered.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import fmean


@dataclass(frozen=True)
class DiffCI:
    mean_diff: float  # mean(a - b); positive means `a` scores higher
    lo: float
    hi: float
    n: int

    @property
    def significant(self) -> bool:
        """CI excludes 0 -> difference is unlikely to be noise at this level."""
        return self.lo > 0 or self.hi < 0


def paired_bootstrap_ci(a: list[float], b: list[float], *, iters: int = 10000,
                        alpha: float = 0.05, seed: int = 0) -> DiffCI:
    """Bootstrap CI for the paired mean difference ``mean(a - b)``.

    ``a[i]`` and ``b[i]`` MUST be the two engines' scores for the same query.
    """
    if len(a) != len(b):
        raise ValueError("paired inputs must have equal length")
    if not a:
        raise ValueError("need at least one paired observation")

    diffs = [x - y for x, y in zip(a, b)]
    n = len(diffs)
    rng = random.Random(seed)
    means = sorted(fmean(rng.choices(diffs, k=n)) for _ in range(iters))
    lo = means[int((alpha / 2) * iters)]
    hi = means[min(iters - 1, int((1 - alpha / 2) * iters))]
    return DiffCI(mean_diff=fmean(diffs), lo=lo, hi=hi, n=n)
