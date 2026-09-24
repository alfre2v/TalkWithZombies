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
        assert (show.interaction_min_s, show.interaction_max_s) == (60.0, 180.0)
        assert (show.listen_window_s, show.press_cap_s) == (10.0, 30.0)
        assert (show.no_speech_max, show.logprob_min) == (0.6, -1.0)
        assert show.stt_language == "en"

    def test_values_read_from_yaml(self, tmp_path):
        raw = {"show": {
            "story": "another-story", "episode": "01-supplies", "max_tokens": 400,
            "context_budget": 3000, "seed": 7, "emotion_tags": False, "debug": True,
            "interaction_min_s": 5, "interaction_max_s": 9, "stt_language": "es",
        }}
        show = app_config.load_settings(_write_settings(tmp_path, raw)).show

        assert (show.story, show.episode) == ("another-story", "01-supplies")
        assert (show.max_tokens, show.context_budget, show.seed) == (400, 3000, 7)
        assert show.emotion_tags is False
        assert show.debug is True
        assert (show.interaction_min_s, show.interaction_max_s) == (5.0, 9.0)
        assert show.stt_language == "es"

    def test_interaction_min_above_max_rejected(self):
        with pytest.raises(ValidationError):
            ShowConfig(interaction_min_s=200, interaction_max_s=100)

    @pytest.mark.parametrize("field,value", [
        ("story", ""),
        ("max_tokens", 0),
        ("context_budget", 10),
        ("seed", -1),
        ("listen_window_s", 0),
        ("press_cap_s", 0),
        ("no_speech_max", 1.5),
    ])
    def test_out_of_bounds_rejected(self, field, value):
        with pytest.raises(ValidationError):
            ShowConfig(**{field: value})

    def test_save_then_load_keeps_the_show_section(self, tmp_path):
        path = tmp_path / "settings.yaml"
        settings = AppSettings(show=ShowConfig(story="another-story", seed=11, debug=True))

        app_config.save_settings(settings, path)

        assert app_config.load_settings(path).show == settings.show
