import logging
import os
import time
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Импортируем ваши функции
from src.convertToMp3 import convertToMp3
from src.textFromVideo import getDescVideo
from src.createVideo import createVideo

# --- Настройка ---
load_dotenv()
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

# Получаем токен из .env
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не найден в .env файле!")
    exit()

# Убедимся, что папки существуют
os.makedirs("tmp", exist_ok=True)
os.makedirs("results", exist_ok=True)


async def process_video_pipeline(video_path: str) -> (str | None, dict | None):
    """
    Запускает полный пайплайн обработки видео.
    Возвращает (path_to_final_video, text_data) или (None, None) в случае ошибки.
    """
    try:
        logger.info(f"Начинаю обработку видео: {video_path}")
        
        # 1. Получаем текст из видео
        text_data = getDescVideo(video_path)  # Это dict {"title": "...", "content": "..."}
        if not text_data or not text_data.get("content"):
            logger.error(f"Не удалось получить текст из видео: {text_data}")
            return None, None
        
        logger.info(f"Получен текст: {text_data.get('title', 'Без заголовка')}")

        # 2. Конвертируем текст в аудио
        audio_path = convertToMp3(text_data["content"])
        if not audio_path:
            logger.error("Не удалось сгенерировать аудио.")
            return None, text_data

        logger.info(f"Аудио сгенерировано: {audio_path}")

        # 3. Создаем финальное видео
        final_file_name = str(int(time.time()))
        final_path = f"results/video_{final_file_name}.mp4"
        
        created = createVideo(audio_path, video_path, final_path)
        
        if created:
            logger.info(f"Видео успешно создано: {final_path}")
            return final_path, text_data
        else:
            logger.error("Не удалось собрать финальное видео.")
            return None, text_data
    
    except Exception as e:
        logger.error(f"Критическая ошибка в пайплайне: {e}", exc_info=True)
        return None, None

# --- Обработчики Бота ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет приветственное сообщение."""
    await update.message.reply_text(
        "Привет! 👋\n"
        "Отправь мне видео, и я добавлю к нему закадровый голос, "
        "сгенерированный ИИ на основе содержания."
    )

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает полученное видео."""
    if not update.message.video:
        await update.message.reply_text("Пожалуйста, отправьте видеофайл.")
        return

    video_file = update.message.video
    input_video_path = f"tmp/input_{video_file.file_id}.mp4"
    
    await update.message.reply_text("Видео получено. Начинаю обработку... 🤖\nЭто может занять несколько минут.")

    try:
        # 1. Скачиваем видео
        logger.info(f"Скачиваю видео: {video_file.file_id}")
        file = await video_file.get_file()
        await file.download_to_drive(input_video_path)
        logger.info(f"Видео сохранено: {input_video_path}")

        # 2. Запускаем пайплайн
        final_path, text_data = await process_video_pipeline(input_video_path)

        # 3. Отправляем результат
        if final_path and text_data:
            logger.info(f"Отправляю готовое видео: {final_path}")
            caption = text_data.get('title', 'Ваше видео готово!')
            with open(final_path, 'rb') as video_data:
                await update.message.reply_video(video=video_data, caption=caption)
        else:
            logger.error("Пайплайн не вернул результат.")
            await update.message.reply_text(
                "Произошла ошибка при обработке видео. 😢\n"
                "Попробуйте еще раз или проверьте логи."
            )

    except Exception as e:
        logger.error(f"Ошибка в handle_video: {e}", exc_info=True)
        await update.message.reply_text("Произошла критическая ошибка. 🤯")
    
    finally:
        # 4. Очистка
        if os.path.exists(input_video_path):
            os.remove(input_video_path)
            logger.info(f"Удален входной файл: {input_video_path}")
        if 'final_path' in locals() and final_path and os.path.exists(final_path):
            os.remove(final_path)
            logger.info(f"Удален финальный файл: {final_path}")

def main():
    """Запуск бота."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    
    # Добавляем обработчик для не-видео сообщений
    application.add_handler(MessageHandler(
        ~filters.VIDEO & ~filters.COMMAND, 
        lambda u, c: u.message.reply_text("Пожалуйста, отправьте мне видеофайл."))
    )

    logger.info("Бот запускается...")
    application.run_polling()


if __name__ == "__main__":
    main()