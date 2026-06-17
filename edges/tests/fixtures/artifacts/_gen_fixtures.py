"""Regenerate the deterministic P1.1 ingestion fixtures (nb / csv / pdf).

These are committed binaries; this script documents exactly how they were produced so the bytes
are reproducible. Run once:  python3 edges/tests/fixtures/artifacts/_gen_fixtures.py
(The PDF step needs PyMuPDF; the nb/csv steps are pure stdlib.)
"""
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def gen_preds_csv():
    """preds.csv: header y_true,y_pred + 1000 rows. Fully deterministic (no randomness):
    y_true alternates 0/1; y_pred sweeps 0.00..0.99. int-like label, float-in-[0,1] prediction."""
    path = os.path.join(HERE, "preds.csv")
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["y_true", "y_pred"])
        for i in range(1000):
            w.writerow([i % 2, "%.2f" % ((i % 100) / 100.0)])
    return path


def gen_notebook():
    """nb_three_metrics.ipynb: 15 cells. Cells 0-11 are no-number filler (dropped on ingest);
    cell 12 prints 'accuracy = 0.94', cell 13 prints 'AUC: 0.91', cell 14 writes preds.csv then
    prints 'macro F1 0.88'."""
    def code(src, outputs=None):
        return {"cell_type": "code", "metadata": {}, "execution_count": None,
                "source": src, "outputs": outputs or []}

    def md(src):
        return {"cell_type": "markdown", "metadata": {}, "source": src}

    def stream(text):
        return {"output_type": "stream", "name": "stdout", "text": text}

    cells = [md(["# BTC strategy backtest\n", "Load data and evaluate the model."])]
    filler = [
        "import pandas as pd\n",
        "import numpy as np\n",
        "from sklearn.metrics import accuracy_score, roc_auc_score, f1_score\n",
        "df = pd.read_csv('input.csv')\n",
        "df = df.dropna()\n",
        "features = ['open', 'high', 'low', 'close']\n",  # has no standalone digit
        "X = df[features]\n",
        "y = df['label']\n",
        "model = train(X, y)\n",
        "preds = model.predict(X)\n",
        "scores = model.predict_proba(X)\n",
    ]  # 11 filler code cells -> indices 1..11
    for src in filler:
        cells.append(code([src]))

    # cell 12
    cells.append(code(['print("accuracy = 0.94")\n'], [stream("accuracy = 0.94\n")]))
    # cell 13
    cells.append(code(['print("AUC: 0.91")\n'], [stream("AUC: 0.91\n")]))
    # cell 14 - writes preds.csv then prints a macro-F1
    cells.append(code(['df.to_csv("preds.csv")\n', 'print("macro F1 0.88")\n'],
                      [stream("macro F1 0.88\n")]))

    nb = {"cells": cells, "metadata": {"language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    path = os.path.join(HERE, "nb_three_metrics.ipynb")
    with open(path, "w") as fh:
        json.dump(nb, fh, indent=1)
    return path


def gen_pdf():
    """report_one_page.pdf: 1 page. A title paragraph (with a year) and one table block whose
    data rows each carry >=2 numeric tokens, including a 'BTC strategy ... Sharpe ... 1.85' row."""
    import fitz
    path = os.path.join(HERE, "report_one_page.pdf")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "BTC Strategy Backtest 2024 Report", fontsize=14)
    table = ("Strategy        Sharpe   Return\n"
             "BTC strategy    1.85     0.32\n"
             "ETH strategy    1.40     0.21")
    page.insert_text((72, 120), table, fontsize=11)
    doc.save(path, garbage=4, deflate=True)
    doc.close()
    return path


if __name__ == "__main__":
    print(gen_preds_csv())
    print(gen_notebook())
    print(gen_pdf())
