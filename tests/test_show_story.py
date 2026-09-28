"""Tests for app/show/story.py — loading a story and rendering its cast sheet.

The two expected prompts are the system messages proven on the box on
2026-09-22 (zombie-radio: docs/experiments/2026-09-22-adr-0003-gate/
cast.py CAST_SHEET, and docs/experiments/2026-09-22-emotion-grammar-cost/
cast.py CAST_SHEET_TAUGHT), byte for byte — plus, since step 3.4c
(2026-09-26), the premise sentence about the failing receiver and, with
moods on, the story's fourteen moods in the order of its overtones; and,
since the prompt sweep (2026-09-28), the premise sentences about the
listener who answers and what the scientists tell the listeners.
"""

from pathlib import Path

import jinja2
import pytest

import app.config as app_config
from app.config import Persona, PersonasConfig, ShowConfig
from app.show.grammar import MOODS
from app.show.story import Story, StoryError, all_moods, load_story, render_cast_sheet

SHIPPED = Path(__file__).resolve().parent.parent / "stories"
CAST = ["Daniel", "Moira", "Ralph", "Samantha"]

_WORLD_AND_CAST = (
    "/no_think\n"
    "You write a live radio play. Four scientists are trapped in a besieged research lab during a zombie outbreak, speaking over the lab's shortwave radio. "
    "The radio's receiver keeps failing: while it is down they can only transmit, and when they get it working they "
    "call out for anyone listening to answer. A listener who answers is heard as a voice on the frequency, and the "
    "cast talk to them directly. The scientists try to explain to the listener over the radio the strange events "
    "that led to the lab's accident that produced the zombie infestation, hoping that someone can find a cure for "
    "the virus, they also ask the listeners for help (supplies, food, medicine, ammo) to try to resist the zombie "
    "attack waves.\n"
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
    "happy, hopeful, excited, relieved, calm, doubtful, urgent, curious, determined, sad, afraid, terrified, angry, "
    "exhausted. "
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


FRONT = "title: T\ncast: [Daniel, Moira]\noperator: Moira\norientation: What newcomers are told.\n"
DIRECTIONS = "directions:\n  repair: On again.\n  breakdown: Dead again.\n  switch-off: Off, by choice.\n"
KINDS = ("kinds:\n  orientation: [level]\n  repair: [up]\n  exchange: [up, level]\n  re-call: [level]\n"
         "  breakdown: [level, down]\n  switch-off: [level, down]\n")
WEIGHTS = "weights: {up: 1, level: 2, down: 3}\n"
OVERTONES = ("overtones:\n"
             "  up:\n    moods: [happy]\n    tones:\n      Warm: [bright]\n"
             "  level:\n    moods: [calm]\n"
             "  down:\n    moods: [sad, afraid]\n    tones:\n      Dark: [grim, eerie]\n") + KINDS + WEIGHTS
EVENTS = "events:\n  down:\n    Dark:\n      - Something happens.\n"
AGENDA = "agenda:\n  - Who are you?\n  - Where are you?\n"
BEATS = ("repair:\n  after-breakdown:\n    - [Fixed!, Answer us.]\n  after-switch-off:\n    - [Back on!, Answer us.]\n"
         "breakdown:\n  - It's dead.\nswitch-off:\n  nobody-answered:\n    - Nobody. Off.\n  voice-lost:\n"
         "    - Lost you. Off.\n")


def _write_story(root, *, front=FRONT + DIRECTIONS,
                 body="{{ model_prefix }}\nWorld.\n\n{{ format_rules }}\n\n{{ episode }}\n",
                 overtones=OVERTONES, events=EVENTS, agenda=AGENDA, beats=None, name="s"):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "cast_sheet.md").write_text(f"---\n{front}---\n{body}" if front is not None else body)
    for file, text in (("overtones.yaml", overtones), ("events.yaml", events), ("agenda.yaml", agenda),
                       ("beats.yaml", beats)):
        if text is not None:
            (folder / file).write_text(text)
    return root


