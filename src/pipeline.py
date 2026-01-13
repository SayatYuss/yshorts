# src/pipeline.py

import logging
import os
import time
import json
import re
import subprocess
import asyncio
from dotenv import load_dotenv
from google import genai
from elevenlabs import ElevenLabs, save

# Загружаем .env
load_dotenv()
logger = logging.getLogger(__name__)

class VideoPipeline:
    """
    Инкапсулирует полный пайплайн:
    1. Gemini: Текст из видео
    2. ElevenLabs + FFprobe: Контекстная озвучка по фразам + .SRT субтитры
    3. FFmpeg: Сборка видео, замена аудио и вжигание субтитров
    """
    
    def __init__(self):
        os.makedirs("tmp", exist_ok=True)
        os.makedirs("results", exist_ok=True)
        
        # Инициализируем клиент ElevenLabs один раз
        self.elevenlabs_api_key = os.getenv("ELEVEN_LAB_API")
        if not self.elevenlabs_api_key:
            logger.error("ELEVEN_LAB_API не найден в .env!")
            self.elevenlabs_client = None
        else:
            self.elevenlabs_client = ElevenLabs(
                base_url="https://api.elevenlabs.io",
                api_key=self.elevenlabs_api_key
            )

    # --- ШАГ 1: ГЕНЕРАЦИЯ ТЕКСТА ---
    def get_desc_video(self, videoPath: str) -> dict:
        """
        [Логика из textFromVideo.py]
        Получает JSON с title и content из видео.
        """
        client = genai.Client(api_key=os.getenv("GEMENI_API_KEY"))
        logger.info(f"Uploading file: {videoPath}...")
        
        videoFile = None
        try:
            videoFile = client.files.upload(file=videoPath)

            # Ждём активацию файла
            for _ in range(10):
                file_info = client.files.get(name=videoFile.name)
                if file_info.state == "ACTIVE":
                    break
                logger.info(f"Файл {videoFile.name} ещё не активен, ожидаем...")
                time.sleep(2)
            else:
                raise RuntimeError(f"Файл {videoFile.name} не стал ACTIVE.")

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

            # Удаляем файл сразу после получения ответа
            logger.info(f"Deleting file {videoFile.name}...")
            client.files.delete(name=videoFile.name)
            logger.info("File deleted.")

            text = response.text.strip()
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

            data = json.loads(text)
            return data
            
        except Exception as e:
            logger.error(f"Ошибка в get_desc_video: {e}", exc_info=True)
            return {"title": "", "content": f"Ошибка обработки: {e}"}
            
        finally:
            # Дополнительная очистка на случай сбоя до удаления
            if videoFile and client:
                try:
                    client.files.delete(name=videoFile.name)
                except Exception:
                    pass # Игнорируем ошибку, если файл уже удален

    # --- ШАГ 2: Генерация Аудио и SRT (Вспомогательные функции) ---

    def _format_srt_time(self, seconds: float) -> str:
        """Вспомогательная функция для формата времени SRT (ЧЧ:ММ:СС,ММС)"""
        millis = int((seconds - int(seconds)) * 1000)
        seconds = int(seconds)
        minutes = seconds // 60
        hours = minutes // 60
        seconds = seconds % 60
        minutes = minutes % 60
        return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"

    def _get_audio_duration(self, file_path: str) -> float:
        """Получает длительность аудиофайла с помощью ffprobe."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            return float(result.stdout.strip())
        except Exception as e:
            logger.error(f"Ошибка при получении длительности файла {file_path}: {e}")
            return 0.0

    def _smart_text_splitter(self, text: str, max_chars: int = 45) -> list[str]:
        """
        "Умно" делит текст на короткие фразы, подходящие для субтитров.
        Делит по знакам препинания И по максимальной длине.
        """
        # Заменяем переносы строк на пробелы
        text = text.replace('\n', ' ')
        
        # Сначала делим по основным знакам препинания (сохраняя их)
        base_phrases = re.split(r'([.!?,,])', text)
        # Объединяем обратно: ["Phrase 1,", "Phrase 2.", ...]
        base_phrases = ["".join(i).strip() for i in zip(base_phrases[0::2], base_phrases[1::2])]
        base_phrases = [p for p in base_phrases if p] # Убираем пустые

        final_chunks = []
        current_chunk = ""

        for phrase in base_phrases:
            # Если фраза сама по себе слишком длинная, делим ее по словам
            if len(phrase) > max_chars:
                words = phrase.split()
                temp_line = ""
                for word in words:
                    if len(temp_line) + len(word) + 1 > max_chars:
                        final_chunks.append(temp_line.strip())
                        temp_line = word
                    else:
                        temp_line += " " + word
                final_chunks.append(temp_line.strip()) # Добавляем остаток
                continue # Переходим к следующей фразе

            # Если добавление новой фразы превысит лимит,
            # сохраняем текущую и начинаем новую.
            if len(current_chunk) + len(phrase) + 1 > max_chars:
                final_chunks.append(current_chunk.strip())
                current_chunk = phrase
            else:
                # "Наклеиваем" фразу на текущую
                current_chunk += " " + phrase
                current_chunk = current_chunk.strip()

        # Не забываем добавить последний оставшийся "кусок"
        if current_chunk:
            final_chunks.append(current_chunk.strip())

        # Финальная очистка от пустых строк
        return [chunk for chunk in final_chunks if chunk]

    # --- ШАГ 2 (Основной): Генерация Аудио и SRT ---
    
    def generate_audio_and_srt(self, text: str, base_filename: str) -> (str | None, str | None): # type: ignore
        """
        Генерирует аудио по коротким фразам С УЧЕТОМ КОНТЕКСТА,
        склеивает его и создает SRT-файл на лету.
        """
        if not self.elevenlabs_client:
            logger.error("Клиент ElevenLabs не инициализирован.")
            return None, None

        # 1. Используем наш "умный" разделитель
        text_chunks = self._smart_text_splitter(text)
        logger.info(f"Текст разделен на {len(text_chunks)} коротких фраз.")

        if not text_chunks:
            logger.error("Не удалось разбить текст на фразы.")
            return None, None

        srt_path = f"tmp/{base_filename}.srt"
        audio_chunks_paths = []
        current_time = 0.0
        pause = 0.1 # Пауза между субтитрами в секундах

        try:
            with open(srt_path, "w", encoding="utf-8") as srt_file:
                for i, chunk_text in enumerate(text_chunks):
                    
                    # Получаем контекст для ElevenLabs
                    previous_text = text_chunks[i - 1] if i > 0 else None
                    next_text = text_chunks[i + 1] if i < len(text_chunks) - 1 else None
                    
                    logger.info(f"Генерирую аудио для: {chunk_text}")
                    
                    # 2. Генерируем аудио-фрагмент с контекстом
                    response = self.elevenlabs_client.text_to_speech.convert(
                        voice_id="FGY2WhTYpPnrIDTdsKH5",
                        output_format="mp3_44100_128",
                        text=chunk_text,
                        model_id="eleven_multilingual_v2",
                        previous_text=previous_text,
                        next_text=next_text
                    )
                    
                    chunk_path = f"tmp/{base_filename}_chunk_{i}.mp3"
                    save(response, chunk_path)
                    audio_chunks_paths.append(chunk_path)
                    
                    # 3. Получаем длительность фрагмента
                    duration = self._get_audio_duration(chunk_path)
                    if duration == 0.0:
                        logger.warning(f"Не удалось получить длительность для {chunk_path}")
                        continue
                    
                    # 4. Пишем в SRT-файл
                    start_time_str = self._format_srt_time(current_time)
                    end_time = current_time + duration
                    end_time_str = self._format_srt_time(end_time)
                    
                    srt_file.write(f"{i + 1}\n")
                    srt_file.write(f"{start_time_str} --> {end_time_str}\n")
                    srt_file.write(f"{chunk_text}\n\n")
                    
                    # Двигаем "курсор" времени вперед + пауза
                    current_time = end_time + pause

            # 5. Склеиваем все аудио-фрагменты в один файл
            final_audio_path = f"tmp/{base_filename}_final.mp3"
            concat_list_path = f"tmp/{base_filename}_concat.txt"
            
            with open(concat_list_path, "w") as f:
                for chunk_path in audio_chunks_paths:
                    f.write(f"file '{os.path.basename(chunk_path)}'\n") 
                    # Добавляем "тишину" между файлами, чтобы аудио совпадало с паузами в SRT
                    f.write(f"duration {pause}\n")
            
            # Запускаем ffmpeg для склейки. -safe 0 нужен для путей
            concat_cmd = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list_path,
                "-c", "copy",
                final_audio_path,
                "-y"
            ]
            # cwd="tmp" гарантирует, что ffmpeg найдет файлы из concat_list_path
            subprocess.run(concat_cmd, check=True, capture_output=True, text=True)
            
            logger.info(f"Финальное аудио собрано: {final_audio_path}")
            return final_audio_path, srt_path

        except Exception as e:
            logger.error(f"Ошибка в generate_audio_and_srt: {e}", exc_info=True)
            return None, None
        finally:
            # Очистка временных файлов (chunk'ов и txt)
            for chunk_path in audio_chunks_paths:
                if os.path.exists(chunk_path): os.remove(chunk_path)
            if 'concat_list_path' in locals() and os.path.exists(concat_list_path):
                os.remove(concat_list_path)

    # --- ШАГ 3: СБОРКА ВИДЕО ---
    def create_video(self, audio_path: str, video_path: str, final_path: str, srt_path: str) -> bool:
        """
        Собирает видео, заменяет аудио и "вжигает" субтитры.
        """
        if not audio_path or not os.path.exists(audio_path):
            logger.error(f"Аудиофайл не найден: {audio_path}")
            return False
        
        if not srt_path or not os.path.exists(srt_path):
            logger.error(f"SRT-файл не найден: {srt_path}")
            # Не можем продолжать без субтитров, т.к. команда ffmpeg их требует
            return False

        # Экранирование пути для Windows (если вдруг понадобится)
        # В Linux/Docker это не обязательно, но и не мешает
        srt_path_escaped = srt_path.replace(':', '\\\\:')

        cmd = [
            "ffmpeg",
            "-i", video_path,    # Вход 0: Видео
            "-i", audio_path,    # Вход 1: Аудио
            
            # vf (video filter) "subtitles" вжигает субтитры
            # Добавляем стиль: тень/обводка для читаемости
            "-vf", f"subtitles={srt_path_escaped}:force_style='FontName=Arial,FontSize=18,PrimaryColour=&HFFFFFF,BorderStyle=3,BackColour=&H80000000,Shadow=0,MarginV=25'",            
            "-c:v", "libx264",   # Перекодируем видео (обязательно для вжигания)
            "-crf", "23",        # Качество (18-28, чем ниже, тем лучше)
            "-preset", "fast",   # Скорость кодирования (ultrafast, superfast, fast, medium)
            "-c:a", "aac",       # Кодек для аудио
            
            "-map", "0:v:0",     # Берем видео из входа 0
            "-map", "1:a:0",     # Берем аудио из входа 1
            
            "-shortest",         # Заканчиваем, когда самый короткий поток (аудио) закончится
            final_path,
            "-y"                 # Перезаписывать без вопроса
        ]

        try:
            logger.info("Начинаю сборку видео с субтитрами...")
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logging.info("Видео успешно собрано: %s", final_path)
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка FFmpeg при сборке видео: {e.stderr}")
            return False
        finally:
            # Очищаем финальные временные файлы
            if os.path.exists(audio_path):
                os.remove(audio_path)
                logging.info("Временный аудиофайл удалён: %s", audio_path)
            if os.path.exists(srt_path):
                os.remove(srt_path)
                logging.info("Временный SRT-файл удалён: %s", srt_path)

    # --- ПУБЛИЧНЫЕ МЕТОДЫ-ПАЙПЛАЙНЫ ---

    def run_sync(self, input_video_path: str) -> (str | None, dict | None): #type: ignore
        """
        Выполняет весь пайплайн СИНХРОННО.
        """
        logger.info(f"[SYNC] Начинаю обработку видео: {input_video_path}")
        srt_path = None
        audio_path = None
        try:
            # 1. Текст
            text_data = self.get_desc_video(input_video_path)
            if not text_data or not text_data.get("content"):
                logger.error(f"[SYNC] Не удалось получить текст.")
                return None, text_data
            
            # 2. Аудио + SRT (Новый метод)
            base_filename = str(int(time.time()))
            audio_path, srt_path = self.generate_audio_and_srt(text_data["content"], base_filename)
            
            if not audio_path or not srt_path:
                logger.error("[SYNC] Не удалось сгенерировать аудио и SRT.")
                return None, text_data

            # 3. Видео
            final_path = f"results/video_{base_filename}.mp4"
            created = self.create_video(audio_path, input_video_path, final_path, srt_path)
            
            return (final_path, text_data) if created else (None, text_data)
        
        except Exception as e:
            logger.error(f"[SYNC] Критическая ошибка в пайплайне: {e}", exc_info=True)
            # Доп. очистка на случай падения
            if audio_path and os.path.exists(audio_path): os.remove(audio_path)
            if srt_path and os.path.exists(srt_path): os.remove(srt_path)
            return None, None

    async def run_async(self, input_video_path: str) -> (str | None, dict | None): #type: ignore
        """
        Выполняет весь пайплайн АСИНХРОННО (в потоках).
        """
        logger.info(f"[ASYNC] Начинаю обработку видео: {input_video_path}")
        srt_path = None
        audio_path = None
        try:
            # 1. Текст (в потоке)
            text_data = await asyncio.to_thread(self.get_desc_video, input_video_path)
            if not text_data or not text_data.get("content"):
                logger.error(f"[ASYNC] Не удалось получить текст.")
                return None, text_data
            
            # 2. Аудио + SRT (в потоке)
            base_filename = str(int(time.time()))
            audio_path, srt_path = await asyncio.to_thread(
                self.generate_audio_and_srt, text_data["content"], base_filename
            )
            
            if not audio_path or not srt_path:
                logger.error("[ASYNC] Не удалось сгенерировать аудио и SRT.")
                return None, text_data

            # 3. Видео (в потоке)
            final_path = f"results/video_{base_filename}.mp4"
            created = await asyncio.to_thread(
                self.create_video, audio_path, input_video_path, final_path, srt_path
            )
            
            return (final_path, text_data) if created else (None, text_data)
        
        except Exception as e:
            logger.error(f"[ASYNC] Критическая ошибка в пайплайне: {e}", exc_info=True)
            if audio_path and os.path.exists(audio_path): os.remove(audio_path)
            if srt_path and os.path.exists(srt_path): os.remove(srt_path)
            return None, None

# --- БЛОК ДЛЯ ТЕСТИРОВАНИЯ ---
if __name__ == "__main__":
    # Этот блок можно использовать для быстрого теста `run_sync`
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    
    TEST_VIDEO_PATH = "tmp/video_for.mp4" # Убедитесь, что этот файл существует
    
    if not os.path.exists(TEST_VIDEO_PATH):
        logger.warning(f"Тестовый файл не найден: {TEST_VIDEO_PATH}")
        logger.warning("Пожалуйста, поместите видео в tmp/video_for.mp4 для теста.")
    else:
        logger.info("--- ЗАПУСК СИНХРОННОГО ТЕСТА ПАЙПЛАЙНА ---")
        pipeline = VideoPipeline()
        final_video, data = pipeline.run_sync(TEST_VIDEO_PATH)
        
        if final_video:
            logger.info(f"--- ТЕСТ УСПЕШЕН ---")
            logger.info(f"Финальное видео: {final_video}")
            logger.info(f"Заголовок: {data.get('title')}")
        else:
            logger.error(f"--- ТЕСТ ПРОВАЛЕН ---")
            logger.error("Не удалось создать видео. Проверьте логи.")