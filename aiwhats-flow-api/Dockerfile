# Use uma imagem base do Node.js. Substitua '21.7.1' pela versão específica do Node que você precisa
FROM node:21.7.1

# Defina o diretório de trabalho no contêiner
WORKDIR /app

# Copie os arquivos package.json e package-lock.json
COPY package*.json ./

# Instale as dependências do projeto
RUN npm install

# Copie os arquivos da aplicação para o contêiner
COPY . .

# Copie seu arquivo private.pem para dentro do contêiner
COPY private.pem .

# Altere as permissões do arquivo private.pem para garantir que apenas o proprietário possa ler e escrever
RUN chmod 600 private.pem

# Exponha a porta que sua aplicação usa
EXPOSE 5000

# Comando para iniciar a aplicação
CMD ["node", "server.js"]
