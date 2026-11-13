FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py ./
COPY history_store.py ./
COPY health_checks.py ./
COPY platform_worker.py platform_monitor.py ./
COPY frontend/dist ./static
ENV GATEWAY_STATIC_DIR=/app/static
EXPOSE 8091
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8091", "--no-server-header"]
