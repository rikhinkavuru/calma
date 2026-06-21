"""calma.contamination_checks - eval / benchmark contamination on the findings rail (dimension
"contamination", an EXEC dim), called from calma._assemble_ledger like leakage_checks. Broader than
leakage's train/test overlap: the EVALUATION ITSELF is contaminated by the model's pretraining / a
known public benchmark. Most salient for LLM and benchmark evals.

What it catches, deterministic arithmetic only (no model):
  - benchmark / test-set MEMORIZATION - an eval item whose content hash is present in a declared corpus
    manifest (the pretraining / known-corpus hashes). A set/hash overlap, like leakage's row hash but
    eval-vs-corpus. Authoritative.
  - NEAR-DUPLICATE contamination - an eval item whose minhash/shingle Jaccard against the corpus is at
    or above a threshold (a paraphrase / reformat of a corpus item). LABELED HEURISTIC -> soft.

The verdict follows the claim's own scope (mirrors the leakage OOS scope-guard, here keyed on a HELD-OUT
/ ZERO-SHOT / UNCONTAMINATED assertion): exact eval-in-corpus overlap on a held-out claim -> INVALIDATED;
a claim that explicitly allows contamination (few-shot / in-context / fine-tuned-on) -> CAVEAT; an
indeterminate scope -> CAN'T-CONFIRM ("declare whether the eval is held-out / zero-shot"). A heuristic
near-dup is always a CAVEAT, never invalidating. REFUTED is never manufactured here.

Activates ONLY when a `corpus:{manifest}` block is declared - the known-corpus is never guessed. Pure
stdlib (`hashlib` for exact; a stdlib minhash over word/char shingles for near-dup; no new deps).

Library: run_checks(contract, base, claim_id, claim_text) -> [finding,...];
apply_validity(claims, findings, contract, claim_text); contamination_status(contract, claim_text).
"""
import csv
import hashlib
import os
import re
import unicodedata

import pathsafe as PS

# near-duplicate minhash configuration (deterministic; stdlib only).
_MINHASH_K = 32          # number of hash functions in the signature
_SHINGLE_N = 3           # word-shingle size (falls back to char-shingles for short items)
_NEARDUP_J = 0.80        # estimated-Jaccard threshold at/above which an item is a near-duplicate
# LSH banding: split the K-minhash signature into B bands of R rows (B*R == K). Two items are CANDIDATE
# near-dups iff they agree on all R values of at least one band - so near-dup is O(eval + corpus), not the
# O(eval x corpus) all-pairs scan (which replaces the old blanket _NEARDUP_CAP corpus truncation with a
# per-band degenerate-cluster bound - see _MAX_BAND - so a real large corpus is fully covered but an
# adversarial near-identical one can't force O(corpus) candidates per item). B=8,R=4 gives a candidate
# crossover ~0.60, so the LSH banding loses ZERO recall vs the all-pairs scan (measured: 100% of the
# pairs all-pairs flags, at every Jaccard bin) while pruning ~99% of unrelated pairs. The absolute
# detection rate near the 0.80 boundary is set by the 32-hash MinHash ESTIMATE variance (shared with
# all-pairs - not a banding effect): est-Jaccard tracks true-Jaccard with ~+-0.05 noise, so a true-0.79
# pair may estimate below 0.80 and miss - acceptable, since near-dup is a soft, never-invalidating
# heuristic. The final decision is the exact estimated Jaccard >= _NEARDUP_J on the candidates; LSH only
# changes WHICH pairs are compared, never the verdict.
_LSH_BANDS = 8
_LSH_ROWS = _MINHASH_K // _LSH_BANDS
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")

# DoS bounds (this runs as a guardrail on attacker-authored contracts + files). The EXACT-hash check
# stays uncapped and full-content (it is the authoritative path - never truncate it, or a shared prefix
# would forge a false memorization hit). Only the SOFT near-dup pass is bounded: caps make it near-linear
# even on adversarial near-identical corpora (which would otherwise collapse into one giant LSH band).
_MAX_LINES = 2_000_000      # max manifest / eval rows read into memory
_MAX_SHINGLES = 4096        # max shingles hashed per item (bounds _signature cost; near-dup only)
_MAX_BAND = 512             # an LSH band with more members than this is degenerate (attack / mega-cluster)
                            # -> skipped for candidate generation, bounding candidates/item to BANDS*MAX_BAND


