import subprocess
import sys
import time
import os

with open("D:/Internship/vsco/traceback.txt", "w", encoding="utf-8") as f:
    p = subprocess.Popen([sys.executable, "main.py"], cwd="D:/Internship/vsco/backend", stderr=f, stdout=f, text=True)
    time.sleep(3)
    os.system(sys.executable + " D:/Internship/vsco/tmp_duplex4.py")
    time.sleep(2)
    p.kill()
