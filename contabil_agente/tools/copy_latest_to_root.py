import os
import shutil
from pathlib import Path

d = Path(__file__).parent.parent / "temp_docs"
files = [f for f in os.listdir(d) if f.lower().endswith(".pd")]
if not files:
    print("NO_PDF")
else:
    files.sort(key=lambda f: os.path.getmtime(os.path.join(d, f)), reverse=True)
    src = d / files[0]
    dst = Path.cwd() / "rescisao_para_baixar.pd"
    shutil.copy(src, dst)
    print("COPIED", dst)
