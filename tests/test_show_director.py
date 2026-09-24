"""Tests for app/show/director.py — director v1."""

import itertools
from collections import Counter

import pytest

from app.config import ShowConfig
from app.show.director import instruction_for, names_in, plan_round
from app.show.script import Line, Round, Run
from app.show.story import Story

CAST = ("Daniel", "Moira", "Ralph", "Samantha")
TONES = ("brittle", "macabre", "woeful")
STORY = Story(name="lab", title="T", cast=CAST, operator="Samantha", template="",
              events=("First event.", "Second event.", "Third event."), tones=TONES)
SHOW = ShowConfig(interaction_min_s=60, interaction_max_s=180)
NUMBERS = {2: "two", 3: "three", 4: "four"}


def _run(seed=42, moods=True):
    return Run(run_id="r", started="s", story="lab", cast=list(CAST), moods=moods, seed=seed, systems={"": "S"})


def _record(run, plan, played_s=0.0, lines=None):
    """Record a planned round; by default the allowed speakers take the budget's lines in turn."""
    if lines is None:
        lines = [(plan.speakers[i % len(plan.speakers)], "Line. Over.") for i in range(plan.max_lines)]
    run.rounds.append(Round(n=len(run.rounds) + 1, kind=plan.kind, played_s=played_s,
                            instruction=plan.instruction, listener=plan.listener, speakers=list(plan.speakers),
                            max_lines=plan.max_lines, event=plan.event, tone=plan.tone,
                            lines=[Line(speaker=s, raw=f"{s} (calm): {t}", spoken=t) for s, t in lines]))


def _play(run, rounds, step=0.0, heard=(None,), story=STORY):
    """Plan and record rounds, `step` seconds of audio each; after an invitation the listener
    says the next item of `heard` (None: silence). Returns the plans."""
    replies = itertools.cycle(heard)
    plans = []
    for i in range(rounds):
        after_invitation = bool(run.rounds) and run.rounds[-1].kind == "invitation"
        plan = plan_round(run, story, SHOW, played_s=step * i, transcript=next(replies) if after_invitation else None)
        _record(run, plan, step * i)
        plans.append(plan)
    return plans


def _says_what_the_grammar_enforces(plan):
    grammar = plan.grammar.splitlines()
    assert grammar[0] == f"root    ::= line{{1,{plan.max_lines}}}"
    assert grammar[2] == "speaker ::= " + " | ".join(f'"{name}"' for name in plan.speakers)
    count = "the next line" if plan.max_lines == 1 else f"the next {NUMBERS[plan.max_lines]} lines"
    assert count in plan.instruction
    if plan.speakers != CAST:
        assert all(name in plan.instruction for name in plan.speakers)


class TestEveryKind:
    def test_words_and_grammar_state_the_same_constraints(self):
        plans = _play(_run(), 120, step=20, heard=(None, "Moira, is it airborne?", "Anyone out there?"))

        assert {plan.kind for plan in plans} == {"free", "invitation", "answer", "static"}
        for plan in plans:
            _says_what_the_grammar_enforces(plan)

    def test_same_seed_replays_the_same_plans(self):
        heard = (None, "Ralph?")
        assert _play(_run(seed=7), 40, step=20, heard=heard) == _play(_run(seed=7), 40, step=20, heard=heard)
        assert _play(_run(seed=7), 40, step=20, heard=heard) != _play(_run(seed=8), 40, step=20, heard=heard)

    def test_moods_off(self):
        for plan in _play(_run(moods=False), 40, step=20, heard=(None, "Hello?")):
            assert "emotion" not in plan.instruction
            assert "emotion ::=" not in plan.grammar


