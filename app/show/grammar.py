"""GBNF screenplay grammar for one round of the show.

The model may write only lines of the form ``Name: text`` (or
``Name (mood): text`` with moods on), only for the round's allowed
speakers, and at most the round's line budget.
"""

from typing import Optional, Sequence

MOODS = ("calm", "happy", "sad", "afraid", "terrified", "doubtful", "angry", "urgent", "exhausted")

_FORBIDDEN_IN_LITERAL = set('"\\\n\r')


def _literals(values: Sequence[str], what: str) -> str:
    if not values:
        raise ValueError(f"at least one {what} is required")
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {what} in {list(values)}")
    for value in values:
        if not value or not value.strip() or _FORBIDDEN_IN_LITERAL & set(value):
            raise ValueError(f"invalid {what}: {value!r}")
    return " | ".join(f'"{value}"' for value in values)


def build_grammar(speakers: Sequence[str], max_lines: int, moods: Optional[Sequence[str]] = None) -> str:
    if max_lines < 1:
        raise ValueError("max_lines must be at least 1")
    rules = [f"root    ::= line{{1,{max_lines}}}"]
    if moods is None:
        rules += [
            'line    ::= speaker ": " text "\\n"',
            f"speaker ::= {_literals(speakers, 'speaker')}",
            "text    ::= [^\\n\\[\\]]+",
        ]
    else:
        rules += [
            'line    ::= speaker " (" emotion "): " text "\\n"',
            f"speaker ::= {_literals(speakers, 'speaker')}",
            f"emotion ::= {_literals(moods, 'mood')}",
            "text    ::= [^\\n\\[\\]()]+",
        ]
    return "\n".join(rules) + "\n"
