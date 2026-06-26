"""calma.config_toml - read/write the committed `calma.toml`, the WS1 convention config.

`calma init` (auto-detect) writes a calma.toml so the SECOND verify is bare `calma verify` - the
file pins the target folder, the recipe, and the claim. `calma verify` (no positional target) finds
the nearest calma.toml (walking up to the repo root) and runs it. This is the ecosystem convention
(ruff.toml / cargo.toml / uv): a flat, committed, human-editable config at the repo root.

Pure stdlib. TOML is read with the stdlib `tomllib` (Python >= 3.11) when available; on 3.9/3.10 a
minimal reader handles the FLAT subset calma.toml uses (a `[verify]` table of string/number/bool
values - no nested tables or arrays). Calma stays dependency-free and supports Python >= 3.9.
"""
from __future__ import annotations

import os

FILENAME = "calma.toml"


def _coerce(val):
    """A bare TOML scalar -> a Python value (quoted string / int / float / bool / else the raw string)."""
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        return val[1:-1]
    low = val.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return float(val) if ("." in val or "e" in low or "inf" in low or "nan" in low) else int(val)
    except ValueError:
        return val


def _parse_minimal(text):
    """A tiny flat-TOML reader for the subset calma.toml uses: `[section]` headers + `key = value`
    lines (value: a quoted string, a number, or a bool). No nested tables / arrays. Used ONLY when
    stdlib `tomllib` is unavailable (Python < 3.11), where `tomllib` is always preferred."""
    out, section = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            out.setdefault(section, {})
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        # take the value up to an inline comment. A quoted value ends at its CLOSING quote (a '#'
        # before it is data); a bare value ends at the first '#'.
        if val[:1] in ("'", '"'):
            close = val.find(val[0], 1)
            if close != -1:
                val = val[:close + 1]
        else:
            val = val.split("#", 1)[0].strip()
        bucket = out.setdefault(section, {}) if section else out
        bucket[key] = _coerce(val)
    return out


def loads(text):
    """Parse calma.toml text -> a nested dict. tomllib when present (full spec), else the flat reader.

    A REAL tomllib parse error (a duplicate key, a git merge-conflict marker, genuinely malformed TOML)
    is RAISED, never silently re-parsed by the lenient flat reader: degrading there would accept a
    broken file and quietly verify the WRONG claim/target (the one thing Calma must never do). The flat
    reader is a fallback ONLY on Python < 3.11, where there is no stdlib tomllib at all."""
    try:
        import tomllib
    except ModuleNotFoundError:
        return _parse_minimal(text)        # Python < 3.11: no stdlib TOML parser
    try:
        return tomllib.loads(text)
    except Exception as e:
        raise ValueError("malformed calma.toml (%s) - fix the file; Calma won't guess which value you "
                         "meant" % e)


def load(path):
    """Read + parse a calma.toml file. Raises ValueError on an unreadable / oversized / non-utf8 /
    non-regular file (a FIFO or device would block open() forever, and a non-utf8 file is corrupt)."""
    import stat as _stat
    try:
        st = os.stat(path)
        if not _stat.S_ISREG(st.st_mode):       # a FIFO/socket/device: never open() (would block)
            raise ValueError("calma.toml is not a regular file: %s" % path)
        if st.st_size > 1 << 20:                 # a calma.toml is a few hundred bytes; cap a hostile one
            raise ValueError("calma.toml is over the 1 MB cap - it should be a few lines")
        with open(path, "r", encoding="utf-8") as fh:
            return loads(fh.read())
    except (OSError, UnicodeError) as e:
        raise ValueError("could not read %s: %s" % (path, e))


def find(start="."):
    """Find the nearest calma.toml walking UP from `start` (a file or dir), stopping at the repo root
    (a directory containing `.git`) or the filesystem root - so an unrelated parent project's
    calma.toml is never picked up. Returns the absolute path, or None."""
    d = os.path.abspath(start)
    if os.path.isfile(d):
        d = os.path.dirname(d)
    while True:
        cand = os.path.join(d, FILENAME)
        if os.path.isfile(cand):
            return cand
        if os.path.isdir(os.path.join(d, ".git")):
            return None                       # repo root reached, no calma.toml at/above it
        parent = os.path.dirname(d)
        if parent == d:
            return None                       # filesystem root
        d = parent


def verify_config(start="."):
    """Resolve the [verify] config nearest `start` -> a dict with absolute `target` (+ metric / claim /
    tol / run_id when present), or None when there is no calma.toml. `target` is resolved RELATIVE TO
    the calma.toml's own directory, so `calma verify` works from any subdirectory of the repo."""
    path = find(start)
    if not path:
        return None
    data = load(path)
    v = data.get("verify") or {}
    base = os.path.dirname(path)
    target = v.get("target") or "."
    cfg = {"target": os.path.normpath(os.path.join(base, target)), "_path": path}
    for k in ("metric", "claim", "run_id"):
        if v.get(k) is not None:
            cfg[k] = str(v[k])
    if v.get("tol") is not None:
        cfg["tol"] = v["tol"]
    return cfg


def _q(s):
    """Quote a string for TOML (double quotes; backslash + double-quote escaped)."""
    return '"%s"' % str(s).replace("\\", "\\\\").replace('"', '\\"')


def dump_verify(target=".", metric=None, claim=None, tol=None, detected=None):
    """Render a committed calma.toml for a verify config. `detected` is an optional list of human notes
    (what auto-detection found) written as comments so the file is self-documenting."""
    out = [
        "# calma.toml - committed so `calma verify` (no args) re-checks this result.",
        "# Calma re-executes the code in a network-off sandbox and recomputes the headline number from",
        "# the raw output files (never the reported number), then proves or breaks the claim.",
        "# Edit any field; delete the file to start over. Docs: https://trycalma.ai/docs",
    ]
    if detected:
        out.append("#")
        out.extend("# detected: %s" % d for d in detected)
    out += ["", "[verify]", "target = %s" % _q(target)]
    if metric:
        out.append("metric = %s  # recipe id - browse with `calma recipes search <term>`" % _q(metric))
    if claim:
        out.append("claim  = %s  # the headline number to check" % _q(claim))
    else:
        out.append('# claim = "accuracy=0.91"   # add a number to check; omit for a reproduction-only run')
    if tol is not None:
        out.append("tol    = %s  # tolerance override (Calma calibrates one by default)" % tol)
    return "\n".join(out) + "\n"


def write(target_dir, **kw):
    """Write calma.toml into `target_dir`. Returns the path written."""
    path = os.path.join(target_dir, FILENAME)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dump_verify(**kw))
    return path
