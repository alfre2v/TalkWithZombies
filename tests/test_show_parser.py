"""Tests for app/show/parser.py — the show's stream parser.

REAL_ROUND is a real reply recorded on the box on 2026-09-23 (llama.cpp
b11096, Nemotron Nano 9B v2 Q4_K_M, the lab-outbreak cast sheet with
moods on, a grammar allowing Ralph and Moira and two lines, seed 42),
token by token as it was streamed.
"""

import pytest

from app.show.parser import LineParser, ScriptLine

REAL_ROUND = [
    'R', 'alph', ' (', 'urg', 'ent', '):', ' We', '’ve', ' got', ' something',
    ' outside', ',', ' rhythmic', ' pounding', '.', ' It', '’s', ' not', ' human', '.',
    ' Over', '.', '  ', '\n', 'Mo', 'ira', ' (', 'af', 'raid', '):', ' It', '’s',
    ' adapting', '.', ' Or', ' maybe', ' it', '’s', ' learning', '.', ' Over', '.\n',
]
REAL_TEXT = "".join(REAL_ROUND)
REAL_LINES = [
    ScriptLine("Ralph", "urgent",
               "Ralph (urgent): We’ve got something outside, rhythmic pounding. It’s not human. Over.  ",
               "We've got something outside, rhythmic pounding. It's not human. Over."),
    ScriptLine("Moira", "afraid",
               "Moira (afraid): It’s adapting. Or maybe it’s learning. Over.",
               "It's adapting. Or maybe it's learning. Over."),
]


def _run(pieces, moods=True):
    parser = LineParser(moods)
    events = []
    for piece in pieces:
        events += parser.feed(piece)
    parser.finish()
    return parser, events


def _per_line(events):
    """Collapse the events to (start, joined tokens, done) per line."""
    out, tokens = [], ""
    for event in events:
        if event["type"] == "start":
            out.append(("start", event["persona"], event["mood"]))
            tokens = ""
        elif event["type"] == "token":
            tokens += event["token"]
        elif event["type"] == "done":
            out.append(("tokens", event["persona"], tokens))
            out.append(("done", event["persona"], event["text"]))
    return out


def _spoken(body, moods=True):
    prefix = "Ralph (calm): " if moods else "Ralph: "
    parser, _ = _run([prefix + body + "\n"], moods)
    return parser.lines[0].spoken


class TestRealRound:
    def test_parses_both_lines(self):
        parser, _ = _run(REAL_ROUND)

        assert parser.lines == REAL_LINES
        assert parser.dropped == []

    def test_raw_is_byte_identical_to_the_model_output(self):
        parser, _ = _run(REAL_ROUND)
        assert "\n".join(line.raw for line in parser.lines) + "\n" == REAL_TEXT

    def test_events_carry_only_spoken_text(self):
        _, events = _run(REAL_ROUND)

        assert _per_line(events) == [
            ("start", "Ralph", "urgent"),
            ("tokens", "Ralph", REAL_LINES[0].spoken),
            ("done", "Ralph", REAL_LINES[0].spoken),
            ("start", "Moira", "afraid"),
            ("tokens", "Moira", REAL_LINES[1].spoken),
            ("done", "Moira", REAL_LINES[1].spoken),
        ]
        for event in events:
            assert "’" not in event.get("token", "") + event.get("text", "")

    def test_start_waits_for_the_whole_prefix(self):
        parser = LineParser(moods=True)
        assert parser.feed("R") + parser.feed("alph (urg") + parser.feed("ent):") == []
        assert parser.feed(" We") == [
            {"type": "start", "persona": "Ralph", "mood": "urgent"},
            {"type": "token", "persona": "Ralph", "token": "We"},
        ]

    @pytest.mark.parametrize("pieces", [
        [REAL_TEXT],
        list(REAL_TEXT),
        [REAL_TEXT[:40], REAL_TEXT[40:90], REAL_TEXT[90:]],
    ], ids=["one piece", "one character at a time", "three uneven pieces"])
    def test_chunking_makes_no_difference(self, pieces):
        reference_parser, reference_events = _run(REAL_ROUND)
        parser, events = _run(pieces)

        assert parser.lines == reference_parser.lines
        assert _per_line(events) == _per_line(reference_events)


class TestSpokenText:
    @pytest.mark.parametrize("body,spoken", [
        ("It’s here.", "It's here."),
        ("‘Quiet,’ she said.", "'Quiet,' she said."),
        ("He wrote “run” on the door.", 'He wrote "run" on the door.'),
        ("Wait—listen.", "Wait, listen."),
        ("Wait — listen.", "Wait, listen."),
        ("Well…", "Well..."),
        ("Doors holding. Over.   ", "Doors holding. Over."),
        ("Doors  holding.", "Doors holding."),
    ])
    def test_mapping(self, body, spoken):
        assert _spoken(body) == spoken

    @pytest.mark.parametrize("body", ['"Stay back. Over."', "“Stay back. Over.”", ' "Stay back. Over." '])
    def test_wrapping_quotes_removed_from_spoken_kept_in_raw(self, body):
        parser, _ = _run(["Moira (afraid): " + body + "\n"])

        assert parser.lines[0].spoken == "Stay back. Over."
        assert parser.lines[0].raw == "Moira (afraid): " + body

    def test_moods_off(self):
        parser, events = _run(["Ralph: Doors holding. Over.\n"], moods=False)

        assert parser.lines == [ScriptLine("Ralph", None, "Ralph: Doors holding. Over.", "Doors holding. Over.")]
        assert events[0] == {"type": "start", "persona": "Ralph", "mood": None}


class TestDroppedLines:
    def test_line_cut_short_is_dropped(self):
        parser, events = _run(REAL_ROUND[:24] + ["Mo", "ira", " (", "af", "raid", "):", " It", "’s", " adapt"])

        assert parser.lines == REAL_LINES[:1]
        assert parser.dropped == ["Moira (afraid): It’s adapt"]
        assert [e["type"] for e in events].count("done") == 1

    def test_malformed_line_is_dropped(self):
        parser, events = _run(["Nonsense without a prefix\n", "Ralph (calm): Fine. Over.\n"])

        assert parser.dropped == ["Nonsense without a prefix"]
        assert [line.speaker for line in parser.lines] == ["Ralph"]
        assert events[0]["type"] == "start"
