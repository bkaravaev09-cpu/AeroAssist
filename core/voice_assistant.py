import subprocess
import webbrowser

import pyttsx3
import speech_recognition as sr


class PolishVoiceAssistant:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.recognizer.energy_threshold = 300
        self.recognizer.dynamic_energy_threshold = True
        self._keyboard_callback = None  # Set by main.py for GUI integration

    def set_keyboard_callback(self, callback):
        """Allow main.py to wire keyboard actions from the voice thread."""
        self._keyboard_callback = callback

    def _run_keyboard_action(self, action, *args):
        """Invoke the keyboard callback safely from the voice thread."""
        if self._keyboard_callback is None:
            print(f"[Keyboard] No callback set, skipping action: {action}")
            return
        try:
            self._keyboard_callback(action, *args)
        except Exception as e:
            print(f"[Keyboard] Callback error: {e}")

    def _get_engine(self):
        engine = pyttsx3.init()
        voices = engine.getProperty("voices")
        for voice in voices:
            if (
                "polish" in voice.name.lower()
                or "pl" in voice.id.lower()
                or "paulina" in voice.name.lower()
            ):
                engine.setProperty("voice", voice.id)
                break
        engine.setProperty("rate", 155)
        return engine

    def speak(self, text):
        try:
            print(f"[Assistant]: {text}")
            engine = self._get_engine()
            engine.say(text)
            engine.runAndWait()
            del engine
        except Exception as e:
            print(f"[TTS Error]: {e}")

    def listen_and_execute(self):
        """Start voice command loop (called by main.py assistant thread)."""
        self.speak("Słucham polecenia")

        try:
            with sr.Microphone() as source:
                print("[Microphone]: Adjusting for ambient noise...")
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                print("[Microphone]: Listening...")
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)

                print("[Recognition]: Processing speech...")
                command = self.recognizer.recognize_google(audio, language="pl-PL").lower().strip()
                print(f"[Recognized]: '{command}'")
                self._dispatch(command)
        except sr.WaitTimeoutError:
            print("[Microphone]: Timeout waiting for phrase")
            self.speak("Koniec czasu oczekiwania")
        except sr.UnknownValueError:
            print("[Recognition]: Could not understand audio")
            self.speak("Nie zrozumiałam polecenia")
        except Exception as e:
            print(f"[Microphone Error]: {e}")
            self.speak("Problem z mikrofonem")

    def _dispatch(self, cmd):
        # 1. Web search
        if "szukaj" in cmd or "znajdź" in cmd:
            query = (
                cmd.replace("szukaj w google", "")
                .replace("szukaj", "")
                .replace("znajdź", "")
                .strip()
            )
            self.speak(f"Szukam w Google: {query}")
            webbrowser.open(f"https://www.google.com/search?q={query}")

        # 2. YouTube / browser
        elif "youtube" in cmd or "jutub" in cmd:
            self.speak("Otwieram YouTube")
            webbrowser.open("https://youtube.com")

        elif "przeglądarka" in cmd or "internet" in cmd:
            self.speak("Uruchamiam przeglądarkę")
            webbrowser.open("https://google.pl")

        # 3. On-screen keyboard (GUI bridge)
        elif (
            "zamknij klawiaturę" in cmd
            or "schowaj klawiaturę" in cmd
            or "wyłącz klawiaturę" in cmd
        ):
            self.speak("Zamykam klawiaturę")
            self._run_keyboard_action("close")

        elif "otwórz klawiaturę" in cmd or "uruchom klawiaturę" in cmd or "klawiatura" in cmd:
            self.speak("Uruchamiam klawiaturę ekranową")
            self._run_keyboard_action("toggle")

        elif "zmień język" in cmd or "zmień język klawiatury" in cmd or "language" in cmd:
            self.speak("Zmieniam język klawiatury")
            self._run_keyboard_action("language")

        # 4. Window switching / desktop
        elif "przełącz" in cmd or "zmień okno" in cmd or "następne" in cmd:
            self.speak("Przełączam okno")
            import pyautogui

            pyautogui.hotkey("alt", "tab")

        elif "pulpit" in cmd or "zminimalizuj" in cmd:
            self.speak("Pokazuję pulpit")
            import pyautogui

            pyautogui.hotkey("win", "d")

        # 5. Apps
        elif "notatnik" in cmd:
            self.speak("Otwieram notatnik")
            subprocess.Popen(["notepad.exe"])

        elif "kalkulator" in cmd:
            self.speak("Włączam kalkulator")
            subprocess.Popen(["calc.exe"])

        else:
            self.speak(f"Rozpoznano: {cmd}")