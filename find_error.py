import subprocess
import sys
p = subprocess.Popen([sys.executable, "main.py"], cwd="D:/Internship/vsco/backend", stderr=subprocess.PIPE, text=True)
with open("D:/Internship/vsco/traceback.txt", "w") as f:
    for line in p.stderr:
        f.write(line)
        f.flush()
        if "??" in line or "Fatal" in line:
            for _ in range(20):
                f.write(next(p.stderr, ""))
            break
p.kill()
