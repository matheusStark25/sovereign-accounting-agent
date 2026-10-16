import sys

p = r"c:\Users\User\Desktop\agent projeto V2\parte1_after_enter.html"
try:
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        s = f.read()
        if "12.345.678/0001-90" in s:
            print("FOUND")
        else:
            print("NOT FOUND")
except Exception as e:
    print("ERROR", e)
    sys.exit(2)
