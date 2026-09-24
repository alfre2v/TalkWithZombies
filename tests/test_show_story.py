"""Tests for app/show/story.py — loading a story and rendering its cast sheet.

The two expected prompts are the system messages proven on the box on
2026-09-22 (zombie-radio: docs/experiments/2026-09-22-adr-0003-gate/
cast.py CAST_SHEET, and docs/experiments/2026-09-22-emotion-grammar-cost/
cast.py CAST_SHEET_TAUGHT), byte for byte.
"""

from pathlib import Path

import jinja2
import pytest

import app.config as app_config
from app.config import Persona, PersonasConfig, ShowConfig
from app.show.grammar import MOODS
from app.show.story import StoryError, load_story, render_cast_sheet

SHIPPED = Path(__file__).resolve().parent.parent / "stories"
CAST = ["Daniel", "Moira", "Ralph", "Samantha"]

_WORLD_AND_CAST = (
    "/no_think\n"
    "You write a live radio play. Four scientists are trapped in a besieged research lab during a zombie outbreak, speaking over the lab's shortwave radio.\n"
    "\n"
    "The cast:\n"
    "- Daniel: Dr. Daniel Hayworth, systems engineer. Dry British understatement; competent, tired, quietly heroic.\n"
    "- Moira: Dr. Moira Byrne, microbiologist. Irish lilt in her phrasing; grimly fascinated by the science of the outbreak, sometimes forgetting to be afraid.\n"
    "- Ralph: Dr. Ralph Okafor, security officer. Deep, deliberate, a little paranoid; counts things (doors, cans, shamblers) because counting keeps him calm.\n"
    "- Samantha: Dr. Samantha Reyes, communications lead running the broadcast. Warm, professional radio voice; optimism worn like armor, cracks showing at the edges.\n"
    "\n"
)
RUN_1_PROMPT = _WORLD_AND_CAST + (
    "Format: write the next lines of the script, one line per transmission, as `Name: spoken words`. "
    'Each transmission is one or two short spoken sentences ending with "Over." No narration, no markdown, no stage directions.'
)
RUN_2_PROMPT = _WORLD_AND_CAST + (
    "Format: write the next lines of the script, one line per transmission, as `Name (emotion): spoken words`. "
    "The emotion in parentheses is the one the listener should hear in the speaker's voice, exactly one of: "
    "calm, happy, sad, afraid, terrified, doubtful, angry, urgent, exhausted. "
    'Each transmission is one or two short spoken sentences ending with "Over." No narration, no markdown, and nothing else in parentheses.'
)


@pytest.fixture
def voices(monkeypatch):
    """Personas with a reference voice for the given names (all four by default)."""
    def _set(names=CAST):
        personas = [Persona(name=n, system_prompt="-", reference_audio=f"{n}/ref.wav") for n in names]
        monkeypatch.setattr(app_config, "_personas_cache", PersonasConfig(personas=personas))
    _set()
    return _set


def _write_story(root, *, front="title: T\ncast: [Daniel, Moira]\noperator: Moira\n",
                 body="{{ model_prefix }}\nWorld.\n\n{{ format_rules }}\n\n{{ episode }}\n",
                 events="events:\n  - Something happens.\n", tones=None, name="s"):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "cast_sheet.md").write_text(f"---\n{front}---\n{body}" if front is not None else body)
    if events is not None:
        (folder / "events.yaml").write_text(events)
    if tones is not None:
        (folder / "tones.yaml").write_text(tones)
    return root


