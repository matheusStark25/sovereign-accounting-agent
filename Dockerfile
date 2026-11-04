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
# correções de segurança do sistema base (o CI passa o trivy na imagem pronta)
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
# As versões exatas testadas (requirements.lock) entram como restrição: dependência nova não chega à imagem sem teste.
# O pip só serve para montar a imagem e sai no fim: ele traz uma cópia antiga do setuptools (CVE-2025-47273, achada pelo
# trivy) e não é usado em produção.
COPY requirements.txt requirements.lock ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt -c requirements.lock \
    && pip uninstall -y pip

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