class TestShippedStory:
    def test_loads(self, voices):
        story = load_story("lab-outbreak", SHIPPED)

        assert story.title == "The Lab at the End of the Frequency"
        assert story.cast == tuple(CAST)
        assert story.operator == "Samantha"
        assert [o.name for o in story.overtones] == ["positive", "neutral", "negative"]
        moods = [m for o in story.overtones for m in o.moods]
        assert len(moods) == 14 and set(MOODS) <= set(moods)
        assert story.kinds["exchange"] == ("positive", "neutral")
        assert story.weights == {"positive": 1, "neutral": 2, "negative": 3}
        assert len(story.tones) == 496
        assert "brittle" in story.tones
        assert not set(story.tones) & set(moods)
        assert len({theme for o in story.overtones for theme in o.tones}) == 24
        assert len(story.events) == 289
        assert {o: sum(map(len, themes.values())) for o, themes in story.event_pools.items()} == {
            "positive": 29, "neutral": 94, "negative": 166}
        assert ("Something is scratching at the loading dock door, slow and rhythmic."
                in story.event_pools["negative"]["The ADR-0003 gate's ten (2026-09-22)"])
        assert story.agenda[0].startswith("Find out who the voice is.")
        assert "receiver is dead" in story.orientation
        assert set(story.directions) == {"repair", "breakdown", "switch-off"}
        beats = story.beats
        assert [len(beats.repair_after_breakdown), len(beats.repair_after_switch_off), len(beats.breakdown),
                len(beats.switch_off_nobody_answered), len(beats.switch_off_voice_lost)] == [4, 4, 4, 4, 4]
        assert all(len(pair) == 2 for pair in beats.repair_after_breakdown + beats.repair_after_switch_off)

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

    @pytest.mark.parametrize("events", [None, "events: []\n", "other: [x]\n", "events:\n  - Flat list.\n",
                                        "events:\n  sideways:\n    Odd:\n      - Something.\n",
                                        "events:\n  down:\n    Dark:\n      - ''\n",
                                        "events:\n  up:\n    A: [Same.]\n  down:\n    B: [Same.]\n"])
    def test_missing_malformed_or_repeated_events_fail(self, voices, tmp_path, events):
        with pytest.raises(StoryError, match="events"):
            load_story("s", _write_story(tmp_path, events=events))

    def test_an_overtone_may_have_no_events(self, voices, tmp_path):
        story = load_story("s", _write_story(tmp_path))
        assert set(story.event_pools) == {"down"}

    @pytest.mark.parametrize("overtones, match", [
        (None, "not found"),
        ("overtones: []\n" + KINDS + WEIGHTS, "overtones"),
        (OVERTONES.replace("moods: [calm]", "moods: [(calm)]"), "moods"),
        (OVERTONES.replace("moods: [calm]", "moods: [happy]"), "two overtones"),
        (OVERTONES.replace("[grim, eerie]", "[grim, calm]"), "both a mood and a tone word"),
        (OVERTONES.replace("[grim, eerie]", "[grim, bright]"), "repeats"),
        (OVERTONES.replace("  re-call: [level]\n", ""), "kinds"),
        (OVERTONES.replace("repair: [up]", "repair: [sideways]"), "repair"),
        (OVERTONES.replace("breakdown: [level, down]", "breakdown: [up, down]"), "neighbors"),
        (OVERTONES.replace(WEIGHTS, "weights: {up: 1, level: 2}\n"), "weights"),
        (OVERTONES.replace(WEIGHTS, "weights: {up: 0, level: 0, down: 0}\n"), "weights"),
    ])
    def test_malformed_overtones_fail(self, voices, tmp_path, overtones, match):
        with pytest.raises(StoryError, match=match):
            load_story("s", _write_story(tmp_path, overtones=overtones))

    def test_beats_are_optional_and_read_when_present(self, voices, tmp_path):
        assert load_story("s", _write_story(tmp_path / "a")).beats is None
        beats = load_story("s", _write_story(tmp_path / "b", beats=BEATS)).beats
        assert beats.repair_after_breakdown == (("Fixed!", "Answer us."),)
        assert (beats.breakdown, beats.switch_off_voice_lost) == (("It's dead.",), ("Lost you. Off.",))

    @pytest.mark.parametrize("beats, match", [
        (BEATS.replace("repair:", "repairs:"), "'repair', a mapping"),
        (BEATS.replace("[Fixed!, Answer us.]", "[Fixed!, Answer us., Again.]"), "pairs"),
        (BEATS.replace("  - It's dead.\n", "  []\n"), "'breakdown'"),
        (BEATS.replace("  voice-lost:\n    - Lost you. Off.\n", ""), "voice-lost"),
    ])
    def test_malformed_beats_fail(self, voices, tmp_path, beats, match):
        with pytest.raises(StoryError, match=match):
            load_story("s", _write_story(tmp_path, beats=beats))

    @pytest.mark.parametrize("agenda", [None, "agenda: []\n", "agenda:\n  - Only one.\n",
                                        "agenda:\n  - Twice.\n  - Twice.\n"])
    def test_missing_or_short_agenda_fails(self, voices, tmp_path, agenda):
        with pytest.raises(StoryError, match="agenda"):
            load_story("s", _write_story(tmp_path, agenda=agenda))

    @pytest.mark.parametrize("front, match", [
        (FRONT.replace("orientation: What newcomers are told.\n", "") + DIRECTIONS, "orientation"),
        (FRONT, "directions"),
        (FRONT + DIRECTIONS.replace("  switch-off: Off, by choice.\n", ""), "directions"),
    ])
    def test_missing_orientation_or_directions_fail(self, voices, tmp_path, front, match):
        with pytest.raises(StoryError, match=match):
            load_story("s", _write_story(tmp_path, front=front))

    def test_all_moods_in_the_overtones_order_or_the_engines_nine(self, voices, tmp_path):
        story = load_story("s", _write_story(tmp_path))
        assert all_moods(story) == ["happy", "calm", "sad", "afraid"]
        bare = Story(name="b", title="T", cast=("Daniel",), operator="Daniel", template="", events=("E.",))
        assert all_moods(bare) == list(MOODS)

    def test_the_palette_is_read_in_order(self, voices, tmp_path):
        story = load_story("s", _write_story(tmp_path))
        assert [(o.name, o.moods) for o in story.overtones] == [("up", ("happy",)), ("level", ("calm",)),
                                                                ("down", ("sad", "afraid"))]
        assert story.overtones[2].tones == {"Dark": ("grim", "eerie")}
        assert story.tones == ("bright", "grim", "eerie")
        assert story.kinds["breakdown"] == ("level", "down")
        assert story.directions["switch-off"] == "Off, by choice."

    def test_unknown_story_fails(self, voices, tmp_path):
        with pytest.raises(StoryError, match="not found"):
            load_story("nope", tmp_path)

    def test_default_root_is_the_project_stories_folder(self, voices, tmp_path):
        _write_story(tmp_path / "stories")
        assert load_story("s").title == "T"
