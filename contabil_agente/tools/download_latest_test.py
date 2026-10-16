from pathlib import Path

import requests

URL = "http://127.0.0.1:5000/download/latest"
OUT = Path("downloaded_latest.pd")
try:
    r = requests.get(URL, timeout=20)
    r.raise_for_status()
    with open(OUT, "wb") as f:
        f.write(r.content)
    print("SAVED", OUT.resolve())
except Exception as e:
    print("ERROR", str(e))
