"""Paired bootstrap CI: these guard the decision rule that drives every
'is this difference real?' claim in the report.
"""

import pytest

from searcheval.stats import DiffCI, paired_bootstrap_ci


def test_clear_positive_difference_is_significant():
    # a is uniformly 0.5 better than b on every query -> CI well above 0.
    a = [0.9, 0.8, 0.85, 0.95, 0.7, 0.9, 0.88, 0.92]
    b = [0.4, 0.3, 0.35, 0.45, 0.2, 0.4, 0.38, 0.42]
    ci = paired_bootstrap_ci(a, b, seed=1)
    assert ci.mean_diff > 0.4
    assert ci.lo > 0 and ci.significant


def test_clear_negative_difference_is_significant():
    a = [0.1, 0.2, 0.15, 0.05]
    b = [0.9, 0.8, 0.85, 0.95]
    ci = paired_bootstrap_ci(a, b, seed=1)
    assert ci.mean_diff < 0 and ci.hi < 0 and ci.significant


def test_no_difference_is_not_significant():
    # Identical per-query scores -> every diff is 0 -> CI is [0, 0], not significant.
    a = [0.5, 0.6, 0.7, 0.4, 0.55]
    ci = paired_bootstrap_ci(a, list(a), seed=1)
    assert ci.mean_diff == 0.0
    assert ci.lo == 0.0 and ci.hi == 0.0
    assert not ci.significant


def test_tiny_noisy_difference_is_not_significant():
    # Symmetric noise around 0 -> CI should straddle 0.
    a = [0.5, 0.9, 0.1, 0.6, 0.4, 0.8, 0.2, 0.55]
    b = [0.9, 0.5, 0.6, 0.1, 0.8, 0.4, 0.55, 0.2]
    ci = paired_bootstrap_ci(a, b, seed=1)
    assert ci.lo < 0 < ci.hi
    assert not ci.significant


def test_deterministic_for_fixed_seed():
    a = [0.3, 0.7, 0.5, 0.9, 0.2]
    b = [0.1, 0.4, 0.6, 0.3, 0.5]
    assert paired_bootstrap_ci(a, b, seed=7) == paired_bootstrap_ci(a, b, seed=7)


def test_mismatched_lengths_rejected():
    with pytest.raises(ValueError):
        paired_bootstrap_ci([0.1, 0.2], [0.1], seed=1)


def test_empty_rejected():
    with pytest.raises(ValueError):
        paired_bootstrap_ci([], [], seed=1)


def test_diffci_significance_property():
    assert DiffCI(0.1, 0.02, 0.2, 10).significant
    assert DiffCI(-0.1, -0.2, -0.02, 10).significant
    assert not DiffCI(0.0, -0.05, 0.05, 10).significant
