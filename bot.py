import os
import re
import logging
import tempfile
import asyncio
import subprocess
import json
from pathlib import Path

from telegram import Update, InlineQueryResultArticle, InlineQueryResultCachedVideo, InputTextMessageContent
from telegram.ext import Application, MessageHandler, InlineQueryHandler, CommandHandler, filters, ContextTypes
import yt_dlp

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
MAX_HEIGHT = int(os.environ.get("MAX_HEIGHT", "720"))
MAX_TG_SIZE = 50 * 1024 * 1024  # Telegram limit 50 MB
MAX_DOWNLOAD_SIZE = 500 * 1024 * 1024  # safety limit to not fill disk

WHITELIST_PATH = Path(os.environ.get("WHITELIST_PATH", "/app/data/whitelist.json"))


def _load_whitelist() -> set[int]:
    if WHITELIST_PATH.exists():
        return set(json.loads(WHITELIST_PATH.read_text()))
    return set()


def _save_whitelist(users: set[int]) -> None:
    WHITELIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    WHITELIST_PATH.write_text(json.dumps(sorted(users)))


allowed_users: set[int] = _load_whitelist()

YT_REGEX = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([\w-]{11})"
)

TT_REGEX = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@[\w.]+/video/\d+"
    r"|https?://(?:www\.)?tiktok\.com/t/[\w]+"
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

    if update.message.chat.type == "private" and allowed_users and update.message.from_user.id not in allowed_users:
        return

    urls = extract_urls(update.message.text)
    if not urls:
        return

    for url in urls:
        await download_and_send(update, url)


async def _download_video(url: str, tmpdir: str) -> tuple[Path, str]:
    """Download video, compress if needed. Returns (file_path, title)."""
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

    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, lambda: _download(ydl_opts, url))

    final_path = _resolve_output(tmpdir, output_path)
    if final_path is None:
        raise FileNotFoundError("Файл не найден после скачивания")

    if final_path.stat().st_size > MAX_TG_SIZE:
        compressed = Path(tmpdir) / "compressed.mp4"
        ok = await loop.run_in_executor(
            None, lambda: _compress(final_path, compressed, MAX_TG_SIZE)
        )
        if not ok:
            raise RuntimeError("Видео слишком длинное, не удаётся сжать до 50 МБ")
        final_path = compressed

    title = info.get("title", "video")[:200]
    return final_path, title


async def download_and_send(update: Update, url: str) -> None:
    msg = await update.message.reply_text("Скачиваю видео...")

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            final_path, title = await _download_video(url, tmpdir)
        except Exception as e:
            logger.error("Download failed for %s: %s", url, e)
            await msg.edit_text(f"Не удалось: {e}")
            return

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


def _is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


async def _resolve_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[int, str] | None:
    """Resolve user from argument (@username or ID), forwarded or replied message."""
    if context.args:
        arg = context.args[0]
        if arg.startswith("@"):
            try:
                chat = await context.bot.get_chat(arg)
                return chat.id, f"@{chat.username}" if chat.username else str(chat.id)
            except Exception:
                await update.message.reply_text(
                    f"Не удалось найти {arg}. Пользователь должен сначала написать боту.\n"
                    "Или перешлите сообщение от этого пользователя и ответьте на него /allow"
                )
                return None
        try:
            uid = int(arg)
            return uid, str(uid)
        except ValueError:
            await update.message.reply_text("Укажите @username или числовой ID.")
            return None

    msg = update.message
    # forwarded message sent directly (not as reply)
    if msg.forward_origin:
        origin = msg.forward_origin
        if hasattr(origin, "sender_user") and origin.sender_user:
            u = origin.sender_user
            label = f"@{u.username}" if u.username else f"{u.first_name} ({u.id})"
            return u.id, label

    # reply to someone's message or forwarded message
    reply = msg.reply_to_message
    if reply:
        if reply.forward_origin:
            origin = reply.forward_origin
            if hasattr(origin, "sender_user") and origin.sender_user:
                u = origin.sender_user
                label = f"@{u.username}" if u.username else f"{u.first_name} ({u.id})"
                return u.id, label
        if reply.from_user:
            u = reply.from_user
            label = f"@{u.username}" if u.username else f"{u.first_name} ({u.id})"
            return u.id, label

    await update.message.reply_text(
        "Способы указать пользователя:\n"
        "• /allow @username — если пользователь писал боту\n"
        "• /allow 123456789 — по числовому ID\n"
        "• Перешлите сообщение от пользователя с подписью /allow"
    )
    return None


async def cmd_allow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.message.from_user.id):
        return
    result = await _resolve_user(update, context)
    if not result:
        return
    uid, label = result
    allowed_users.add(uid)
    _save_whitelist(allowed_users)
    await update.message.reply_text(f"Пользователь {label} добавлен.")


async def cmd_deny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.message.from_user.id):
        return
    result = await _resolve_user(update, context)
    if not result:
        return
    uid, label = result
    allowed_users.discard(uid)
    _save_whitelist(allowed_users)
    await update.message.reply_text(f"Пользователь {label} удалён.")


async def cmd_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update.message.from_user.id):
        return
    if not allowed_users:
        await update.message.reply_text("Белый список пуст — ограничений нет.")
        return
    lines = [str(uid) for uid in sorted(allowed_users)]
    await update.message.reply_text("Белый список:\n" + "\n".join(lines))


async def handle_inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if allowed_users and update.inline_query.from_user.id not in allowed_users:
        return

    query = update.inline_query.query.strip()
    if not query:
        return

    urls = extract_urls(query)
    if not urls:
        return

    url = urls[0]
    user_id = update.inline_query.from_user.id

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            final_path, title = await _download_video(url, tmpdir)

            with open(final_path, "rb") as f:
                sent = await context.bot.send_video(
                    chat_id=user_id,
                    video=f,
                    disable_notification=True,
                    read_timeout=120,
                    write_timeout=120,
                )

            file_id = sent.video.file_id
            await context.bot.delete_message(user_id, sent.message_id)

        results = [InlineQueryResultCachedVideo(
            id="0",
            video_file_id=file_id,
            title=title,
            caption=title,
        )]
    except Exception as e:
        logger.error("Inline download failed for %s: %s", url, e)
        results = [InlineQueryResultArticle(
            id="0",
            title="Не удалось скачать",
            description=str(e)[:100],
            input_message_content=InputTextMessageContent(message_text=url),
        )]

    await update.inline_query.answer(results, cache_time=300)


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("allow", cmd_allow))
    app.add_handler(CommandHandler("deny", cmd_deny))
    app.add_handler(CommandHandler("whitelist", cmd_whitelist))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(InlineQueryHandler(handle_inline_query))
    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
