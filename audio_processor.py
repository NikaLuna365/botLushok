import os
import subprocess
import wave
import json
import logging
from vosk import Model, KaldiRecognizer

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AudioProcessor:
    def __init__(self, model_path, ffmpeg_path="ffmpeg", sample_rate=16000):
        """
        :param model_path: Путь к папке с моделью Vosk (например, "models/vosk_model")
        :param ffmpeg_path: Путь к исполняемому файлу ffmpeg (по умолчанию "ffmpeg")
        :param sample_rate: Частота дискретизации для конвертации (по умолчанию 16000 Гц)
        """
        self.model_path = model_path
        self.ffmpeg_path = ffmpeg_path
        self.sample_rate = sample_rate
        try:
            self.model = Model(self.model_path)
            logger.info("Модель Vosk успешно загружена из '%s'.", self.model_path)
        except Exception as e:
            logger.error("Ошибка загрузки модели Vosk: %s", e)
            raise e

    def convert_ogg_to_wav(self, ogg_file, wav_file):
        """
        Конвертирует аудиофайл из формата OGG в WAV с указанными параметрами.
        :param ogg_file: Путь к исходному OGG файлу.
        :param wav_file: Путь для сохранения выходного WAV файла.
        :return: True если конвертация успешна, иначе False.
        """
        command = [
            self.ffmpeg_path,
            "-i", ogg_file,
            "-ar", str(self.sample_rate),
            "-ac", "1",
            wav_file
        ]
        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True
            )
            logger.info("Конвертация файла '%s' в '%s' выполнена успешно.", ogg_file, wav_file)
        except subprocess.CalledProcessError as e:
            logger.error("Ошибка конвертации файла. ffmpeg stderr: %s", e.stderr.decode())
            return False
        return True

    def transcribe_audio(self, wav_file):
        """
        Распознаёт речь в WAV файле с помощью Vosk.
        :param wav_file: Путь к WAV файлу.
        :return: Распознанный текст.
        """
        try:
            wf = wave.open(wav_file, "rb")
        except Exception as e:
            logger.error("Ошибка открытия файла WAV: %s", e)
            return ""
        
        if wf.getnchannels() != 1 or wf.getframerate() != self.sample_rate:
            logger.warning("Файл WAV имеет неподходящие параметры. Ожидается моно с частотой %s Гц.", self.sample_rate)

        rec = KaldiRecognizer(self.model, self.sample_rate)
        rec.SetWords(True)
        result_text = ""
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                res = json.loads(rec.Result())
                result_text += " " + res.get("text", "")
        res = json.loads(rec.FinalResult())
        result_text += " " + res.get("text", "")
        wf.close()
        return result_text.strip()

    def process_audio(self, ogg_file, temp_wav_file="temp.wav"):
        """
        Обрабатывает аудиофайл в формате OGG: конвертирует в WAV, распознаёт текст, удаляет временный WAV.
        :param ogg_file: Путь к входному OGG файлу.
        :param temp_wav_file: Путь для временного WAV файла.
        :return: Распознанный текст.
        """
        if not self.convert_ogg_to_wav(ogg_file, temp_wav_file):
            logger.error("Конвертация не удалась. Прерываем процесс.")
            return ""
        transcription = self.transcribe_audio(temp_wav_file)
        try:
            os.remove(temp_wav_file)
            logger.info("Временный файл '%s' удалён.", temp_wav_file)
        except Exception as e:
            logger.warning("Не удалось удалить временный файл '%s': %s", temp_wav_file, e)
        return transcription

# Пример использования:
if __name__ == "__main__":
    MODEL_PATH = "models/vosk_model"  # Укажите правильный путь к модели Vosk
    OGG_FILE = "sample.ogg"           # Пример входного файла OGG
    
    processor = AudioProcessor(model_path=MODEL_PATH)
    text = processor.process_audio(OGG_FILE)
    print("Распознанный текст:", text)
