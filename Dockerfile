# Используем базовый образ Python 3.11 (slim версия)
FROM python:3.11-slim

# Устанавливаем системные зависимости (в этой версии голосовая обработка не используется, поэтому ffmpeg не требуется)
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файл зависимостей и устанавливаем их
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Копируем весь код проекта (без файла audio_processor.py, который удаляется)
COPY . .

# Команда для запуска бота
CMD ["python", "bot_4_02.py"]
