"""calma.connectors - W7: the manager-data connector contract + the local/on-prem connector.

A connector pulls a manager's mandate data into a pathsafe-CONTAINED workspace, content-hashes it and emits a
W8(d) source manifest (the lineage tier-2), and hands the workspace off to verify/recompute. THE INVARIANT (the
"data never leaves" load-bearing fact at the intake edge): a connector NEVER uploads raw bytes to the control
plane — only the local workspace path + the source manifest (hashes + metadata) leave it.

`LocalConnector` (on-prem / data-handed-over) is FULLY built + tested, no creds — the reference connector and
the real on-prem case. `S3` / `SFTP` / `DataRoom` are honest skeletons: the transport needs provider
credentials + the W7 BYOC runner, so they name their contract and refuse honestly (`available()` is truthful,
`pull()` raises NotImplementedError) — a fill-in, not a redesign (mirrors execprovider/remote_drivers.py). The
shared `source_manifest()` (the lineage tier-2 emission) is real for every connector.

Pure stdlib. Library: get(name) -> Connector; LocalConnector().pull(source, workspace) -> PullResult.
"""
import hashlib
import os
import shutil
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lineage as LIN  # noqa: E402 - the W8(d) source-manifest builder
import pathsafe as PS  # noqa: E402 - the containment guard

_NOT_BUILT = ("connector not built — needs the W7 BYOC runner + provider credentials; the contract is fixed "
              "(pull into a contained workspace, emit a source manifest, hand off to recompute)")


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _runner_id(name):
    try:
        host = socket.gethostname()
    except OSError:
        host = "host"
    return "calma-connector-%s@%s" % (name, host)


class Connector:
    """The connector contract. Subclasses implement `available()` + `pull()`; `source_manifest()` (the W8(d)
    lineage tier-2) is shared. `pull(source, workspace)` returns a PullResult dict:
        {workspace, local_path, source_manifest, uploaded_raw_bytes: False}."""

    name = "connector"

    def available(self):
        """(ok: bool, reason: str) — is this connector usable in the current environment?"""
        return False, _NOT_BUILT

    def pull(self, source, workspace, **kw):
        raise NotImplementedError("%s.pull: %s" % (self.name, _NOT_BUILT))

    def source_manifest(self, uri, local_path, *, retrieved_at=None, etag=None, version_id=None):
        """Emit the W8(d) tier-2 source manifest for a pulled artifact: the URI it came from + the transport
        digest hashed AT FETCH TIME (so the recomputed bytes can be chained to the fetched bytes) + the
        provider immutability handles. Real for every connector."""
        return LIN.source_descriptor(uri, retrieved_at=retrieved_at, retrieved_by=_runner_id(self.name),
                                     transport_sha256=_sha256_file(local_path) if local_path else None,
                                     etag=etag, version_id=version_id)


class LocalConnector(Connector):
    """Pull manager data from a LOCAL path (on-prem, or a directory the manager handed over) into a contained
    workspace + emit the source manifest. Fully working, no creds — the reference connector. Raw bytes are
    copied LOCALLY into the workspace and never uploaded; only the workspace path + the manifest leave."""

    name = "local"

    def available(self):
        return True, "local filesystem"

    def pull(self, source, workspace, *, retrieved_at=None):
        if not os.path.exists(source):
            raise ValueError("source %r not found" % source)
        workspace = os.path.realpath(workspace)          # resolve symlinks so containment + the returned paths agree
        os.makedirs(workspace, exist_ok=True)
        base = os.path.basename(source.rstrip("/")) or "data"
        dest = PS.safe_join(workspace, base)             # CONTAIN the destination (no traversal out of workspace)
        src_uri = "file://%s" % os.path.abspath(source)
        if os.path.isdir(source):
            shutil.copytree(source, dest, dirs_exist_ok=True)
            manifest = {"uri": src_uri, "retrieved_by": _runner_id(self.name),
                        "note": "directory — per-file content hashes live in the run's input_lineage"}
        else:
            shutil.copy2(source, dest)
            manifest = self.source_manifest(src_uri, dest, retrieved_at=retrieved_at)
        return {"workspace": workspace, "local_path": dest,
                "source_manifest": manifest, "uploaded_raw_bytes": False}


class _SkeletonConnector(Connector):
    """Honest base for the not-yet-built cloud connectors: the contract (methods) is real, the transport body
    is not. `mapping` names the concrete source shape a builder fills in (kept as data for docs/inspection)."""

    mapping = {}

    def available(self):
        return False, _NOT_BUILT


class S3Connector(_SkeletonConnector):
    """Pull from an S3 bucket/key into the contained workspace (uses the object's ETag + version_id as the
    immutability handles in the source manifest). Needs AWS credentials + the BYOC runner."""
    name = "s3"
    mapping = {"source": "{bucket, key, version_id?}", "auth": "AWS creds (runner's role)",
               "immutability": "ETag + version_id -> source_manifest"}


class SFTPConnector(_SkeletonConnector):
    """Pull from an SFTP host/path into the contained workspace. Needs SFTP credentials + the BYOC runner."""
    name = "sftp"
    mapping = {"source": "{host, path, key?}", "auth": "SFTP key/password (runner secret)"}


class DataRoomConnector(_SkeletonConnector):
    """Pull from a data-room export (e.g. a fund admin's portal) into the contained workspace. Needs the
    data-room API credentials + the BYOC runner."""
    name = "data-room"
    mapping = {"source": "{provider, export_id}", "auth": "data-room API token (runner secret)"}


CONNECTORS = {
    "local": LocalConnector,
    "s3": S3Connector,
    "sftp": SFTPConnector,
    "data-room": DataRoomConnector,
}


def get(name):
    """Resolve a connector by name. Raises KeyError on an unknown name."""
    key = (name or "").strip().lower()
    if key not in CONNECTORS:
        raise KeyError("unknown connector %r (known: %s)" % (name, ", ".join(sorted(CONNECTORS))))
    return CONNECTORS[key]()
