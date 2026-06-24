#!/bin/bash

PASSWORD="cefetmg"

PUBKEY=$(cat ~/MONITOR-DE-NOS/id_rsa.pub)

for ip in $(seq 1 40); do

    HOST="10.2.0.$ip"

    echo "=============================="
    echo "Verificando $HOST"
    echo "=============================="

    ping -c 1 -W 1 "$HOST" >/dev/null 2>&1 || continue

    # Se já aceita chave, pula
    ssh -o BatchMode=yes \
        -o ConnectTimeout=2 \
        -i ~/MONITOR-DE-NOS/id_rsa \
        fitpath@$HOST exit >/dev/null 2>&1

    if [ $? -eq 0 ]; then
        echo "[OK] Já possui chave"
        continue
    fi

    echo "[INFO] Instalando chave..."

    sshpass -p "$PASSWORD" ssh \
        -o StrictHostKeyChecking=no \
        -o ConnectTimeout=5 \
        fitpath@$HOST "
            mkdir -p ~/.ssh
            chmod 700 ~/.ssh

            touch ~/.ssh/authorized_keys

            grep -qxF '$PUBKEY' ~/.ssh/authorized_keys || \
            echo '$PUBKEY' >> ~/.ssh/authorized_keys

            chmod 600 ~/.ssh/authorized_keys
        "

    if ssh -o BatchMode=yes \
        -o ConnectTimeout=2 \
        -i ~/MONITOR-DE-NOS/id_rsa \
        fitpath@$HOST exit >/dev/null 2>&1; then

        echo '[SUCESSO] Chave instalada'

    else

        echo '[ERRO] Falhou'

    fi

done
