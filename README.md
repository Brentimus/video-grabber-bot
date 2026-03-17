# Video Grabber Bot

Telegram-бот, который автоматически скачивает видео из YouTube, TikTok и Instagram. Отправьте ссылку в чат — бот скачает видео и пришлёт его как видеосообщение.

## Поддерживаемые платформы

**YouTube**
- Обычные ссылки (`youtube.com/watch?v=...`)
- Короткие ссылки (`youtu.be/...`)
- Shorts (`youtube.com/shorts/...`)

**TikTok**
- Полные ссылки (`tiktok.com/@user/video/...`)
- Короткие ссылки (`vm.tiktok.com/...`, `vt.tiktok.com/...`)

**Instagram** (требуются cookies)
- Reels (`instagram.com/reel/...`)
- Посты с видео (`instagram.com/p/...`)
- IGTV (`instagram.com/tv/...`)

## Быстрый старт

1. Клонируйте репозиторий:

```bash
git clone <repo-url>
cd video-grabber-bot
```

2. Создайте файл `.env`:

```bash
cp .env.example .env
```

3. Заполните `.env` своим токеном:

```
BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
```

4. (Опционально) Для Instagram — добавьте `cookies.txt`:
   - Установите расширение **"Get cookies.txt LOCALLY"** в Chrome
   - Залогиньтесь в Instagram
   - Экспортируйте куки и сохраните как `cookies.txt` в корень проекта

5. Запустите:

```bash
docker compose up -d
```

## Переменные окружения

| Переменная   | Обязательная | По умолчанию | Описание                         |
|-------------|-------------|-------------|----------------------------------|
| `BOT_TOKEN` | да          | —           | Токен Telegram-бота от BotFather |
| `MAX_HEIGHT`| нет         | `720`       | Максимальная высота видео (px)   |

## Запуск без Docker

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN=your-token
python bot.py
```

Требуется установленный `ffmpeg` в системе.

## Особенности

- Видео больше 50 МБ автоматически сжимается через ffmpeg
- Защита от переполнения диска (лимит скачивания 500 МБ)
- Вертикальные видео скачиваются в нормальном качестве (до 720p)
- Временные файлы удаляются сразу после отправки

## Ограничения

- Максимальный размер файла для Telegram — 50 МБ (лимит Bot API)
- Куки Instagram могут протухнуть — потребуется повторный экспорт
