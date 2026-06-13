import os, shutil
os.makedirs("runs", exist_ok=True)
shutil.copy(os.path.join("data", "preds.csv"), os.path.join("runs", "preds.csv"))