def _safe_join(base, rel):
    """Resolve rel under base and refuse anything that escapes it (absolute path, .. traversal, symlink
    out). Delegates to the shared guard (pathsafe) so there is ONE audited containment implementation
    (L1) - a detector must never be coerced into reading a file outside the contract base (path-traversal
    / file-exfiltration via an attacker-authored verify.yaml)."""
    return PS.safe_join(base, rel)

_HELDOUT_RE = re.compile(
    r"held.?out|zero.?shot|uncontaminat|unseen|out.?of.?distribution|\boos\b|not (in|seen in) (the )?"
    r"(training|pre.?training|corpus)|clean (eval|test|benchmark)|never (seen|trained)|"
    r"decontaminat|test[\s-]?set|generaliz", re.I)
_ALLOWED_RE = re.compile(
    r"few.?shot|in.?context|fine.?tun|trained on|seen during training|memoriz|in.?sample|"
    r"closed.?book.*train|with (the )?answer", re.I)


# ---- io ----------------------------------------------------------------------

def _read(path):
    if not PS.within_cap(path):
        return [], []  # FIFO/socket/device: never open() (would block); treated as unreadable
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            rd = csv.reader(fh)
            header = next(rd, [])
            rows = []
            for r in rd:
                rows.append(r)
                if len(rows) >= _MAX_LINES:  # bound memory on a hostile eval table
                    break
        return header, rows
    except (OSError, StopIteration, csv.Error):
        return [], []


def _norm_text(s):
    """Whitespace-canonical, NFKC-normalized text - so trivial reformatting and Unicode COMPATIBILITY
    variants (fullwidth digits/letters, ligatures, presentation forms) don't dodge the exact-
    memorization hash. Stays content-exact otherwise (no case-folding / token surgery). NFKC does NOT
    fold cross-script CONFUSABLES (e.g. Latin 'o' vs Cyrillic 'о' are distinct codepoints): a
    deliberate homoglyph substitution still hashes differently - documented, not silently claimed."""
    return " ".join(unicodedata.normalize("NFKC", str(s)).split())


def _content_hash(s):
    return hashlib.sha256(_norm_text(s).encode("utf-8")).hexdigest()


def _corpus(contract):
    return contract.get("corpus") if isinstance(contract.get("corpus"), dict) else None


