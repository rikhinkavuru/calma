"""In-sandbox notebook runner (four-unlocks §1, E2B/Modal notebook dispatch).

Runs inside the verification sandbox — invoked as `python /capture/run_notebook_e2b.py <notebook.ipynb>`. The
process env already carries the capture arming (PYTHONPATH=/capture + CALMA_CAPTURE_OUT, set by
runner.effector.capture_run_env), and the Jupyter kernel this launches INHERITS that env, so the capture shim
auto-installs in the kernel via sitecustomize — no fragile in-cell injection. This mirrors the host-side
orchestrator.tools_exec.run_notebook, but as a standalone entrypoint the sandbox can exec.

SOTA notebook-as-a-job discipline (papermill/nbclient field guides): pin the kernel to `python3`, enforce a
per-cell timeout, and let cell errors surface (`allow_errors=False`) — a silent half-run is worse than a clean
failure. Exit 0 on a full run, 1 on any cell error or a kernel/startup failure (an honest failed run).
"""
from __future__ import annotations

import os
import sys


def main(argv) -> int:
    if len(argv) < 2:
        sys.stderr.write("usage: run_notebook_e2b.py <notebook.ipynb>\n")
        return 2
    nb_path = argv[1]
    if not os.path.isfile(nb_path):
        sys.stderr.write("notebook not found: %s\n" % nb_path)
        return 2
    try:
        import nbformat
        from nbclient import NotebookClient
        from nbclient.exceptions import CellExecutionError
    except Exception as e:  # noqa: BLE001 — the runtime isn't in the image (shouldn't happen post-rebuild)
        sys.stderr.write("notebook runtime unavailable: %s\n" % e)
        return 1

    cell_timeout = int(os.environ.get("CALMA_NB_CELL_TIMEOUT", "300"))
    try:
        nb = nbformat.read(nb_path, as_version=4)
        client = NotebookClient(nb, timeout=cell_timeout, kernel_name="python3", allow_errors=False,
                                resources={"metadata": {"path": os.path.dirname(nb_path) or "."}})
        client.execute()
    except CellExecutionError as e:
        sys.stderr.write("cell error: %s\n" % str(e)[-2000:])
        return 1
    except Exception as e:  # noqa: BLE001 — kernel/startup failure → honest failed run
        sys.stderr.write("notebook execution failed: %s\n" % str(e)[-2000:])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
