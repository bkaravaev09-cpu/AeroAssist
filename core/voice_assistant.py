import pyttsx3
import speech_recognition as sr
import webbrowser
import subprocess

class PolishVoiceAssistant:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300  # Чувствительность микрофона
        self.recognizer.dynamic_energy_threshold = True

    def _get_engine(self):
        engine = pyttsx3.init()
        voices = engine.getProperty('voices')
        for voice in voices:
            if "polish" in voice.name.lower() or "pl" in voice.id.lower() or "paulina" in voice.name.lower():
                engine.setProperty('voice', voice.id)
                break
        engine.setProperty('rate', 155)
        return engine

    def speak(self, text):
        try:
            print(f"[АСИСТЕНТ]: {text}")
            engine = self._get_engine()
            engine.say(text)
            engine.runAndWait()
            del engine
        except Exception as e:
            print(f"[ОШИБКА ОЗВУЧКИ]: {e}")

    def listen_and_execute(self):
        # 1. Сначала говорим и завершаем фразу
        self.speak("Słucham polecenia")

        # 2. Только после завершения речи открываем микрофон
        try:
            with sr.Microphone() as source:
                print("[МИКРОФОН]: Калибровка шума...")
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                print("[МИКРОФОН]: Говорите команду...")
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)
                
                print("[МИКРОФОН]: Распознавание польской речи...")
                command = self.recognizer.recognize_google(audio, language="pl-PL").lower().strip()
                print(f"[РАСПОЗНАНО]: '{command}'")
                self._dispatch(command)
        except sr.WaitTimeoutError:
            print("[МИКРОФОН]: Таймаут ожидания речи")
            self.speak("Koniec czasu oczekiwania")
        except sr.UnknownValueError:
            print("[МИКРОФОН]: Речь не удалось разобрать")
            self.speak("Nie zrozumiałam polecenia")
        except Exception as e:
            print(f"[ОШИБКА МИКРОФОНА]: {e}")
            self.speak("Problem z mikrofonem")

    def _dispatch(self, cmd):
        if "szukaj" in cmd or "znajdź" in cmd:
            query = cmd.replace("szukaj w google", "").replace("szukaj", "").replace("znajdź", "").strip()
            self.speak(f"Szukam w Google: {query}")
            webbrowser.open(f"https://www.google.com/search?q={query}")

        elif "youtube" in cmd or "jutub" in cmd:
            self.speak("Otwieram YouTube")
            webbrowser.open("https://youtube.com")

        elif "przeglądarka" in cmd or "internet" in cmd:
            self.speak("Uruchamiam przeglądarkę")
            webbrowser.open("https://google.pl")

        elif "klawiatura" in cmd or "klawiaturę" in cmd:
            self.speak("Uruchamiam klawiaturę ekranową")
            subprocess.Popen(["osk.exe"])

        elif "notatnik" in cmd:
            self.speak("Otwieram notatnik")
            subprocess.Popen(["notepad.exe"])

        elif "kalkulator" in cmd:
            self.speak("Włączam kalkulator")
            subprocess.Popen(["calc.exe"])

        else:
            self.speak(f"Rozpoznano: {cmd}")