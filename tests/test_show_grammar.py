"""Tests for app/show/grammar.py — the screenplay grammar builder.

The two expected texts are the grammars proven on the box on
2026-09-22 (zombie-radio: docs/experiments/2026-09-22-adr-0003-gate/
screenplay.gbnf and docs/experiments/2026-09-22-emotion-grammar-cost/
screenplay-emotion.gbnf), byte for byte.
"""

import pytest

from app.show.grammar import MOODS, build_grammar

CAST = ["Daniel", "Moira", "Ralph", "Samantha"]

PROVEN_PLAIN = (
    'root    ::= line{1,4}\n'
    'line    ::= speaker ": " text "\\n"\n'
    'speaker ::= "Daniel" | "Moira" | "Ralph" | "Samantha"\n'
    'text    ::= [^\\n\\[\\]]+\n'
)

PROVEN_MOODS = (
    'root    ::= line{1,4}\n'
    'line    ::= speaker " (" emotion "): " text "\\n"\n'
    'speaker ::= "Daniel" | "Moira" | "Ralph" | "Samantha"\n'
    'emotion ::= "calm" | "happy" | "sad" | "afraid" | "terrified" | "doubtful" | "angry" | "urgent" | "exhausted"\n'
    'text    ::= [^\\n\\[\\]()]+\n'
)


class TestBuildGrammar:
    def test_moods_off_reproduces_the_proven_grammar(self):
        assert build_grammar(CAST, 4) == PROVEN_PLAIN

    def test_moods_on_reproduces_the_proven_grammar(self):
        assert build_grammar(CAST, 4, MOODS) == PROVEN_MOODS

    def test_allowlist_and_budget_are_filled_in(self):
        grammar = build_grammar(["Ralph", "Moira"], 2, MOODS)

        assert grammar.splitlines()[0] == "root    ::= line{1,2}"
        assert grammar.splitlines()[2] == 'speaker ::= "Ralph" | "Moira"'

    def test_single_line_round(self):
        assert build_grammar(["Samantha"], 1).splitlines()[:3] == [
            "root    ::= line{1,1}",
            'line    ::= speaker ": " text "\\n"',
            'speaker ::= "Samantha"',
        ]

    @pytest.mark.parametrize("speakers", [[], ["Ra\"lph"], ["Ralph\nMoira"], [" "], ["Ralph", "Ralph"]])
    def test_bad_speakers_rejected(self, speakers):
        with pytest.raises(ValueError):
            build_grammar(speakers, 2)

    @pytest.mark.parametrize("moods", [[], ["calm", 'sa"d']])
    def test_bad_moods_rejected(self, moods):
        with pytest.raises(ValueError):
            build_grammar(CAST, 2, moods)

    def test_budget_below_one_rejected(self):
        with pytest.raises(ValueError):
            build_grammar(CAST, 0)
