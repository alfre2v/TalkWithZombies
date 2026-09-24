"""Tests for app/show/script.py — the run's record and the assembler.

The reply is the real one recorded on the box on 2026-09-23 (see
tests/test_show_parser.py): the history must carry it back exactly as
the model wrote it.
"""

from datetime import datetime

from app.config import ShowConfig
from app.show.script import (
    Line, Round, append_round, assemble_messages, load_run, new_run, reply_text, runs_root,
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

    def test_a_round_recorded_before_the_event_and_director_v1_fields_still_loads(self):
        old = Round.model_validate({"n": 1, "instruction": "I.", "speakers": ["Ralph"], "max_lines": 1})
        assert (old.event, old.kind, old.played_s, old.tone) == (None, "free", 0.0, None)


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

    def test_no_bracketed_speaker_labels_anywhere(self):
        run = new_run(STORY, ShowConfig(), "SYSTEM", seed=42, now=NOW)
        append_round(run, _round(1))

        text = "".join(m["content"] for m in assemble_messages(run, "Next."))
        assert not any(f"[{name}]:" in text for name in STORY.cast)
