import json
from google import genai
from dotenv import load_dotenv
import os
import logging
import time
import re


load_dotenv()

logger = logging.getLogger(__name__)

def getDescVideo(videoPath: str):
    client = genai.Client(api_key=os.getenv("GEMENI_API_KEY"))

    logger.info(f"Uploading file: {videoPath}...")
    videoFile = client.files.upload(file=videoPath)

    # Ждём активацию файла
    for _ in range(10):
        file_info = client.files.get(name=videoFile.name)
        if file_info.state == "ACTIVE":
            break
        logger.info(f"Файл {videoFile.name} ещё не активен, ожидаем...")
        time.sleep(2)
    else:
        raise RuntimeError(f"Файл {videoFile.name} не стал ACTIVE, прерываю выполнение.")

    # Обновлённый промт
    prompt = """
Ты — сценарист, диктор и автор кинематографичных текстов.

Я отправлю тебе видео или отрывок фильма.  
Проанализируй происходящее: действия, эмоции, атмосферу, контекст, настроение, взаимодействие людей или персонажей.

На основе этого:
1. Придумай короткий, выразительный **заголовок** (до 10 слов), отражающий суть сцены.  
2. Сгенерируй **текст для закадровой озвучки или внутреннего монолога**, но длину текста подстрой под длительность видео.

**Правила длины текста:**
- Средняя скорость речи диктора — примерно **2.5 слова в секунду**.  
- Рассчитай примерное количество слов = (длина видео в секундах × 2.5).  
- Твой текст не должен превышать эту длину.  
- Если видео короткое (меньше 15 секунд), делай текст максимально ёмким — 1–3 коротких предложений.  

**Стиль:**
- Если это обычное видео — напиши естественный, живой текст в духе TikTok или Reels.  
- Если это фрагмент фильма — опиши сцену **от лица главного героя**, как внутренний монолог.  
- Передавай эмоции, атмосферу и подтекст, а не просто действия.  
- Пиши выразительно, с лёгкой кинематографичностью (Netflix, HBO, A24).

**Важно:**
- Если в сцене есть персонажи без имён, придумай им западные (американские или английские) имена.  
- Не используй русские имена.
- Текст должен быть на русском  

Ответ верни строго в формате JSON без пояснений и лишних символов:
{
  "title": "название сцены или ролика",
  "content": "текст длительностью, соответствующей видео"
}
"""


    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[videoFile, prompt]
    )

    logger.info(f"Deleting file {videoFile.name}...")
    client.files.delete(name=videoFile.name)
    logger.info("File deleted.")

    # --- Извлекаем JSON из блока кода ---
    text = response.text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # --- Парсим JSON ---
    try:
        data = json.loads(text)
        return data
    except json.JSONDecodeError:
        logger.error("Ошибка парсинга JSON. Ответ от Gemini:\n" + response.text)
        return {"title": "", "content": response.text}



if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(getDescVideo("tmp/video_film.mp4"))
