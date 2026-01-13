# bot.py
import logging
import os
import asyncio
import time # <-- Добавлен time для base_filename
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile

# Импортируем ваш класс пайплайна
from src.pipeline import VideoPipeline 

# --- Настройка ---
load_dotenv()
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

# Получаем токен из .env
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN не найден в .env file!")
    exit()

# Папки создаются в VideoPipeline
os.makedirs("tmp", exist_ok=True)
os.makedirs("results", exist_ok=True)

# --- Обработчики Бота (Aiogram) ---

router = Router()

@router.message(Command("start"))
async def start_handler(message: Message):
    """Отправляет приветственное сообщение."""
    await message.answer(
        "Привет! 👋\n"
        "Отправь мне видео, и я добавлю к нему закадровый голос "
        "и субтитры."
    )

@router.message(F.video)
async def handle_video(message: Message, bot: Bot, pipeline: VideoPipeline):
    """Обрабатывает полученное видео с пошаговым обновлением статуса."""
    if not message.video:
        await message.answer("Пожалуйста, отправьте видеофайл.")
        return

    video_file = message.video
    input_video_path = f"tmp/input_{video_file.file_id}.mp4"
    final_path = None # Для блока finally
    
    # 1. Отправляем и сохраняем сообщение о статусе
    status_message = await message.answer("Видео получено. Скачиваю... 📥")

    try:
        # 2. Скачиваем видео
        logger.info(f"Скачиваю видео: {video_file.file_id}")
        file_info = await bot.get_file(video_file.file_id)
        await bot.download_file(file_info.file_path, destination=input_video_path)
        logger.info(f"Видео сохранено: {input_video_path}")

        # --- 3. Запускаем пайплайн ---
        
        # Шаг 1: Текст
        await status_message.edit_text("Этап 1/3: Анализирую видео... (Gemini) 🧠")
        text_data = await asyncio.to_thread(pipeline.get_desc_video, input_video_path)
        
        if not text_data or not text_data.get("content"):
            logger.error("Пайплайн не вернул текст.")
            await status_message.edit_text("Ошибка: Не удалось получить текст из видео. 😢")
            return

        # Шаг 2: Аудио и Субтитры
        await status_message.edit_text("Этап 2/3: Генерирую озвучку и субтитры... (ElevenLabs + FFmpeg) 🎙️")
        base_filename = str(int(time.time()))
        audio_path, srt_path = await asyncio.to_thread(
            pipeline.generate_audio_and_srt, text_data["content"], base_filename
        )

        if not audio_path or not srt_path:
            logger.error("Пайплайн не вернул аудио/srt.")
            await status_message.edit_text("Ошибка: Не удалось сгенерировать аудио. 😢")
            return

        # Шаг 3: Сборка
        await status_message.edit_text("Этап 3/3: Собираю финальное видео... (FFmpeg) 🎬")
        final_path = f"results/video_{base_filename}.mp4"
        created = await asyncio.to_thread(
            pipeline.create_video, audio_path, input_video_path, final_path, srt_path
        )

        # 4. Отправляем результат
        if created and final_path:
            logger.info(f"Отправляю готовое видео: {final_path}")
            caption = text_data.get('title', 'Ваше видео готово!')
            
            await status_message.edit_text("Готово! Отправляю видео... 🚀")
            await message.answer_video(
                video=FSInputFile(final_path), 
                caption=caption
            )
            # Удаляем сообщение о статусе
            await status_message.delete()
        
        else:
            logger.error("Пайплайн не смог создать финальное видео.")
            await status_message.edit_text("Ошибка: Не удалось собрать финальное видео. 😢")

    except Exception as e:
        logger.error(f"Ошибка в handle_video: {e}", exc_info=True)
        # Проверяем, существует ли еще сообщение, прежде чем его редактировать
        if status_message:
            await status_message.edit_text("Произошла критическая ошибка. 🤯")
    
    finally:
        # 5. Очистка
        if os.path.exists(input_video_path):
            os.remove(input_video_path)
            logger.info(f"Удален входной файл: {input_video_path}")
        if final_path and os.path.exists(final_path):
            os.remove(final_path)
            logger.info(f"Удален финальный файл: {final_path}")

@router.message()
async def handle_other_messages(message: Message):
    """Обработчик для всех других типов сообщений."""
    await message.reply("Пожалуйста, отправьте мне видеофайл.")

# --- Функция Запуска ---

async def main():
    """Запуск бота."""
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    # 1. Создаем один экземпляр пайплайна
    pipeline_instance = VideoPipeline()
    
    # 2. Передаем его в Dispatcher
    dp = Dispatcher(pipeline=pipeline_instance)
    
    dp.include_router(router)
    
    logger.info("Бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную.")