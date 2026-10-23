from unittest.mock import MagicMock, patch

import pytest

from core import voice_assistant as voice


@pytest.fixture
def assistant():
    with patch.object(voice.sr, "Recognizer"), patch.object(voice.sr, "Microphone"):
        assistant = voice.PolishVoiceAssistant()
        assistant.speak = MagicMock()
        yield assistant


def test_polish_recognition_and_dispatch(assistant):
    assistant.recognizer.recognize_google.return_value = "  YOUTUBE  "
    with patch.object(voice.webbrowser, "open") as browser:
        assistant.listen_and_execute()
    browser.assert_called_once_with("https://youtube.com")
    assert assistant.recognizer.recognize_google.call_args.kwargs == {"language": "pl-PL"}
    assert assistant.recognizer.listen.call_args.kwargs == {"timeout": 5, "phrase_time_limit": 5}
    voice.sr.Microphone.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("error", [voice.sr.WaitTimeoutError, voice.sr.UnknownValueError, OSError])
def test_microphone_errors_are_handled(assistant, error):
    assistant.recognizer.listen.side_effect = error()
    assistant.listen_and_execute()
    assert assistant.speak.call_count == 2
    assistant.recognizer.recognize_google.assert_not_called()


def test_speech_engine_failure_is_handled():
    assistant = voice.PolishVoiceAssistant()
    with patch.object(assistant, "_get_engine", side_effect=RuntimeError("no audio")):
        assistant.speak("test")
