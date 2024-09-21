# Используем базовый образ с Python
FROM python:3.9-slim

# Устанавливаем зависимости для работы с аудио (если это необходимо в будущем)
RUN apt-get update && apt-get install -y ffmpeg

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файл с зависимостями
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код бота в контейнер
COPY . .

# Задаем переменные окружения для API-ключей
ENV TELEGRAM_BOT_TOKEN=<AIzaSyCNcAZXxvuSB0I249JXsEQnbA8K5zgi0Kg>
ENV API_KEY=<7211227866:AAGXvLKse9pd8Jq9NllbdPlrmSUD9lCYHOU>

# Команда для запуска бота
CMD ["python", "bot_4_02.py"]
