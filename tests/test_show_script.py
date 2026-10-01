"""Tests for app/show/script.py — the run's record and the assembler.

The reply is the real one recorded on the box on 2026-09-23 (see
tests/test_show_parser.py): the history must carry it back exactly as
the model wrote it.
"""

from datetime import datetime

import pytest

from app.config import ShowConfig
from app.show.script import (
    Line, Round, Run, append_round, assemble_messages, known_size, load_run, new_run, reply_text, round_share,
    runs_root,
    script_size, trim,
)
from app.show.story import Story

REAL_REPLY = (
    "Ralph (urgent): We’ve got something outside, rhythmic pounding. It’s not human. Over.  \n"
    "Moira (afraid): It’s adapting. Or maybe it’s learning. Over.\n"
)
REAL_LINES = [
    Line(speaker="Ralph", mood="urgent",
         raw="Ralph (urgent): We’ve got something outside, rhythmic pounding. It’s not human. Over.  ",
         spoken="We've got something outside, rhythmic pounding. It's not human. Over."),
    Line(speaker="Moira", mood="afraid",
         raw="Moira (afraid): It’s adapting. Or maybe it’s learning. Over.",
         spoken="It's adapting. Or maybe it's learning. Over."),
]
READ = Line(speaker="Daniel", mood="afraid", raw="Daniel (afraid): A rack falls. Over.", spoken="A rack falls. Over.",
            fixed=True)
STORY = Story(name="lab-outbreak", title="T", cast=("Daniel", "Moira", "Ralph", "Samantha"),
              operator="Samantha", template="", events=("Something happens.",))
NOW = datetime(2026, 9, 24, 1, 23, 45)


def _round(n, lines=REAL_LINES, **kw):
    return Round(n=n, instruction=f"Instruction {n}.", speakers=["Ralph", "Moira"], max_lines=2, lines=lines, **kw)


class TestRecord:
    def test_new_run_writes_its_folder_and_file(self):
        run = new_run(STORY, ShowConfig(), "SYSTEM", seed=42, now=NOW)

        assert run.run_id == "2026-09-24T01-23-45"
        assert (runs_root() / run.run_id / "script.json").is_file()
        assert run.started == "2026-09-24T01:23:45"
        assert (run.story, run.cast, run.moods, run.seed) == ("lab-outbreak", list(STORY.cast), True, 42)
        assert run.systems == {"": "SYSTEM"}
        assert run.rounds == []

    def test_same_second_gets_a_suffix(self):
        first = new_run(STORY, ShowConfig(), "S", seed=1, now=NOW)
        second = new_run(STORY, ShowConfig(), "S", seed=1, now=NOW)
        third = new_run(STORY, ShowConfig(), "S", seed=1, now=NOW)

        assert [first.run_id, second.run_id, third.run_id] == [
            "2026-09-24T01-23-45", "2026-09-24T01-23-45-2", "2026-09-24T01-23-45-3"]

    def test_rounds_round_trip_and_no_temporary_file_is_left(self):
        run = new_run(STORY, ShowConfig(emotion_tags=False), "S", seed=7, now=NOW)
        append_round(run, _round(1, timings={"prompt_n": 4, "cache_n": 303, "predicted_n": 43},
                                 finish_reason="stop"))
        append_round(run, _round(2, lines=REAL_LINES[:1], dropped=["Moira (afraid): It’s adapt"],
                                 finish_reason="length", listener="Hello?"))

        assert load_run(run.run_id) == run
        assert [p.name for p in (runs_root() / run.run_id).iterdir()] == ["script.json"]

    def test_a_round_recorded_by_an_older_version_still_loads(self):
        old = Round.model_validate({"n": 1, "instruction": "I.", "speakers": ["Ralph"], "max_lines": 1})
        assert (old.event, old.kind, old.played_s, old.tone) == (None, "free", 0.0, None)
        assert (old.tokens, old.trims, old.heard) == (None, [], None)
        assert (old.overtone, old.agenda, old.slot, old.recollects) == (None, None, None, None)

    @pytest.mark.parametrize("kind", ["invitation", "answer", "static"])
    def test_the_kinds_before_step_3_4c_still_load(self, kind):
        old = Round.model_validate({"n": 1, "kind": kind, "instruction": "I.", "speakers": ["Samantha"],
                                    "max_lines": 1})
        assert old.kind == kind

    def test_the_fields_of_step_3_4c_round_trip(self):
        run = new_run(STORY, ShowConfig(), "S", seed=7, now=NOW)
        append_round(run, _round(1, kind="exchange", listener="Hello?", overtone="positive",
                                 agenda="Find out who the voice is."))
        append_round(run, _round(2, kind="free", overtone="negative", slot="recollection", recollects=1))

        assert load_run(run.run_id) == run


