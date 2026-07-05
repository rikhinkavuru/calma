"""Leakage detection: duplicate-row and homology (near-duplicate sequence) leakage — verify the data, not
just the number."""
import random

from core import leakage as L


def test_split_discovery_skips_test_fixture_dirs(tmp_path):
    # A train/test split under tests/fixtures/ (or examples/, sample/, …) is unit-test scaffolding, not the
    # repo's real evaluation data — scanning it produced a false leakage alarm (gfmbench-api: an 8-row
    # tests/fixtures split with 100% overlap flagged "contaminated"). Split discovery must skip those dirs.
    fx = tmp_path / "tests" / "fixtures" / "data" / "toy"
    fx.mkdir(parents=True)
    (fx / "train.csv").write_text("seq,label\nAAAA,0\nBBBB,1\n")
    (fx / "test.csv").write_text("seq,label\nAAAA,0\nBBBB,1\n")   # 100% overlap, but it's a fixture
    assert L._split_pairs(str(tmp_path)) == {}
    # a REAL split at the repo root is still discovered (and would fire leakage)
    (tmp_path / "d_train.csv").write_text("seq,label\nAAAA,0\n")
    (tmp_path / "d_test.csv").write_text("seq,label\nAAAA,0\n")
    assert "d" in L._split_pairs(str(tmp_path))


def test_clean_split_no_leakage():
    rng = random.Random(1)
    rows = [[rng.randint(0, 100000), rng.randint(0, 100000)] for _ in range(400)]
    train, test = rows[:300], rows[300:]
    assert L.exact_overlap(train, test)["overlap_frac"] == 0.0
    assert L.check_leakage(train, test) == []


def test_duplicate_row_leakage_detected():
    rng = random.Random(2)
    train = [[rng.randint(0, 40), rng.randint(0, 40)] for _ in range(300)]
    test = train[:60] + [[10 ** 6 + i, i] for i in range(40)]   # 60% of test leaked verbatim from train
    f = L.check_leakage(train, test)
    assert f and f[0]["kind"] == "duplicate-row leakage" and f[0]["invalidating"]
    assert f[0]["magnitude"] > 0.5


def _seq(rng, n=80):
    return "".join(rng.choice("ACGT") for _ in range(n))


def test_homology_leakage_detected():
    rng = random.Random(3)
    train = [_seq(rng) for _ in range(120)]
    test = []
    for s in train[:50]:                       # mutated copies of train sequences (homologous)
        s = list(s)
        s[rng.randint(0, len(s) - 1)] = rng.choice("ACGT")
        test.append("".join(s))
    test += [_seq(rng) for _ in range(50)]      # + novel
    findings = L.check_leakage(train, test, sequences=True)
    assert any(x["kind"] == "homology leakage" for x in findings)


def test_homology_clean_on_novel_sequences():
    rng = random.Random(4)
    train = [_seq(rng) for _ in range(100)]
    test = [_seq(rng) for _ in range(100)]      # all novel → no homology
    assert L.homology_overlap(train, test)["overlap_frac"] < 0.05
    assert L.check_leakage(train, test, sequences=True) == []


def test_seq_column_skips_id_index_split_metadata():
    """Regression (Phase 2 mypy fix): _seq_column must skip label/id/index/split metadata columns when no
    recognized sequence-name column is present. A module-level name collision (_LABEL_COLS was defined twice)
    silently rebound this skip-list to the label-name tuple, so id/index/split stopped being skipped and an id
    column could be mistaken for the sequence — quietly weakening homology-leakage detection."""
    header = ["id", "index", "split", "mystery_feature", "label"]
    assert L._seq_column(header) == 3                        # mystery_feature, not the id column at index 0
    assert L._seq_column(["id", "sequence", "label"]) == 1   # a recognized sequence name still wins directly
