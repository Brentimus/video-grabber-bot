import os
import re
import logging
import tempfile
import asyncio
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import yt_dlp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
YT_REGEX = re.compile(
    r'(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([\w-]{11})'
)
MAX_FILE_SIZE = 50 * 1024 * 1024  # Telegram limit 50MB


def extract_youtube_urls(text: str) -> list[str]:
    matches = YT_REGEX.findall(text)
    return [f"https://www.youtube.com/watch?v={vid}" for vid in dict.fromkeys(matches)]


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    urls = extract_youtube_urls(update.message.text)
    if not urls:
        return

    for url in urls:
        await download_and_send(update, url)


async def download_and_send(update: Update, url: str):
    msg = await update.message.reply_text("Скачиваю видео...")

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "video.mp4")
        ydl_opts = {
            "format": "best[height<=360][ext=mp4]/bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]",
            "outtmpl": output_path,
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
        }

        try:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, lambda: _download(ydl_opts, url))
        except Exception as e:
            logger.error(f"Download failed: {e}")
            await msg.edit_text(f"Не удалось скачать: {e}")
            return

        # yt-dlp may add extension
        if not os.path.exists(output_path):
            files = os.listdir(tmpdir)
            if files:
                output_path = os.path.join(tmpdir, files[0])
            else:
                await msg.edit_text("Файл не найден после скачивания.")
                return

        file_size = os.path.getsize(output_path)
        if file_size > MAX_FILE_SIZE:
            await msg.edit_text("Видео слишком большое (>50MB) для Telegram.")
            return

        title = info.get("title", "video")[:200]
        try:
            await update.message.reply_video(
                video=open(output_path, "rb"),
                caption=title,
                read_timeout=120,
                write_timeout=120,
                supports_streaming=True,
            )
            await msg.delete()
        except Exception as e:
            logger.error(f"Send failed: {e}")
            await msg.edit_text(f"Не удалось отправить: {e}")


def _download(opts: dict, url: str) -> dict:
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=True)


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
