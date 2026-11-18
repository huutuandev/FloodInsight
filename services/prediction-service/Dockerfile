FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY floodinsight_prediction ./floodinsight_prediction
COPY --from=ml_common . /app
RUN install -d -o 10001 -g 10001 /models
ENV OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "floodinsight_prediction.main:app", "--host", "0.0.0.0", "--port", "8000"]
