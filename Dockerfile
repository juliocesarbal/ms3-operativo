# MS3 Operativo/IA (FastAPI + sklearn + TensorFlow-CPU + web3) — imagen para GCP Cloud Run.
# Imagen grande por TensorFlow (~2-3GB); Cloud Run la soporta. Build tarda varios min.

FROM python:3.13-slim

WORKDIR /app

# Dependencias del sistema: gcc/g++ para wheels nativas (web3/psycopg), libgomp para sklearn/TF.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

# Instala deps primero (capa cacheable). tensorflow-cpu es lo mas pesado.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Codigo + modelos ML ya entrenados (.pkl/.keras estan versionados en el repo).
COPY app ./app

# Cloud Run inyecta PORT (default 8080). La app escucha en 0.0.0.0:$PORT.
ENV PORT=8080
EXPOSE 8080

# sh -c para expandir $PORT. 1 worker (Cloud Run escala por instancias, no por workers).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
