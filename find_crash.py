with open("tmp_error.txt", "w") as f:
    import json
    # just dump whatever was logged
    try:
        f.write(open("crash_log.txt").read())
    except Exception:
        pass
    try:
        f.write("\n")
        f.write(open("backend/crash_log.txt").read())
    except Exception:
        pass
