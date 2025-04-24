```markdown
# AI LU Telegram Bot

Интеллектуальный Telegram-бот, эмулирующий личность Николая Лу (Lushok).  
Бот понимает текст, голосовые сообщения, видеокружки и изображения, хранит историю диалога, и отвечает в его стиле с аналитичностью, иронией и саморефлексией.

---

## Возможности

- 📱 **Текстовые сообщения**  
- 🎙️ **Голосовые сообщения** (обработка в Gemini API)  
- 📷 **Изображения**  
- 🎥 **Видео-кружки**  
- 🔄 **Контекст**: хранит до 10 последних элементов истории  
- 🔀 **Гибкая логика**: DM → всегда ответ, упоминания, каналы, случайные ответы (5%)  
- 🛠 **Безопасность**: фильтрация IP, обработка ошибок API, логирование  

---

## Структура проекта

```
.
├── ai_lu_bot/                 # Пакет приложения
│   ├── __init__.py
│   ├── app.py                 # Точка входа (polling)
│   ├── handlers/
│   │   └── message.py         # Основная логика приёма и обработки
│   ├── core/
│   │   └── context.py         # In-memory manager истории переписки
│   ├── services/
│   │   └── gemini.py          # Обёртка над Gemini API с обработкой ошибок
│   └── utils/
│       └── media.py           # Скачивание медиа (image/video/audio)
├── bot_4_02.py                # Оригинальные функции: prompt & filter
├── requirements.txt           # Зависимости Python
├── Dockerfile                 # Инструкция сборки контейнера
├── docker-compose.yml         # Запуск с Docker Compose
├── Procfile                   # Для Heroku-подобных окружений
├── .gitignore
└── logs/                      # Логи (bot.log, critical_startup_error.log)
```

---

## Установка и запуск

1. **Клонировать репозиторий**  
   ```bash
   git clone https://github.com/yourorg/ai-lu-bot.git
   cd ai-lu-bot
   ```

2. **Создать файл окружения**  
   ```bash
   cp env.txt .env
   # Откройте .env и вставьте ваши ключи:
   # TELEGRAM_BOT_TOKEN=...
   # API_KEY=...
   ```

3. **Запуск через Docker Compose**  
   ```bash
   docker-compose build
   docker-compose up -d
   ```

4. **Локальный запуск без Docker**  
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   python -m ai_lu_bot.app
   ```

---

## Конфигурация

- **`TELEGRAM_BOT_TOKEN`** — токен вашего Telegram-бота.  
- **`API_KEY`** — ключ для Google Gemini API.  

Переменные берутся из файла `.env`.

---

## Использование

- `/start` — приветствие и выбор темы.  
- Отправьте **текст**, **голосовое сообщение**, **фото** или **видео-кружок** — бот ответит в стиле Николая Лу.

---

## Логирование и отладка

- **bot.log** — основной лог операций уровня INFO и выше.  
- **critical_startup_error.log** — все критические ошибки при старте приложения.  
- Для подробного отладки включите в `app.py` или `gemini.py` уровень DEBUG.

---

## Разработка и тесты

1. Ветка **main** содержит стабильную версию.  
2. Создавайте feature-ветки от main и делайте pull-request.  
3. В будущем добавим **pytest** и CI/CD.

---

## Контакты

Автор: Николай Лу (@Nik_Ly)  
GitHub: https://github.com/yourorg/ai-lu-bot  
```