class TestFree:
    def test_speakers_and_budget_stay_in_bounds(self):
        for plan in _play(_run(), 200):
            assert plan.kind == "free"
            assert 2 <= len(plan.speakers) <= 3
            assert list(plan.speakers) == [name for name in CAST if name in plan.speakers]
            assert 1 <= plan.max_lines <= 4

    def test_the_budget_is_weighted_to_two_and_three(self):
        budgets = Counter(plan.max_lines for seed in range(20) for plan in _play(_run(seed), 20))

        assert set(budgets) == {1, 2, 3, 4}
        assert budgets[2] + budgets[3] > 2 * (budgets[1] + budgets[4])

    def test_whoever_has_been_silent_longest_is_always_allowed(self):
        for seed in range(50):
            run = _run(seed)
            _record(run, plan_round(run, STORY, SHOW), lines=[("Daniel", "A."), ("Moira", "B.")])
            _record(run, plan_round(run, STORY, SHOW), lines=[("Samantha", "C."), ("Ralph", "D."), ("Moira", "E.")])
            assert "Daniel" in plan_round(run, STORY, SHOW).speakers

    def test_a_name_in_the_last_round_is_allowed(self):
        for seed in range(50):
            run = _run(seed)
            _record(run, plan_round(run, STORY, SHOW), lines=[("Daniel", "A."), ("Samantha", "B.")])
            _record(run, plan_round(run, STORY, SHOW), lines=[("Ralph", "C."), ("Moira", "Ralph, the doors? Over.")])
            assert {"Daniel", "Ralph"} <= set(plan_round(run, STORY, SHOW).speakers)

    def test_a_speaker_naming_themself_is_not_a_name_in_the_last_round(self):
        allowed = []
        for seed in range(50):
            run = _run(seed)
            _record(run, plan_round(run, STORY, SHOW), lines=[("Daniel", "A."), ("Moira", "B.")])
            _record(run, plan_round(run, STORY, SHOW), lines=[("Samantha", "C."), ("Ralph", "Ralph here. Over.")])
            allowed.append("Ralph" in plan_round(run, STORY, SHOW).speakers)
        assert not all(allowed)

    def test_a_name_in_the_listeners_words_is_allowed_next(self):
        for seed in range(50):
            run = _run(seed)
            _record(run, plan_round(run, STORY, SHOW), lines=[("Ralph", "A."), ("Daniel", "B.")])
            _record(run, plan_round(run, STORY, SHOW, played_s=180), played_s=180, lines=[("Samantha", "C.")])
            answer = plan_round(run, STORY, SHOW, played_s=185, transcript="Tell Ralph we are coming.")
            assert answer.speakers == ("Ralph",)
            _record(run, answer, 185, lines=[("Ralph", "We hear you. Over.")])
            assert {"Moira", "Ralph"} <= set(plan_round(run, STORY, SHOW, played_s=190).speakers)

    def test_events_on_odd_rounds_without_repeats_until_the_pool_is_used(self):
        plans = _play(_run(), 12)
        events = [plan.event for plan in plans]

        assert all(event is None for event in events[1::2])
        odd = events[0::2]
        assert sorted(odd[:3]) == sorted(STORY.events)
        assert sorted(odd[3:]) == sorted(STORY.events)
        assert all(plan.instruction.startswith(f"Offstage: {plan.event} ") for plan in plans[0::2])
        assert not any(plan.instruction.startswith("Offstage:") for plan in plans[1::2])

    def test_one_tone_word_per_round_from_the_story(self):
        for plan in _play(_run(), 30):
            assert plan.tone in TONES
            assert plan.instruction.endswith(f" Let the tone be: {plan.tone}.")

    def test_a_story_without_tone_words_gives_none(self):
        plain = Story(name="lab", title="T", cast=CAST, operator="Samantha", template="", events=STORY.events)
        for plan in _play(_run(), 40, step=20, story=plain):
            assert plan.tone is None
            assert "tone" not in plan.instruction


class TestCadence:
    @pytest.mark.parametrize("step", [20.0, 7.0])
    def test_never_before_the_minimum_always_by_the_maximum(self, step):
        firsts = set()
        for seed in range(100):
            run = _run(seed)
            _play(run, 80, step=step)
            marks = [0.0] + [r.played_s for r in run.rounds if r.kind == "invitation"]
            gaps = [later - earlier for earlier, later in zip(marks, marks[1:])]
            assert len(gaps) >= 2
            assert all(60 <= gap < 180 + step for gap in gaps)
            firsts.add(marks[1])
        assert len(firsts) > 3

    def test_the_invitation(self):
        plan = plan_round(_run(), STORY, SHOW, played_s=180)

        assert (plan.kind, plan.speakers, plan.max_lines) == ("invitation", ("Samantha",), 1)
        assert plan.instruction == (
            "Samantha turns to the microphone and asks anyone listening to answer: "
            f"the next line, with the emotion in its voice. Let the tone be: {plan.tone}.")


