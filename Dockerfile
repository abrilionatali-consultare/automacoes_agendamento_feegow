# Imagem base leve e estável
FROM python:3.11-slim

# Evita prompts interativos
ENV DEBIAN_FRONTEND=noninteractive

# Define diretório de trabalho
WORKDIR /app

# Instala dependências de sistema (segurança + requests/yaml)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copia requirements primeiro (melhor cache)
COPY requirements.txt .

# Atualiza pip e instala dependências Python
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copia todo o projeto
COPY . .

# Variáveis de ambiente padrão do Streamlit
ENV STREAMLIT_SERVER_PORT=7860
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Porta obrigatória do Hugging Face
EXPOSE 7860

# Comando de inicialização
CMD ["streamlit", "run", "app.py"]
