from google import genai
from dotenv import load_dotenv
import os
import logging
import time  # <-- 1. Добавьте этот импорт

load_dotenv()

logger = logging.getLogger(__name__)

def getDescVideo(videoPath: str):
    client = genai.Client(api_key=os.getenv("GEMENI_API_KEY"))

    logger.info(f"Uploading file: {videoPath}...")
    videoFile = client.files.upload(file=videoPath)

    for _ in range(10):  # максимум 10 попыток
        file_info = client.files.get(name=videoFile.name)
        if file_info.state == "ACTIVE":
            break
        logger.info(f"Файл {videoFile.name} ещё не активен, ожидаем...")
        time.sleep(2)
    else:
        raise RuntimeError(f"Файл {videoFile.name} не стал ACTIVE, прерываю выполнение.")


    prompt = """Ты — сценарист и диктор. Я отправлю тебе видео. Проанализируй, что происходит на видео — действия, эмоции, место, атмосферу. На основе этого создай короткий, связный и выразительный текст для закадровой озвучки (5–10 предложений, до 100 слов).  
    Говори естественно, как в роликах TikTok или Reels.  
    Передавай смысл, эмоции и настроение сцены, а не очевидные детали.  
    Можно добавить лёгкую философию, юмор или мотивацию, если подходит.  
    В ответе выведи только готовый текст для озвучки — без пояснений, заголовков или лишних слов."""
    
    response = client.models.generate_content(
        model="gemini-2.5-flash", 
        contents=[
            videoFile,
            prompt
        ]
    )
    
    logger.info(f"Deleting file {videoFile.name}...")
    client.files.delete(name=videoFile.name)
    logger.info("File deleted.")

    return response.text


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    getDescVideo("tmp/video_for.mp4")