"""One path-containment guard, shared by every reader that joins a CONTRACT-supplied relative path
onto a base dir. A counterparty verify.yaml is untrusted input: `split.train: ../../etc/passwd`
must never resolve to a read outside the contract's base. Symlinks are resolved (realpath) so a
symlinked escape is caught too. Pure stdlib.

Usage:  path = safe_join(base, contract["split"]["train"])   # raises ValueError on escape
"""
import os


def safe_join(base, rel):
    """Join `rel` onto `base` and confirm the result stays inside `base` (after resolving symlinks).
    Returns the absolute real path; raises ValueError if `rel` escapes the base."""
    full = os.path.realpath(os.path.join(base, rel))
    rb = os.path.realpath(base)
    if full != rb and not full.startswith(rb + os.sep):
        raise ValueError("path escapes the contract base: %r" % rel)
    return full


def is_contained(base, rel):
    """True iff `rel` joined onto `base` stays inside `base` (no exception form of safe_join)."""
    try:
        safe_join(base, rel)
        return True
    except ValueError:
        return False


def guard_out_dir(out_dir, source_dir):
    """L2: validate a user-supplied --out for a writer (registry site / evidence bundle). Returns the
    resolved real path, or raises ValueError when --out: (a) IS the source dir, or (b) is an ANCESTOR
    of the source - a parent/`..`-traversal that would write up the tree and could clobber or escape
    the source's own location. An arbitrary sibling / absolute target the user names is allowed (the
    writers are designed to deposit a pack anywhere); the guard's job is the parent-traversal the old
    `out != source` check missed. Local / low-severity."""
    out_r = os.path.realpath(out_dir)
    src_r = os.path.realpath(source_dir)
    if out_r == src_r:
        raise ValueError("--out must differ from the source dir itself")
    if src_r == out_r or src_r.startswith(out_r + os.sep):
        raise ValueError("--out %r is an ancestor of the source dir - refusing (a parent-traversal "
                         "that would write up/over the tree)" % out_dir)
    return out_r
