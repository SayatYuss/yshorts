import logging
import os
import asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile

# --- НОВЫЙ ИМПОРТ ---
# Импортируем ваш новый класс пайплайна
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

# Папки теперь создаются внутри VideoPipeline,
# но на всякий случай оставим проверку и здесь.
os.makedirs("tmp", exist_ok=True)
os.makedirs("results", exist_ok=True)

# --- Обработчики Бота (Aiogram) ---

router = Router()

@router.message(Command("start"))
async def start_handler(message: Message):
    """Отправляет приветственное сообщение."""
    await message.answer(
        "Привет! 👋\n"
        "Отправь мне видео, и я добавлю к нему закадровый голос, "
        "сгенерированный ИИ на основе содержания."
    )

@router.message(F.video)
async def handle_video(message: Message, bot: Bot, pipeline: VideoPipeline): # <-- 3. Получаем pipeline
    """Обрабатывает полученное видео."""
    if not message.video:
        await message.answer("Пожалуйста, отправьте видеофайл.")
        return

    video_file = message.video
    input_video_path = f"tmp/input_{video_file.file_id}.mp4"
    
    await message.answer("Видео получено. Начинаю обработку... 🤖\nЭто может занять несколько минут.")

    try:
        # 1. Скачиваем видео
        logger.info(f"Скачиваю видео: {video_file.file_id}")
        file_info = await bot.get_file(video_file.file_id)
        await bot.download_file(file_info.file_path, destination=input_video_path)
        logger.info(f"Видео сохранено: {input_video_path}")

        # 2. Запускаем пайплайн
        # --- ИЗМЕНЕНИЕ ---
        # Вызываем асинхронный метод из вашего класса
        final_path, text_data = await pipeline.run_async(input_video_path)

        # 3. Отправляем результат
        if final_path and text_data:
            logger.info(f"Отправляю готовое видео: {final_path}")
            caption = text_data.get('title', 'Ваше видео готово!')
            
            await message.answer_video(
                video=FSInputFile(final_path), 
                caption=caption
            )
        else:
            logger.error("Пайплайн не вернул результат.")
            await message.answer(
                "Произошла ошибка при обработке видео. 😢\n"
                "Попробуйте еще раз или проверьте логи."
            )

    except Exception as e:
        logger.error(f"Ошибка в handle_video: {e}", exc_info=True)
        await message.answer("Произошла критическая ошибка. 🤯")
    
    finally:
        # 4. Очистка
        if os.path.exists(input_video_path):
            os.remove(input_video_path)
            logger.info(f"Удален входной файл: {input_video_path}")
        if 'final_path' in locals() and final_path and os.path.exists(final_path):
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
    
    # --- ИЗМЕНЕНИЕ ---
    # 1. Создаем один экземпляр пайплайна
    pipeline_instance = VideoPipeline()
    
    # 2. Передаем его в Dispatcher при инициализации
    # Он станет доступен во всех хэндлерах по имени аргумента "pipeline"
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