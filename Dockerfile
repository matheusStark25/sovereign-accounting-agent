FROM python:3.14-slim

RUN groupadd -r app && useradd -r -g app -m app
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r requirements.txt || true
RUN chown -R app:app /app

USER app
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "pytest", "-q"]
# Dockerfile para produção

FROM python:3.11-slim

WORKDIR /app

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY contabil_agente/ ./contabil_agente/

# Criar diretórios necessários
RUN mkdir -p /app/db /app/logs /app/documents /app/uploads

# Usuário não-root
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5000/api/health')"

# Expor porta
EXPOSE 5000

# Comando de inicialização
CMD ["python", "-m", "contabil_agente.agent_contabil"]
