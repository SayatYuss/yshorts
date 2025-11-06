from src.convertToMp3 import convertToMp3
import logging
import subprocess
import os

logger = logging.getLogger(__name__)

def createVideo(audioPath: str, videoPath: str, finalPath: str) -> bool:
    result = True
    cmd = [
        "ffmpeg",
        "-i", videoPath,
        "-i", audioPath,
        "-c:v", "copy",
        "-c:a", "aac",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest",
        finalPath,
        "-y"
    ]

    try:
        subprocess.run(cmd, check=True)
        logging.info("Видео успешно собрано: %s", finalPath)
    except:
        result = False
    # finally:
    #     if os.path.exists(audioPath):
    #         os.remove(audioPath)
    #         logging.info("Временный аудиофайл удалён: %s", audioPath)
    
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

