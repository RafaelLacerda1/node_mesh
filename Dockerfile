FROM debian:11-slim

ENV DEBIAN_FRONTEND=noninteractive

# 1. Instalar dependencias
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    openssh-client \
    git \
    sshpass \
    sqlite3 \
    vim \
    curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 2. Criar usuario
RUN useradd -m -s /bin/bash appuser
ENV PATH="/home/appuser/.local/bin:${PATH}"

# 3. Configurar SSH
RUN mkdir -p /home/appuser/.ssh && chown appuser:appuser /home/appuser/.ssh
COPY --chown=appuser:appuser id_rsa /home/appuser/.ssh/id_rsa
RUN chmod 600 /home/appuser/.ssh/id_rsa

# 4. CORRECAO DO ERRO:
# Cria a pasta de trabalho explicitamente e da permissao ao appuser
RUN mkdir -p /home/appuser/app && chown -R appuser:appuser /home/appuser/app

# 5. Definir diretorio de trabalho e usuario
WORKDIR /home/appuser/app
USER appuser

# 6. Dependencias Python
COPY --chown=appuser:appuser requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# 7. Copiar codigo
COPY --chown=appuser:appuser . .

# 8. Criar pasta de logs
RUN mkdir -p /home/appuser/app/data/logs

EXPOSE 8080

CMD ["python3", "run.py"]
