# Para rodar o buscador num servidor na nuvem (ou em qualquer máquina com Docker).
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 BUSCAIMOVEIS_HOME=/dados
WORKDIR /app
COPY pyproject.toml ./
COPY buscaimoveis ./buscaimoveis
RUN pip install --no-cache-dir ".[rapido]" && useradd -m app && mkdir /dados && chown app /dados
USER app
VOLUME /dados
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/saude', timeout=3)"
# Sem BUSCAIMOVEIS_SENHA, o primeiro início gera um código de acesso e o mostra nos registros (logs) do contêiner.
CMD ["buscaimoveis", "servir", "--celular", "--porta", "8000"]
