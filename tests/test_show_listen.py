"""Tests for app/show/listen.py — the transcript filter: words or silence."""

import pytest

from app.config import ShowConfig
from app.show.listen import usable

SHOW = ShowConfig()


class TestUsable:
    def test_clear_words_count(self):
        assert usable("  Moira, is it airborne? ", 0.05, -0.3, SHOW) == ("Moira, is it airborne?", None)

    @pytest.mark.parametrize("text", ["", "   ", "a", "...", " ?! "])
    def test_empty_or_one_character_is_silence(self, text):
        assert usable(text, None, None, SHOW) == (None, "nothing heard")

    def test_whisper_doubting_there_was_speech_is_silence(self):
        assert usable("Hello there.", 0.83, -0.2, SHOW) == (None, "no speech (no_speech_prob 0.83 > 0.6)")

    def test_whisper_doubting_its_reading_is_silence(self):
        assert usable("Hello there.", 0.1, -1.4, SHOW) == (None, "an unsure reading (avg_logprob -1.40 < -1.0)")

    @pytest.mark.parametrize("text", ["Thank you.", "THANK YOU!", "Thanks for watching!",
                                      "Subtitles by the Amara.org community", "you",
                                      "No response received from STT server"])
    def test_known_whisper_noise_and_the_upstream_placeholder_are_silence(self, text):
        assert usable(text, 0.1, -0.2, SHOW) == (None, "a known Whisper hallucination")

    def test_a_sentence_that_only_contains_thank_you_counts(self):
        assert usable("Thank you, Samantha, we hear you.", 0.1, -0.3, SHOW) == (
            "Thank you, Samantha, we hear you.", None)

    def test_missing_numbers_skip_their_checks(self):
        assert usable("Hello there.", None, None, SHOW) == ("Hello there.", None)

    def test_the_thresholds_are_the_settings_and_the_limits_themselves_pass(self):
        assert usable("Hello there.", 0.83, -1.4, ShowConfig(no_speech_max=0.9, logprob_min=-2.0)) == (
            "Hello there.", None)
        assert usable("Hello there.", 0.6, -1.0, SHOW) == ("Hello there.", None)
