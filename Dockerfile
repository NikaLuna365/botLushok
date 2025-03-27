# Используем базовый образ Python 3.11 (slim версия)
FROM python:3.11-slim

# Рабочая директория
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем Python-пакеты, обновляем pip, не используем кэш
# Добавляем --verbose для более подробного вывода установки
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --verbose -r requirements.txt

# --- ШАГ ОТЛАДКИ 1: Выводим список установленных пакетов в лог сборки ---
RUN echo "--- Installed packages: ---" && pip freeze && echo "--- End of package list ---"

# Копируем весь остальной код проекта в рабочую директорию
COPY . .

# --- ШАГ ОТЛАДКИ 2: Команда для запуска контейнера ---
# Сначала пытаемся импортировать библиотеку, потом запускаем основной скрипт
CMD ["sh", "-c", "echo '--- Attempting basic import ---' && python -c 'import google.generativeai; print(\"[OK] google.generativeai imported successfully!\")' && echo '--- Starting main script (bot_4_02.py) ---' && python bot_4_02.py || echo '*** Import failed or script exited with error ***'"]

# Оригинальная команда (закомментирована на время отладки):
# CMD ["python", "bot_4_02.py"]
