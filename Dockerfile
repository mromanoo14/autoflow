FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY comum/ comum/
COPY servicos/ servicos/
# O comando de cada serviço é definido no docker-compose.yml
