# Используем базовый образ Python 3.11 (slim версия)
FROM python:3.11-slim

# Устанавливаем системные зависимости (например, ffmpeg)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файл зависимостей и устанавливаем их
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Копируем весь код проекта
COPY . .

# Команда для запуска бота
CMD ["python", "bot_4_02.py"]
