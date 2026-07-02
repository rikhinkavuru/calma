"""calma_capture._to_list: which captured inputs are serializable and reach independent recompute.

Found via real-repo e2e testing: pandas.get_dummies(..., drop_first=True) on a binary label returns a
single-COLUMN DataFrame (shape (n, 1)), not a Series — genuinely 1-D data, but shaped 2-D. The old "any 2-D
is out of scope" rule silently dropped it, so a real, correctly-reproduced accuracy sat at REPRODUCED-ONLY
forever (no independent recompute was ever attempted) instead of reaching a real CONFIRMED/INVALIDATED
verdict. A true multi-column 2-D array (multiclass scores) must still be refused — squeezing THAT would
silently pick one column and change what's being measured."""
import numpy as np
import pandas as pd

import calma_capture as CC


def test_1d_array_captures_normally():
    v, ok = CC._to_list(np.array([0, 1, 1, 0]), budget=1000)
    assert ok and v == [0, 1, 1, 0]


def test_single_column_2d_numpy_array_is_squeezed():
    arr = np.array([[0], [1], [1], [0]])
    assert arr.shape == (4, 1)
    v, ok = CC._to_list(arr, budget=1000)
    assert ok and v == [0, 1, 1, 0]


def test_single_column_dataframe_is_squeezed():
    # the exact real-world shape: pd.get_dummies(categorical, drop_first=True) on a binary label
    df = pd.get_dummies(pd.Categorical.from_codes([0, 1, 1, 0], ["benign", "malignant"]), drop_first=True)
    assert df.shape == (4, 1)
    v, ok = CC._to_list(df, budget=1000)
    assert ok and v == [0, 1, 1, 0]


def test_multicolumn_2d_array_still_refused():
    # genuine multiclass scores (e.g. predict_proba output) — squeezing this would silently pick a column
    # and change what's being measured, not just a serialization convenience. Must stay unsupported.
    arr = np.array([[0.1, 0.9], [0.8, 0.2], [0.3, 0.7]])
    v, ok = CC._to_list(arr, budget=1000)
    assert not ok and v is None


def test_single_column_over_budget_still_refused():
    arr = np.zeros((10, 1))
    v, ok = CC._to_list(arr, budget=5)
    assert not ok and v is None
