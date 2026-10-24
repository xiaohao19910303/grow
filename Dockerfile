FROM python:3.12-slim-bookworm
ARG GROW_REVISION
ENV GROW_REVISION=$GROW_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CLOUD_DEPLOY=1 PLAN_CONTENT_BACKEND=github WEB_CONCURRENCY=1 PORT=8756 GROW_SCHEDULED_READING_ENABLED=0 RUNTIME_ROOT=/var/lib/grow/runtime LEARN_ROOT=/app/知行成长/学习资料
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git postgresql-client && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt && pip check
COPY 知行成长/server /app/知行成长/server
COPY 知行成长/学习资料/英文阅读/每日文章 /app/知行成长/学习资料/英文阅读/每日文章
COPY 知行成长/学习资料/结构化表达/每日练习 /app/知行成长/学习资料/结构化表达/每日练习
COPY 知行成长/学习资料/现代思维工具教程 /app/知行成长/学习资料/现代思维工具教程
RUN useradd --create-home --uid 10001 grow && mkdir -p /var/lib/grow/runtime && chown -R grow:grow /var/lib/grow
USER grow
WORKDIR /app/知行成长/server
EXPOSE 8756
CMD ["python", "deployment.py", "serve", "--host", "0.0.0.0"]