class TestShippedStory:
    def test_loads(self, voices):
        story = load_story("lab-outbreak", SHIPPED)

        assert story.title == "The Lab at the End of the Frequency"
        assert story.cast == tuple(CAST)
        assert story.operator == "Samantha"
        assert len(story.events) == 10
        assert story.events[2] == "Something is scratching at the loading dock door, slow and rhythmic."
        assert len(story.tones) == 65
        assert "brittle" in story.tones
        assert not set(story.tones) & set(MOODS)

    def test_moods_off_renders_the_run_1_prompt(self, voices):
        story = load_story("lab-outbreak", SHIPPED)
        assert render_cast_sheet(story, ShowConfig(emotion_tags=False)) == RUN_1_PROMPT

    def test_moods_on_renders_the_run_2_prompt(self, voices):
        story = load_story("lab-outbreak", SHIPPED)
        assert render_cast_sheet(story, ShowConfig(emotion_tags=True)) == RUN_2_PROMPT

    def test_the_switch_changes_only_the_format_paragraph(self, voices):
        story = load_story("lab-outbreak", SHIPPED)
        off = render_cast_sheet(story, ShowConfig(emotion_tags=False)).split("\n\n")
        on = render_cast_sheet(story, ShowConfig(emotion_tags=True)).split("\n\n")

        assert off[:-1] == on[:-1]
        assert off[-1] != on[-1]

    def test_episode_text_is_appended(self, voices):
        story = load_story("lab-outbreak", SHIPPED)
        rendered = render_cast_sheet(story, ShowConfig(), episode="Previously: the first night.")

        assert rendered.endswith("nothing else in parentheses.\n\nPreviously: the first night.")

    def test_empty_model_prefix_leaves_no_blank_first_line(self, voices):
        story = load_story("lab-outbreak", SHIPPED)
        assert render_cast_sheet(story, ShowConfig(model_prefix="")).startswith("You write a live radio play.")


class TestStoryErrors:
    def test_misspelled_placeholder_fails_loudly(self, voices, tmp_path):
        root = _write_story(tmp_path, body="{{ model_prefx }}\nWorld.\n")
        story = load_story("s", root)
        with pytest.raises(jinja2.UndefinedError):
            render_cast_sheet(story, ShowConfig())

    def test_cast_name_without_a_voice_fails_and_names_it(self, voices, tmp_path):
        voices(["Daniel"])
        with pytest.raises(StoryError, match="Moira"):
            load_story("s", _write_story(tmp_path))

    def test_operator_outside_the_cast_fails(self, voices, tmp_path):
        root = _write_story(tmp_path, front="title: T\ncast: [Daniel, Moira]\noperator: Ralph\n")
        with pytest.raises(StoryError, match="operator"):
            load_story("s", root)

    def test_duplicate_cast_name_fails(self, voices, tmp_path):
        root = _write_story(tmp_path, front="title: T\ncast: [Daniel, Daniel]\noperator: Daniel\n")
        with pytest.raises(StoryError, match="repeats"):
            load_story("s", root)

    def test_malformed_front_matter_fails(self, voices, tmp_path):
        root = _write_story(tmp_path, front=None, body="---\ntitle: T\ncast: [Daniel]\nWorld.\n")
        with pytest.raises(StoryError, match="title"):
            load_story("s", root)

    @pytest.mark.parametrize("events", [None, "events: []\n", "other: [x]\n", "events:\n  - ''\n"])
    def test_missing_or_empty_events_fail(self, voices, tmp_path, events):
        with pytest.raises(StoryError, match="events"):
            load_story("s", _write_story(tmp_path, events=events))

    @pytest.mark.parametrize("tones", ["tones: brittle\n", "other: [x]\n", "tones:\n  - ''\n"])
    def test_malformed_tones_fail(self, voices, tmp_path, tones):
        with pytest.raises(StoryError, match="tones"):
            load_story("s", _write_story(tmp_path, tones=tones))

    def test_unknown_story_fails(self, voices, tmp_path):
        with pytest.raises(StoryError, match="not found"):
            load_story("nope", tmp_path)

    @pytest.mark.parametrize("tones, expected", [(None, ()), ("tones: []\n", ()),
                                                 ("tones:\n  - brittle\n  - ' woeful '\n", ("brittle", "woeful"))])
    def test_tones_are_optional(self, voices, tmp_path, tones, expected):
        assert load_story("s", _write_story(tmp_path, tones=tones)).tones == expected

    def test_default_root_is_the_project_stories_folder(self, voices, tmp_path):
        _write_story(tmp_path / "stories")
        assert load_story("s").title == "T"
