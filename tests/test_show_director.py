"""Tests for app/show/director.py — director v0."""

from app.show.director import instruction_for, plan_round
from app.show.script import Round, Run
from app.show.story import Story

CAST = ("Daniel", "Moira", "Ralph", "Samantha")
STORY = Story(name="lab", title="T", cast=CAST, operator="Samantha", template="",
              events=("First event.", "Second event.", "Third event."))


def _run(seed=42):
    return Run(run_id="r", started="s", story="lab", cast=list(CAST), moods=True, seed=seed, systems={"": "S"})


def _play(run, rounds, moods=True):
    """Plan and record `rounds` rounds; return the plans."""
    plans = []
    for _ in range(rounds):
        plan = plan_round(run, STORY, moods)
        run.rounds.append(Round(n=len(run.rounds) + 1, instruction=plan.instruction,
                                speakers=list(plan.speakers), max_lines=plan.max_lines, event=plan.event))
        plans.append(plan)
    return plans


class TestPlan:
    def test_speakers_and_budget_stay_in_bounds(self):
        for plan in _play(_run(), 30):
            assert 2 <= len(plan.speakers) <= 3
            assert list(plan.speakers) == [name for name in CAST if name in plan.speakers]
            assert plan.max_lines in (2, 3)
            assert plan.kind == "free"

    def test_words_and_grammar_state_the_same_constraints(self):
        for plan in _play(_run(), 30):
            number = {2: "two", 3: "three"}[plan.max_lines]
            assert f"the next {number} lines" in plan.instruction
            assert all(name in plan.instruction for name in plan.speakers)
            grammar = plan.grammar.splitlines()
            assert grammar[0] == f"root    ::= line{{1,{plan.max_lines}}}"
            assert grammar[2] == "speaker ::= " + " | ".join(f'"{name}"' for name in plan.speakers)

    def test_events_on_odd_rounds_without_repeats_until_the_pool_is_used(self):
        plans = _play(_run(), 12)
        events = [plan.event for plan in plans]

        assert all(event is None for event in events[1::2])
        odd = events[0::2]
        assert sorted(odd[:3]) == sorted(STORY.events)
        assert sorted(odd[3:]) == sorted(STORY.events)
        assert all(plan.instruction.startswith(f"Offstage: {plan.event} ") for plan in plans[0::2])
        assert not any(plan.instruction.startswith("Offstage:") for plan in plans[1::2])

    def test_same_seed_replays_the_same_plans(self):
        assert _play(_run(seed=7), 10) == _play(_run(seed=7), 10)
        assert _play(_run(seed=7), 10) != _play(_run(seed=8), 10)

    def test_moods_off(self):
        plan = _play(_run(), 1, moods=False)[0]

        assert "emotion" not in plan.instruction
        assert "emotion ::=" not in plan.grammar


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
