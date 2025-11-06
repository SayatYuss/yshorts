from src.convertToMp3 import convertToMp3
from src.textFromVideo import getDescVideo
from src.createVideo import createVideo
import logging
import time
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

videoPath = "tmp/video_for.mp4"
text = getDescVideo(videoPath)
audioPath = convertToMp3(text)
final_fileName = str(int(time.time()))
finalPath = f"results/video_{final_fileName}.mp4"

created = createVideo(audioPath, videoPath, finalPath)
