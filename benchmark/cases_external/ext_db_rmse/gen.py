import os, shutil
os.makedirs("runs", exist_ok=True)
shutil.copy(os.path.join("data", "reg.csv"), os.path.join("runs", "reg.csv"))