class TestAssembler:
    def test_system_then_alternating_turns_then_the_new_instruction(self):
        run = new_run(STORY, ShowConfig(), "SYSTEM", seed=42, now=NOW)
        append_round(run, _round(1))
        append_round(run, _round(2))

        messages = assemble_messages(run, "Instruction 3.")

        assert [m["role"] for m in messages] == ["system", "user", "assistant", "user", "assistant", "user"]
        assert messages[0]["content"] == "SYSTEM"
        assert [m["content"] for m in messages if m["role"] == "user"] == [
            "Instruction 1.", "Instruction 2.", "Instruction 3."]

    def test_the_reply_is_byte_identical_to_what_the_model_wrote(self):
        run = new_run(STORY, ShowConfig(), "SYSTEM", seed=42, now=NOW)
        append_round(run, _round(1))

        assert assemble_messages(run, "Next.")[2]["content"] == REAL_REPLY
        assert reply_text(run.rounds[0]) == REAL_REPLY

    def test_dropped_lines_stay_out_of_the_reply(self):
        round_ = _round(1, lines=REAL_LINES[:1], dropped=["Moira (afraid): It’s adapt"])
        assert reply_text(round_) == REAL_LINES[0].raw + "\n"

    def test_trimmed_empty_and_other_episode_rounds_are_skipped(self):
        run = new_run(STORY, ShowConfig(), "SYSTEM", seed=42, now=NOW)
        append_round(run, _round(1, trimmed=True))
        append_round(run, _round(2, lines=[], dropped=["Ralph (calm): Doo"]))
        append_round(run, _round(3, episode="01-supplies"))
        append_round(run, _round(4))

        contents = [m["content"] for m in assemble_messages(run, "Next.")]

        assert contents == ["SYSTEM", "Instruction 4.", REAL_REPLY, "Next."]

    def test_the_current_episode_chooses_the_system_text_and_its_rounds(self):
        run = new_run(STORY, ShowConfig(), "SYSTEM", seed=42, now=NOW)
        append_round(run, _round(1))
        run.systems["01-supplies"] = "SYSTEM FOR EPISODE 1"
        run.episode = "01-supplies"
        append_round(run, _round(2, episode="01-supplies"))

        contents = [m["content"] for m in assemble_messages(run, "Next.")]

        assert contents == ["SYSTEM FOR EPISODE 1", "Instruction 2.", REAL_REPLY, "Next."]

    def test_a_fixed_line_is_never_in_the_models_reply(self):
        run = new_run(STORY, ShowConfig(), "SYSTEM", seed=42, now=NOW)
        append_round(run, _round(1, lines=[READ, *REAL_LINES]))

        messages = assemble_messages(run, "Next.")

        assert [m["content"] for m in messages] == ["SYSTEM", "Instruction 1.", REAL_REPLY, "Next."]
        assert reply_text(run.rounds[0]) == REAL_REPLY

    def test_a_round_of_fixed_lines_only_joins_the_next_user_turn(self):
        run = new_run(STORY, ShowConfig(), "SYSTEM", seed=42, now=NOW)
        append_round(run, _round(1))
        append_round(run, _round(2, lines=[READ]))
        append_round(run, _round(3))

        messages = assemble_messages(run, "Next.")

        assert [m["role"] for m in messages] == ["system", "user", "assistant", "user", "assistant", "user"]
        assert messages[3]["content"] == "Instruction 2. Instruction 3."
        assert "A rack falls" not in "".join(m["content"] for m in messages)

    def test_a_text_ending_on_then_runs_into_the_next(self):
        run = new_run(STORY, ShowConfig(), "SYSTEM", seed=42, now=NOW)
        append_round(run, _round(1))
        called = Round(n=2, instruction='Samantha has just called out: "Answer us." Then', speakers=["Samantha"],
                       max_lines=0, lines=[READ])
        append_round(run, called)
        assert assemble_messages(run, "A voice says: \"Hello?\"")[-1]["content"] == (
            'Samantha has just called out: "Answer us." Then a voice says: "Hello?"')
        append_round(run, _round(3))
        assert assemble_messages(run, "Next.")[3]["content"] == (
            'Samantha has just called out: "Answer us." Then instruction 3.')

    def test_the_new_instruction_carries_a_last_round_of_fixed_lines_only(self):
        run = new_run(STORY, ShowConfig(), "SYSTEM", seed=42, now=NOW)
        append_round(run, _round(1))
        append_round(run, _round(2, lines=[READ]))
        assert assemble_messages(run, "Next.")[-1]["content"] == "Instruction 2. Next."

    def test_no_bracketed_speaker_labels_anywhere(self):
        run = new_run(STORY, ShowConfig(), "SYSTEM", seed=42, now=NOW)
        append_round(run, _round(1))

        text = "".join(m["content"] for m in assemble_messages(run, "Next."))
        assert not any(f"[{name}]:" in text for name in STORY.cast)


