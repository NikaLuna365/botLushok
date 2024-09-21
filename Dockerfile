# Используем базовый образ Python
FROM python:3.9-slim

# Устанавливаем ffmpeg и необходимые системные пакеты
RUN apt-get update && apt-get install -y ffmpeg

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файл с зависимостями
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все файлы проекта в контейнер
COPY . .

# Команда для запуска бота
CMD ["python", "bot_4_02.py"]
