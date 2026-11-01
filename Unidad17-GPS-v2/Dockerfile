FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UNIDAD17_DATOS=/data \
    UNIDAD17_DB=/data/datos/unidad17.db

WORKDIR /app
COPY servidor/requirements-produccion.txt .
RUN pip install --no-cache-dir -r requirements-produccion.txt

COPY servidor/ ./
COPY entrypoint.sh /entrypoint.sh
RUN rm -rf dist deploy actualizaciones/*.exe \
 && useradd --system --uid 10001 unidad17 \
 && chmod +x /entrypoint.sh \
 && mkdir -p /data && chown unidad17 /data
VOLUME /data
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/salud'%os.environ.get('PORT','5000'),timeout=3)"

# Un solo proceso con varios hilos: el límite de intentos fallidos vive en
# memoria y con varios procesos no sería global.
ENTRYPOINT ["/entrypoint.sh"]
