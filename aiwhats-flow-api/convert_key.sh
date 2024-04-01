#!/bin/bash

# Substitua private.pem pelo caminho real do seu arquivo de chave privada
PRIVATE_KEY_PATH="private.pem"

# Lê o arquivo de chave privada, substitui as quebras de linha por '\n', e salva o resultado em uma variável
PRIVATE_KEY=$(awk '{printf "%s\\n", $0}' $PRIVATE_KEY_PATH)

# Adiciona aspas no início e no final da chave
PRIVATE_KEY_FORMATTED="\"$PRIVATE_KEY\""

# Exibe a chave formatada
echo $PRIVATE_KEY_FORMATTED

# Opcional: Descomente a linha abaixo para escrever automaticamente no arquivo .env
# echo "PRIVATE_KEY=$PRIVATE_KEY_FORMATTED" >> .env
