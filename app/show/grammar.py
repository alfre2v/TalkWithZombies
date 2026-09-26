"""GBNF screenplay grammar for one round of the show.

The model may write only lines of the form ``Name: text`` (or
``Name (mood): text`` with moods on), only for the round's allowed
speakers, and at most the round's line budget. A round may also pin
one speaker to its first line (the others follow) or to its last line
(the others lead up to it).
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


def build_grammar(speakers: Sequence[str], max_lines: int, moods: Optional[Sequence[str]] = None, *,
                  min_lines: int = 1, first: Optional[str] = None, last: Optional[str] = None) -> str:
    """The grammar of one round: min_lines to max_lines lines, each by one of the speakers.

    With first, the round's first line is that speaker's and every line after it belongs to one of the other
    speakers; with last, its last line is that speaker's and the lines before it belong to the others. Without
    either, the rules are those proven on the box on 2026-09-22.
    """
    if max_lines < 1:
        raise ValueError("max_lines must be at least 1")
    if not 1 <= min_lines <= max_lines:
        raise ValueError("min_lines must be between 1 and max_lines")
    if first is not None and last is not None:
        raise ValueError("pin the first line or the last, not both")
    tail = '" (" emotion "): " text "\\n"' if moods is not None else '": " text "\\n"'
    pinned = first if first is not None else last
    if pinned is None:
        rules = [f"root    ::= line{{{min_lines},{max_lines}}}", f"line    ::= speaker {tail}",
                 f"speaker ::= {_literals(speakers, 'speaker')}"]
    else:
        _literals(speakers, "speaker")
        if pinned not in speakers:
            raise ValueError(f"the pinned speaker {pinned!r} is not among {list(speakers)}")
        others = [name for name in speakers if name != pinned]
        more = f"line{{{min_lines - 1},{max_lines - 1}}}" if others and max_lines > 1 else ""
        if not more and min_lines > 1:
            raise ValueError(f"{min_lines} lines need a speaker besides {pinned!r}")
        root = " ".join(part for part in ((more, "pinned") if last is not None else ("pinned", more)) if part)
        rules = [f"root    ::= {root}", f"pinned  ::= {_literals([pinned], 'speaker')} {tail}"]
        if more:
            rules += [f"line    ::= speaker {tail}", f"speaker ::= {_literals(others, 'speaker')}"]
    if moods is not None:
        rules.append(f"emotion ::= {_literals(moods, 'mood')}")
    rules.append("text    ::= [^\\n\\[\\]()]+" if moods is not None else "text    ::= [^\\n\\[\\]]+")
    return "\n".join(rules) + "\n"
