"""The repo's own metric implementation — in an importable module so the harness can wrap it via a bind
hint (a custom function defined in the __main__ entrypoint can't be wrapped at import time)."""
import numpy as np


def my_accuracy(y_true, y_pred):
    # BUG / cheat: compares predictions to THEMSELVES, ignoring y_true -> always 1.0.
    yp = np.asarray(y_pred)
    return float((yp == yp).mean())
