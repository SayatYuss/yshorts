from elevenlabs import ElevenLabs, save
import os
import time
from dotenv import load_dotenv
import logging

load_dotenv()
logger = logging.getLogger(__name__)

def convertToMp3(text: str) -> str:
    api = os.getenv("ELEVEN_LAB_API")

    client = ElevenLabs(
        base_url="https://api.elevenlabs.io",
        api_key=api
    )

    response = client.text_to_speech.convert(
        voice_id="FGY2WhTYpPnrIDTdsKH5",
        output_format="mp3_44100_128",
        text=text,
        model_id="eleven_multilingual_v2"
    )

    os.makedirs("tmp", exist_ok=True)
    filename = f"tmp/{int(time.time())}.mp3"
    save(response, filename)

    logger.info(f"Файл сохранён: {filename}")

    return filename

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    convertToMp3("а")
