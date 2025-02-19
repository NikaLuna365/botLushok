FROM python:3.9-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-rus \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Установка дополнительных утилит (если потребуется для ffmpeg)
# RUN apt-get install -y <дополнительные-пакеты>

# Установка рабочей директории
WORKDIR /app

# Копирование файла зависимостей и установка pip-зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование всего исходного кода
COPY . .

# Определяем volume для логов (чтобы они сохранялись вне контейнера)
VOLUME ["/app/logs"]

# Запуск бота
CMD ["python", "bot_4_02.py"]
