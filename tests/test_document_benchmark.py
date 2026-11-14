from benchmark.document_benchmark import norm, pair_set, prf


def test_normalization():
    assert norm("  Võ   Nguyên Giáp ") == "võ nguyên giáp"


def test_pair_set_for_clusters():
    assert pair_set([["a", "b", "c"], ["d", "e"]]) == {
        ("a", "b"), ("a", "c"), ("b", "c"), ("d", "e")
    }


def test_pairwise_metrics():
    assert prf({("a", "b"), ("a", "c")}, {("a", "b"), ("b", "c")}) == {
        "tp": 1, "fp": 1, "fn": 1, "precision": 0.5, "recall": 0.5, "f1": 0.5
    }
