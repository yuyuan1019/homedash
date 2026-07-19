FROM python:3.12

WORKDIR /app

# 容器默认时区设为上海，使 datetime.now() 与 SQLite localtime 输出北京时间；compose 可用 TZ 覆盖
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY .env.example ./.env.example

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
