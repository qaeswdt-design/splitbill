import sys

# Windows 上以管道(pipe)或非預設編碼終端機執行時，stdin/stdout 可能不是 UTF-8，
# 這裡強制指定為 UTF-8，避免中文輸入/輸出出現亂碼或編碼錯誤。
for stream in (sys.stdin, sys.stdout):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from splitbill.cli import run

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "web":
        from splitbill.web import run as run_web

        run_web(int(sys.argv[2]) if len(sys.argv) > 2 else 8000)
    else:
        run()