def _load_corpus(contract, base):
    """The known/pretraining corpus as (hash_set, text_items). A manifest line that is already a 64-hex
    sha256 is taken as a precomputed content hash (no text for near-dup); any other line is raw content
    -> hashed AND kept as text for the near-dup pass. Returns (set, [str]) or (None, None)."""
    cp = _corpus(contract)
    if not cp or not cp.get("manifest"):
        return None, None
    try:
        path = _safe_join(base, cp["manifest"])
        if not PS.within_cap(path):  # FIFO/device: never open() (would block) -> declared-but-unreadable
            raise ValueError("corpus manifest is not a regular file")
        hashes, texts, n = set(), [], 0
        with open(path, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                s = ln.strip()
                if not s:
                    continue
                if _HEX64.match(s):
                    # a precomputed content hash. ALSO store its own content-hash so a literal 64-hex
                    # eval ITEM (a git SHA / hex digest in the data) still matches a same-string corpus
                    # line - the eval side always hashes its text, so the hex-as-hash path alone would
                    # silently miss that overlap (a false-clean on the authoritative check).
                    hashes.add(s.lower())
                    hashes.add(_content_hash(s))
                else:
                    hashes.add(_content_hash(s))
                    texts.append(s)
                n += 1
                if n >= _MAX_LINES:
                    break
    except (OSError, ValueError):  # ValueError: path escapes base
        return None, None
    if not hashes:
        return None, None
    return hashes, texts


def _eval_table(contract, base):
    """The (header, rows) the eval items live in: a declared split.test, else a declared corpus.eval
    path, else the headline metric's artifact."""
    def _rd(rel):
        try:
            return _read(_safe_join(base, rel))
        except ValueError:  # path escapes base
            return [], []
    sp = contract.get("split") or {}
    if sp.get("test"):
        h, r = _rd(sp["test"])
        if h:
            return h, r
    cp = _corpus(contract) or {}
    if cp.get("eval"):
        h, r = _rd(cp["eval"])
        if h:
            return h, r
    mets = contract.get("metrics") or []
    head = next((m for m in mets if m.get("headline")), mets[0] if mets else None)
    if head and head.get("artifact"):
        return _rd(head["artifact"])
    return [], []


def _eval_items(contract, base):
    """The eval items as text: the declared corpus.eval_col, else the whole row joined canonically.
    Returns a list of strings (one per eval row)."""
    cp = _corpus(contract) or {}
    header, rows = _eval_table(contract, base)
    if not header or not rows:
        return []
    col = cp.get("eval_col")
    if col and col in header:
        i = header.index(col)
        return [(r[i] if i < len(r) else "") for r in rows]
    # no text column declared: hash the canonical row (sorted columns) as the item content
    order = sorted(range(len(header)), key=lambda j: header[j])
    return ["\x1f".join("%s=%s" % (header[j], r[j] if j < len(r) else "") for j in order) for r in rows]


# ---- minhash (stdlib, deterministic) ----------------------------------------

def _shingles(text):
    """Word 3-shingles; for short items (<_SHINGLE_N words) fall back to character 4-grams so every item
    has a non-empty shingle set. The shingle count is capped (_MAX_SHINGLES) so a pathologically long
    item can't blow up _signature - this is the soft near-dup path, so the cap only ever under-flags."""
    words = _norm_text(text).lower().split()
    if len(words) >= _SHINGLE_N:
        m = min(len(words) - _SHINGLE_N + 1, _MAX_SHINGLES)
        return {" ".join(words[i:i + _SHINGLE_N]) for i in range(m)}
    s = _norm_text(text).lower()
    if len(s) >= 4:
        m = min(len(s) - 3, _MAX_SHINGLES)
        return {s[i:i + 4] for i in range(m)}
    return {s} if s else set()


def _signature(text):
    """A K-length minhash signature: for each of K salts, the min sha256(salt|shingle) over the item's
    shingles. Deterministic (hashlib), pure stdlib. None when the item has no shingles."""
    sh = _shingles(text)
    if not sh:
        return None
    sig = []
    for k in range(_MINHASH_K):
        salt = b"calma-minhash-%d:" % k
        sig.append(min(int.from_bytes(hashlib.sha256(salt + s.encode("utf-8")).digest()[:8], "big")
                       for s in sh))
    return tuple(sig)


def _est_jaccard(a, b):
    return sum(1 for x, y in zip(a, b) if x == y) / float(_MINHASH_K)


def _lsh_bands(sig):
    """The B band-keys of a signature - each (band_index, the R minhash values of that band). Two items
    share a band (an LSH candidate) iff they agree on all R values of some band."""
    return [(b, sig[b * _LSH_ROWS:(b + 1) * _LSH_ROWS]) for b in range(_LSH_BANDS)]


# ---- detectors --------------------------------------------------------------

def _finding(claim_id, kind, severity, vclass, magnitude, locator, unblock):
    return {
        "id": "f-%s-contam-%s" % (claim_id, kind), "claim_id": claim_id, "dimension": "contamination",
        "severity": severity, "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": locator, "unblock": unblock,
        "reverify": {"kind": "artifact-recheck", "source": "corpus",
                     "expected": "no eval item present in (or near-duplicate of) the declared corpus"},
        "validity_class": vclass, "contamination_kind": kind, "magnitude": magnitude,
    }


def _indeterminate_finding(claim_id, manifest):
    """A contamination check was DECLARED (corpus.manifest set) but its corpus could not be read
    (missing file / decode error / path-escape). A declared check that cannot RUN is CAN'T-CONFIRM,
    never a silent 'checked' (clean) - else a broken corpus path launders a held-out claim."""
    return {
        "id": "f-%s-contam-indeterminate" % claim_id, "claim_id": claim_id,
        "dimension": "contamination", "severity": "minor", "status": "open",
        "confidence": "deterministic", "fixable_by": "author",
        "locator": "declared corpus manifest could not be read: %r" % manifest,
        "unblock": "the contamination check was declared but its corpus manifest could not be read "
                   "(missing file / unreadable / path-escape) - fix corpus.manifest and re-verify",
        "reverify": {"kind": "artifact-recheck", "source": "corpus",
                     "expected": "the declared corpus manifest is readable"},
        "validity_class": "indeterminate", "contamination_indeterminate": True, "magnitude": 1.0,
    }


def check_exact(contract, base, claim_id="c1"):
    """Exact memorization: eval items whose content hash is in the corpus. Authoritative."""
    corpus_hashes, _ = _load_corpus(contract, base)
    items = _eval_items(contract, base)
    if not corpus_hashes or not items:
        return None
    hits = sum(1 for it in items if _content_hash(it) in corpus_hashes)
    if hits == 0:
        return None
    mag = hits / len(items)
    return _finding(
        claim_id, "memorization", "blocker", "authoritative", mag,
        "eval contamination: %d of %d eval items (%.1f%%) are present in the declared corpus - the model "
        "may have seen the answers during training, so the score is not a held-out measurement"
        % (hits, len(items), 100 * mag),
        "remove the contaminated items from the eval (decontaminate against the corpus), then re-evaluate")


def check_near_dup(contract, base, claim_id="c1"):
    """Near-duplicate contamination via minhash/shingle Jaccard. LABELED HEURISTIC -> soft. Skipped when
    the corpus carries no text (pre-hashed manifest) or there is nothing to compare."""
    corpus_hashes, corpus_texts = _load_corpus(contract, base)
    if not corpus_texts:
        return None
    items = _eval_items(contract, base)
    if not items:
        return None
    # build the LSH band index over the corpus signatures: band-key -> corpus-sig indices (one O(corpus)
    # pass). An eval item only compares against corpus items that share a band - near-linear for normal
    # input. DoS guard: a band that accumulates more than _MAX_BAND members is DEGENERATE (an attacker's
    # near-identical-bodied corpus, or a mega-cluster) - drop it from candidate generation so candidates
    # per eval item stay bounded by BANDS*_MAX_BAND instead of collapsing to O(corpus).
    index, corpus_sigs = {}, []
    for t in corpus_texts:
        s = _signature(t)
        if s is None:
            continue
        ci = len(corpus_sigs)
        corpus_sigs.append(s)
        for band in _lsh_bands(s):
            index.setdefault(band, []).append(ci)
    if not corpus_sigs:
        return None
    degenerate = {band for band, members in index.items() if len(members) > _MAX_BAND}
    near = 0
    for it in items:
        if _content_hash(it) in corpus_hashes:
            continue  # an exact hit is the exact detector's job, not a near-dup
        sig = _signature(it)
        if sig is None:
            continue
        cands = set()
        for band in _lsh_bands(sig):
            if band not in degenerate:
                cands.update(index.get(band, ()))
        if any(_est_jaccard(sig, corpus_sigs[ci]) >= _NEARDUP_J for ci in cands):
            near += 1
    if near == 0:
        return None
    mag = near / len(items)
    return _finding(
        claim_id, "near-duplicate", "minor", "soft", mag,
        "possible eval contamination (HEURISTIC): %d of %d eval items (%.1f%%) are near-duplicates "
        "(minhash Jaccard >= %.2f) of corpus items - likely paraphrases / reformats of training data"
        % (near, len(items), 100 * mag, _NEARDUP_J),
        "manually confirm these items are genuinely held-out, or remove them and re-evaluate")


def run_checks(contract, base, claim_id="c1", claim_text=None):
    """All contamination catches against one engagement. SILENT (returns []) unless a `corpus:{manifest}`
    block is declared. Fail-soft: any check that errors is skipped."""
    cp = _corpus(contract)
    if not cp:
        return []
    # declared-but-unreadable: a corpus block points at a manifest that can't be read. NOT a clean
    # scan - return an indeterminate finding so it reads as CAN'T-CONFIRM, never a silent 'checked'.
    if cp.get("manifest"):
        _hashes, _texts = _load_corpus(contract, base)
        if _hashes is None:  # OSError / decode error / path-escape (an empty-readable corpus is set())
            return [_indeterminate_finding(claim_id, cp.get("manifest"))]
    out = []
    for fn in (lambda: check_exact(contract, base, claim_id),
               lambda: check_near_dup(contract, base, claim_id)):
        try:
            f = fn()
        except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
            f = None
        if f:
            out.append(f)
    return out


def family_status(contract, findings):
    """Honest scope.families.contamination status."""
    if not _corpus(contract):
        return "not-applicable"
    if any(f.get("contamination_indeterminate") for f in findings):
        return "indeterminate"  # declared but the corpus couldn't be read - not a clean scan
    return "flagged" if any(f.get("contamination_kind") for f in findings) else "checked"


# ---- claim-scope guard + verdict promotion ----------------------------------

def contamination_status(contract, claim_text):
    """Does the claim assert a HELD-OUT / ZERO-SHOT / UNCONTAMINATED result (the thing contamination
    would invalidate)? 'held-out' | 'allowed' | 'indeterminate'. Drives the scope-guard: INVALIDATED
    requires a POSITIVE held-out assertion; a claim that explicitly allows contamination degrades to a
    caveat; anything ambiguous degrades to CAN'T-CONFIRM - never a manufactured INVALIDATED."""
    t = claim_text or ""
    if _ALLOWED_RE.search(t):
        return "allowed"
    if _HELDOUT_RE.search(t):
        return "held-out"
    return "indeterminate"


def apply_validity(claims, findings, contract, claim_text):
    """Promote the headline claim's verdict per the contamination findings + the claim scope. Conservative:
    only a REPRODUCED number (CONFIRMED/CAVEATS) is promoted, and only DOWN. Exact memorization on a
    held-out claim -> INVALIDATED; on a contamination-allowed claim -> CAVEAT; on an indeterminate scope
    -> CAN'T-CONFIRM. A heuristic near-dup is always a CAVEAT. REFUTED is never manufactured here."""
    contam = [f for f in findings if f.get("dimension") == "contamination"]
    if not contam or not claims:
        return
    head = next((c for c in claims if c.get("headline")), claims[0])
    if head.get("verdict") not in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS"):
        return  # the number didn't reproduce; contamination findings stay additive, no promotion
    import verdict as V
    vi = head.get("verdict_inputs") or {}
    # declared-but-unreadable corpus: the check could not run -> CAN'T-CONFIRM, never a silent pass.
    # Must RE-DERIVE the headline verdict (mirror the tail) - setting the flag alone leaves the stale
    # CONFIRMED label on the claim while verdict_inputs says otherwise.
    if any(f.get("contamination_indeterminate") for f in contam):
        vi["validity_unresolved"] = True
        head["driving_dimension"] = "contamination"
        head["verdict_inputs"] = vi
        head["verdict"] = V.verdict(vi)
        head["headline_confidence"] = V.confidence(vi, head["verdict"])
        return
    auth = [f for f in contam if f.get("validity_class") == "authoritative"]
    soft = [f for f in contam if f.get("validity_class") == "soft"]
    if auth:
        status = contamination_status(contract, claim_text)
        if status == "held-out":
            vi["validity_invalidated"] = True
            vi["oos_claim_asserted"] = True
            head["driving_dimension"] = "contamination"
            for f in auth:
                f["claim_id"] = head["id"]
        elif status == "allowed":
            for f in auth:  # contamination is acknowledged by the claim -> a noted caveat
                f["severity"] = "minor"
                f["unblock"] = f.get("unblock", "") + " (or confirm the eval intentionally includes corpus items)"
            vi["soft_validity_caveat"] = True
        else:  # indeterminate -> CAN'T-CONFIRM: declare the scope, don't guess
            vi["validity_unresolved"] = True
            for f in auth:
                f["unblock"] = ("declare whether the eval is held-out / zero-shot (uncontaminated) - then "
                                "re-verify; " + f.get("unblock", ""))
    elif soft:
        vi["soft_validity_caveat"] = True
    else:
        return
    head["verdict_inputs"] = vi
    head["verdict"] = V.verdict(vi)
    head["headline_confidence"] = V.confidence(vi, head["verdict"])
