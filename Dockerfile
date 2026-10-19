# 基底：官方 Python 3.12 精簡版（Linux）
FROM python:3.12-slim

# 之後的指令都在容器內的 /app 執行
WORKDIR /app

# 強制 UTF-8、輸出不緩衝（docker logs 才看得到即時訊息）
ENV PYTHONUTF8=1 PYTHONUNBUFFERED=1

# 只複製執行需要的程式碼
COPY main.py ./
COPY splitbill ./splitbill

# 標示服務用的埠（說明用，實際開埠靠 docker run -p）
EXPOSE 8000

# 容器啟動時執行的指令
CMD ["python", "main.py", "web"]
用