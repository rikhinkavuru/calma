"""The `calma` console-script entry point (pyproject [project.scripts]). A thin shim: bootstrap the engine
via the package facade, then hand argv to the engine's own argparse main - so `calma` (pip) and
`bin/calma` (symlink) and the skill all drive the SAME CLI."""
import os
import sys


def main():
    # make echoed reproduce/next-step hints read "calma ..." (copy-pasteable), matching bin/calma.
    os.environ.setdefault("CALMA_INVOKED_AS", "calma")
    import calma  # noqa: F401 - triggers the facade bootstrap (adds the engine dir to sys.path)
    return calma._engine.main()


if __name__ == "__main__":
    sys.exit(main())
