# YouTube Telegram Bot

Telegram-бот, который автоматически скачивает и отправляет YouTube-видео. Отправьте ссылку на YouTube в чат — бот скачает видео и пришлёт его как видеосообщение.

Поддерживаются:
- Обычные ссылки (`youtube.com/watch?v=...`)
- Короткие ссылки (`youtu.be/...`)
- Shorts (`youtube.com/shorts/...`)

## Требования

- Docker и Docker Compose
- Telegram Bot Token (получить у [@BotFather](https://t.me/BotFather))

## Быстрый старт

1. Клонируйте репозиторий:

```bash
git clone <repo-url>
cd yt-telegram-bot
```

2. Создайте файл `.env` на основе примера:

```bash
cp .env.example .env
```

3. Заполните `.env` своим токеном:

```
BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
```

4. Запустите:

```bash
docker compose up -d
```

Остановить:

```bash
docker compose down
```

## Переменные окружения

| Переменная   | Обязательная | По умолчанию | Описание                          |
|-------------|-------------|-------------|-----------------------------------|
| `BOT_TOKEN` | да          | —           | Токен Telegram-бота от BotFather  |
| `MAX_HEIGHT`| нет         | `360`       | Максимальная высота видео (px)    |

## Запуск без Docker

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN=your-token
python bot.py
```

Требуется установленный `ffmpeg` в системе.

## Ограничения

- Максимальный размер файла — 50 MB (лимит Telegram Bot API)
- Видео скачивается в разрешении до 360p по умолчанию (настраивается через `MAX_HEIGHT`)