class TestListenerTurn:
    def _invited(self):
        run = _run()
        _record(run, plan_round(run, STORY, SHOW, played_s=180), played_s=180)
        assert run.rounds[-1].kind == "invitation"
        return run

    @pytest.mark.parametrize("transcript", [None, "", "   "])
    def test_a_silent_window_gives_the_static_round(self, transcript):
        plan = plan_round(self._invited(), STORY, SHOW, played_s=190, transcript=transcript)

        assert (plan.kind, plan.speakers, plan.max_lines, plan.listener) == ("static", ("Samantha",), 1, None)
        assert plan.instruction == (
            "Only static answers. Samantha speaks next: "
            f"the next line, with the emotion in its voice. Let the tone be: {plan.tone}.")

    def test_an_unaddressed_voice_lets_the_whole_cast_answer(self):
        plan = plan_round(self._invited(), STORY, SHOW, played_s=190, transcript="  I'm in Austin, the bridges are down. ")

        assert (plan.kind, plan.speakers, plan.max_lines) == ("answer", CAST, 1)
        assert plan.listener == "I'm in Austin, the bridges are down."
        assert (plan.tone, plan.event) == (None, None)
        assert plan.instruction == (
            'A voice on the frequency says: "I\'m in Austin, the bridges are down." '
            "The character the voice addressed answers; if it addressed no one, whoever fits best answers: "
            "the next line, with the emotion in its voice.")

    def test_an_exact_cast_name_narrows_the_answer(self):
        plan = plan_round(self._invited(), STORY, SHOW, played_s=190, transcript="Moira, is it airborne?")

        assert plan.speakers == ("Moira",)
        assert plan.instruction == (
            'A voice on the frequency says: "Moira, is it airborne?" '
            "Moira answers the voice: the next line, with the emotion in its voice.")

    def test_two_names_allow_both(self):
        plan = plan_round(self._invited(), STORY, SHOW, played_s=190, transcript="Ralph and Moira, where are you?")

        assert plan.speakers == ("Moira", "Ralph")
        assert "Moira or Ralph answers the voice:" in plan.instruction

    @pytest.mark.parametrize("transcript", ["moira, is it airborne?", "Is Ralphie there?"])
    def test_a_name_in_another_case_or_inside_a_word_does_not_narrow(self, transcript):
        assert plan_round(self._invited(), STORY, SHOW, played_s=190, transcript=transcript).speakers == CAST

    def test_a_transcript_outside_a_listening_window_is_ignored(self):
        plan = plan_round(_run(), STORY, SHOW, played_s=0, transcript="Moira, is it airborne?")

        assert (plan.kind, plan.listener) == ("free", None)
        assert "airborne" not in plan.instruction


class TestNames:
    @pytest.mark.parametrize("text, names", [
        ("Moira's lab is sealed.", {"Moira"}),
        ("Ralph, Daniel, over.", {"Daniel", "Ralph"}),
        ("Ralphie and moira", set()),
        ("Dr. Byrne, come in.", set()),
    ])
    def test_whole_words_exact_case(self, text, names):
        assert names_in(text, CAST) == names


class TestWording:
    def test_the_probe_round(self):
        assert instruction_for(("Moira", "Ralph"), 2,
                               "Something is scratching at the loading dock door, slow and rhythmic.", True) == (
            "Offstage: Something is scratching at the loading dock door, slow and rhythmic. "
            "Moira and Ralph speak next: the next two lines, each with the emotion in its voice.")

    def test_three_speakers_without_an_event(self):
        assert instruction_for(("Daniel", "Moira", "Ralph"), 3, None, True) == (
            "Daniel, Moira and Ralph speak next: the next three lines, each with the emotion in its voice.")

    def test_one_speaker_one_line(self):
        assert instruction_for(("Samantha",), 1, None, True) == (
            "Samantha speaks next: the next line, with the emotion in its voice.")
        assert instruction_for(("Samantha",), 1, None, False) == "Samantha speaks next: the next line."

    def test_four_lines_and_a_tone_word(self):
        assert instruction_for(("Moira", "Ralph"), 4, None, True, "brittle") == (
            "Moira and Ralph speak next: the next four lines, each with the emotion in its voice. "
            "Let the tone be: brittle.")
