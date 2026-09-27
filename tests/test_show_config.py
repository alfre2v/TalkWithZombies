"""Tests for the show engine's settings (ShowConfig in app/config.py)."""

import pytest
import yaml
from pydantic import ValidationError

import app.config as app_config
from app.config import AppSettings, ShowConfig


def _write_settings(tmp_path, raw):
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(raw))
    return path


class TestShowConfig:
    def test_defaults_when_section_absent(self, tmp_path):
        show = app_config.load_settings(_write_settings(tmp_path, {"llm": {"model": "m"}})).show

        assert show == ShowConfig()
        assert show.story == "lab-outbreak"
        assert show.episode is None
        assert show.model_prefix == "/no_think"
        assert show.max_tokens == 512
        assert show.context_budget == 14000
        assert show.seed is None
        assert show.emotion_tags is True
        assert show.debug is False
        assert (show.event_every, show.event_jitter, show.tone_hold, show.tone_jitter) == (2, 1, 3, 1)
        assert show.event_report is True
        assert (show.interaction_min_s, show.interaction_max_s) == (60.0, 180.0)
        assert (show.listen_window_s, show.press_cap_s) == (10.0, 30.0)
        assert (show.no_speech_max, show.logprob_min) == (0.6, -1.0)
        assert show.stt_language == "en"
        assert (show.free_lines, show.free_line_weights) == ([1, 2, 3, 4], [1.0, 3.0, 3.0, 1.0])
        assert (show.overtone_hold, show.overtone_jitter) == (4, 1)
        assert (show.contact_exchanges, show.contact_jitter) == (3, 1)
        assert (show.contact_min_lines, show.contact_max_lines) == (2, 3)
        assert (show.silences_to_switch_off, show.beat_max_lines, show.breakdown_lines) == (2, 2, 3)
        assert (show.orientation_every, show.orientation_jitter) == (20, 5)
        assert (show.recollection_every, show.recollection_jitter) == (15, 5)
        assert show.restatement_contacts == 5

    def test_the_contact_and_pacing_settings_read_from_yaml(self, tmp_path):
        raw = {"show": {
            "free_lines": [2, 3], "free_line_weights": [1, 1], "overtone_hold": 6, "overtone_jitter": 0,
            "contact_exchanges": 4, "contact_jitter": 0, "contact_min_lines": 3, "contact_max_lines": 3,
            "silences_to_switch_off": 1, "beat_max_lines": 1, "breakdown_lines": 2, "orientation_every": 0,
            "orientation_jitter": 0,
            "recollection_every": 10, "recollection_jitter": 2, "restatement_contacts": 2,
        }}
        show = app_config.load_settings(_write_settings(tmp_path, raw)).show

        assert (show.free_lines, show.free_line_weights) == ([2, 3], [1.0, 1.0])
        assert (show.overtone_hold, show.overtone_jitter) == (6, 0)
        assert (show.contact_exchanges, show.contact_jitter, show.contact_min_lines, show.contact_max_lines) == (
            4, 0, 3, 3)
        assert (show.silences_to_switch_off, show.beat_max_lines, show.breakdown_lines) == (1, 1, 2)
        assert (show.orientation_every, show.recollection_every, show.recollection_jitter) == (0, 10, 2)
        assert show.restatement_contacts == 2

    def test_values_read_from_yaml(self, tmp_path):
        raw = {"show": {
            "story": "another-story", "episode": "01-supplies", "max_tokens": 400,
            "context_budget": 3000, "seed": 7, "emotion_tags": False, "debug": True,
            "interaction_min_s": 5, "interaction_max_s": 9, "stt_language": "es",
            "event_every": 0, "event_jitter": 0, "tone_hold": 5, "tone_jitter": 2, "event_report": False,
        }}
        show = app_config.load_settings(_write_settings(tmp_path, raw)).show

        assert (show.event_every, show.event_jitter, show.tone_hold, show.tone_jitter) == (0, 0, 5, 2)
        assert show.event_report is False
        assert (show.story, show.episode) == ("another-story", "01-supplies")
        assert (show.max_tokens, show.context_budget, show.seed) == (400, 3000, 7)
        assert show.emotion_tags is False
        assert show.debug is True
        assert (show.interaction_min_s, show.interaction_max_s) == (5.0, 9.0)
        assert show.stt_language == "es"

    def test_interaction_min_above_max_rejected(self):
        with pytest.raises(ValidationError):
            ShowConfig(interaction_min_s=200, interaction_max_s=100)

    def test_contact_min_lines_above_max_rejected(self):
        with pytest.raises(ValidationError, match="contact_min_lines"):
            ShowConfig(contact_min_lines=4, contact_max_lines=3)

    @pytest.mark.parametrize("lines, weights", [
        ([], []), ([1, 2], [1]), ([2, 2], [1, 1]), ([0, 1], [1, 1]), ([1, 2], [1, -1]), ([1, 2], [0, 0]),
    ])
    def test_unsound_free_line_budgets_rejected(self, lines, weights):
        with pytest.raises(ValidationError, match="free_lines"):
            ShowConfig(free_lines=lines, free_line_weights=weights)

    @pytest.mark.parametrize("field,value", [
        ("story", ""),
        ("max_tokens", 0),
        ("context_budget", 10),
        ("seed", -1),
        ("listen_window_s", 0),
        ("press_cap_s", 0),
        ("no_speech_max", 1.5),
        ("event_every", -1),
        ("event_jitter", -1),
        ("tone_hold", -1),
        ("tone_jitter", -1),
        ("overtone_hold", 0),
        ("overtone_jitter", -1),
        ("contact_exchanges", 0),
        ("contact_jitter", -1),
        ("contact_min_lines", 0),
        ("silences_to_switch_off", 0),
        ("beat_max_lines", 0),
        ("breakdown_lines", 0),
        ("orientation_every", -1),
        ("recollection_every", -1),
        ("restatement_contacts", 0),
    ])
    def test_out_of_bounds_rejected(self, field, value):
        with pytest.raises(ValidationError):
            ShowConfig(**{field: value})

    def test_save_then_load_keeps_the_show_section(self, tmp_path):
        path = tmp_path / "settings.yaml"
        settings = AppSettings(show=ShowConfig(story="another-story", seed=11, debug=True))

        app_config.save_settings(settings, path)

        assert app_config.load_settings(path).show == settings.show