def _sized(count, size, share=100):
    """A run of `count` rounds with lines, each recording `share` tokens; the last reports `size` tokens."""
    run = Run(run_id="r", started="s", story="lab-outbreak", cast=list(STORY.cast), moods=True, seed=1,
              systems={"": "S"})
    for n in range(1, count + 1):
        run.rounds.append(_round(n, tokens=share))
    run.rounds[-1].timings = {"prompt_n": size - 50, "cache_n": 0, "predicted_n": 50}
    return run


def _budget(budget, **trim):
    """The show settings the trim reads: the budget, and any of its thresholds or kept rounds."""
    return ShowConfig(context_budget=budget, **trim)


class TestTrim:
    def test_the_size_is_what_the_server_reported_after_the_last_round(self):
        run = _sized(3, 1234)
        assert script_size(run) == 1234
        run.rounds[-1].timings = None
        assert script_size(run) is None

    def test_no_trim_below_ninety_percent_or_without_a_size(self):
        assert trim(_sized(20, 1799), _budget(2000)) == []
        run = _sized(20, 1900)
        run.rounds[-1].timings = None
        assert trim(run, _budget(2000)) == []
        assert not any(r.trimmed for r in run.rounds)

    def test_middle_rounds_are_flagged_outwards_until_half_the_budget(self):
        run = _sized(20, 1900)

        flagged = trim(run, _budget(2000))

        assert flagged == list(range(6, 15))
        assert [r.n for r in run.rounds if r.trimmed] == flagged

    def test_the_first_two_and_last_four_rounds_are_never_flagged(self):
        run = _sized(20, 5000)

        assert trim(run, _budget(2000)) == list(range(3, 17))
        assert trim(_sized(6, 5000), _budget(2000)) == []

    def test_a_second_trim_takes_the_middle_of_what_remains(self):
        run = _sized(20, 1900)
        trim(run, _budget(2000))
        for n in range(21, 31):
            run.rounds.append(_round(n, tokens=100))
        run.rounds[-1].timings = {"prompt_n": 1850, "cache_n": 0, "predicted_n": 50}

        assert trim(run, _budget(2000)) == list(range(15, 24))
        assert [r.n for r in run.rounds if not r.trimmed] == [1, 2, 3, 4, 5, 24, 25, 26, 27, 28, 29, 30]

    def test_rounds_the_model_does_not_read_are_not_candidates(self):
        run = _sized(12, 1900)
        run.rounds[2].lines = []
        run.rounds[3].episode = "earlier"

        flagged = trim(run, _budget(2000))

        assert 3 not in flagged and 4 not in flagged
        assert flagged == [5, 6, 7, 8]

    def test_the_trigger_and_the_target_are_settings(self):
        assert trim(_sized(20, 1500), _budget(2000, trim_trigger=0.8)) == []
        assert trim(_sized(20, 1600), _budget(2000, trim_trigger=0.8)) == list(range(7, 13))
        assert trim(_sized(20, 1900), _budget(2000, trim_target=0.7)) == list(range(8, 13))

    def test_the_rounds_kept_at_each_end_are_settings(self):
        run = _sized(20, 5000)

        assert trim(run, _budget(2000, trim_keep_first=5, trim_keep_last=1)) == list(range(6, 20))

    def test_the_known_size_steps_back_over_a_round_the_server_reported_nothing_for(self):
        run = _sized(5, 1200)
        run.rounds.append(_round(6, tokens=None))  # A Repair: no model request, no timings
        assert script_size(run) is None
        assert known_size(run) == 1200

        run.rounds[-1].trims = [3]  # A trim fell after the last reported size: it no longer holds
        assert known_size(run) is None
        assert known_size(_sized(3, 900)) == 900
        run = _sized(3, 900)
        run.rounds[-1].timings = None
        assert known_size(run) is None

    def test_a_round_share_is_its_size_less_the_size_before_it(self):
        assert round_share(900, 0, {"prompt_n": 120, "cache_n": 830, "predicted_n": 50}) == 100
        assert round_share(1900, 900, {"prompt_n": 900, "cache_n": 150, "predicted_n": 50}) == 100
        assert round_share(None, 0, {"prompt_n": 300, "cache_n": 0, "predicted_n": 50}) is None
        assert round_share(900, 0, None) is None
