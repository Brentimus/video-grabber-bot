import os
import re
import logging
import tempfile
import asyncio
import subprocess
import json
from pathlib import Path

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import yt_dlp

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
MAX_HEIGHT = int(os.environ.get("MAX_HEIGHT", "720"))
MAX_TG_SIZE = 50 * 1024 * 1024  # Telegram limit 50 MB
MAX_DOWNLOAD_SIZE = 500 * 1024 * 1024  # safety limit to not fill disk

YT_REGEX = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([\w-]{11})"
)

TT_REGEX = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@[\w.]+/video/\d+"
    r"|https?://(?:vm|vt)\.tiktok\.com/[\w]+"
)

IG_REGEX = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:reel|p|tv)/[\w-]+"
)

COOKIES_PATH = Path("/app/cookies.txt")


def extract_urls(text: str) -> list[str]:
    yt_matches = YT_REGEX.findall(text)
    yt_urls = [f"https://www.youtube.com/watch?v={vid}" for vid in dict.fromkeys(yt_matches)]
    tt_urls = list(dict.fromkeys(TT_REGEX.findall(text)))
    ig_urls = list(dict.fromkeys(IG_REGEX.findall(text)))
    return yt_urls + tt_urls + ig_urls


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    urls = extract_urls(update.message.text)
    if not urls:
        return

    for url in urls:
        await download_and_send(update, url)


async def download_and_send(update: Update, url: str) -> None:
    msg = await update.message.reply_text("Скачиваю видео...")

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "video.mp4")
        is_tiktok = "tiktok.com" in url
        is_instagram = "instagram.com" in url
        if is_tiktok or is_instagram:
            fmt = "bestvideo*+bestaudio/best"
        else:
            fmt = (
                f"bestvideo[height<={MAX_HEIGHT}][ext=mp4]+bestaudio[ext=m4a]/"
                f"bestvideo[height<={MAX_HEIGHT}]+bestaudio/"
                f"best[height<={MAX_HEIGHT}][ext=mp4]/"
                f"best[height<={MAX_HEIGHT}]"
            )
        ydl_opts = {
            "format": fmt,
            "outtmpl": output_path,
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
        }
        if not (is_tiktok or is_instagram):
            ydl_opts["max_filesize"] = MAX_DOWNLOAD_SIZE
        if is_instagram and COOKIES_PATH.exists():
            ydl_opts["cookiefile"] = str(COOKIES_PATH)

        try:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, lambda: _download(ydl_opts, url))
        except Exception as e:
            logger.error("Download failed for %s: %s", url, e)
            await msg.edit_text(f"Не удалось скачать: {e}")
            return

        final_path = _resolve_output(tmpdir, output_path)
        if final_path is None:
            await msg.edit_text("Файл не найден после скачивания.")
            return

        file_size = final_path.stat().st_size

        if file_size > MAX_TG_SIZE:
            await msg.edit_text("Сжимаю видео...")
            compressed = Path(tmpdir) / "compressed.mp4"
            try:
                ok = await loop.run_in_executor(
                    None, lambda: _compress(final_path, compressed, MAX_TG_SIZE)
                )
            except Exception as e:
                logger.error("Compress failed for %s: %s", url, e)
                await msg.edit_text(f"Не удалось сжать видео: {e}")
                return

            if not ok:
                await msg.edit_text("Видео слишком длинное, не удаётся сжать до 50 МБ.")
                return

            final_path = compressed

        title = info.get("title", "video")[:200]
        try:
            with open(final_path, "rb") as video_file:
                await update.message.reply_video(
                    video=video_file,
                    caption=title,
                    read_timeout=120,
                    write_timeout=120,
                    supports_streaming=True,
                )
            await msg.delete()
        except Exception as e:
            logger.error("Send failed for %s: %s", url, e)
            await msg.edit_text(f"Не удалось отправить: {e}")


def _resolve_output(tmpdir: str, expected: str) -> Path | None:
    path = Path(expected)
    if path.exists():
        return path
    files = [f for f in Path(tmpdir).iterdir() if f.suffix != ".part"]
    return files[0] if files else None


def _download(opts: dict, url: str) -> dict:
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=True)


def _get_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", str(path),
        ],
        capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def _compress(src: Path, dst: Path, target_size: int) -> bool:
    duration = _get_duration(src)
    # target bitrate: leave 10% margin, subtract 128kbps for audio
    target_total_bitrate = (target_size * 8 * 0.90) / duration
    audio_bitrate = 128_000
    video_bitrate = int(target_total_bitrate - audio_bitrate)

    if video_bitrate < 200_000:
        return False

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(src),
            "-c:v", "libx264", "-b:v", str(video_bitrate),
            "-preset", "fast", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "128k",
            str(dst),
        ],
        capture_output=True, timeout=600,
    )

    return dst.exists() and dst.stat().st_size <= target_size


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
