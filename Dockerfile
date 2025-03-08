# Используем базовый образ Python 3.11 (slim версия)
FROM python:3.11-slim

# Рабочая директория
WORKDIR /app

# Копируем файл зависимостей и устанавливаем Python-пакеты
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Копируем весь код проекта (убедитесь, что файл audio_processor.py удалён)
COPY . .

# Команда для запуска бота
CMD ["python", "bot_4_02.py"]
