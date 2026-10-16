# API + worker de documentos (mesma imagem; o compose troca o comando).
# O worker do RPA do FGTS NÃO roda aqui: ele abre um navegador para uma pessoa resolver captcha/login
# e por isso roda numa máquina com tela (veja o README, seção RPA).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    AGENTE_ENV=production

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY agente_v2 ./agente_v2
COPY contabil_agente ./contabil_agente
COPY rules ./rules

RUN useradd --system --uid 10001 --create-home app \
    && mkdir -p /data \
    && chown -R app:app /data /app
USER app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "agente_v2.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
