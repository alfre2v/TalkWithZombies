"""Parse the show's streamed reply into script lines and browser events.

The grammar makes the model write lines of the form ``Name: text`` (or
``Name (mood): text``), each ending with a line break, but the stream
arrives in arbitrary pieces. Each line keeps two texts: ``raw``, exactly
as the model wrote it, for the history; and ``spoken``, for the voice.
Every event carries spoken text only: with streaming TTS the browser
speaks from the ``token`` events as they arrive.

Characters are processed one at a time, so the texts never depend on
where the stream was split. A line without its line break (the reply was
cut short) or without a well-formed prefix is dropped: no ``done``, not
in ``lines``.
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

_SPOKEN = {"’": "'", "‘": "'", "“": '"', "”": '"', "—": ", ", "…": "..."}
_QUOTE = '"'
_NO_SPACE_BEFORE = set(",.!?;:")
_PREFIX_MOODS = re.compile(r"^(?P<name>[^()\n]+?) \((?P<mood>[^()\n]+)\): $")
_PREFIX_PLAIN = re.compile(r"^(?P<name>[^:\n]+): $")


@dataclass(frozen=True)
class ScriptLine:
    speaker: str
    mood: Optional[str]
    raw: str
    spoken: str


class LineParser:
    def __init__(self, moods: bool):
        self._prefix_re = _PREFIX_MOODS if moods else _PREFIX_PLAIN
        self._terminator = "): " if moods else ": "
        self.lines: List[ScriptLine] = []
        self.dropped: List[str] = []
        self._reset()

    def _reset(self):
        self._raw = ""
        self._speaker: Optional[str] = None
        self._mood: Optional[str] = None
        self._spoken = ""
        self._held = ""
        self._pending = ""

    def feed(self, piece: str) -> List[Dict]:
        events: List[Dict] = []
        for char in piece:
            self._step(char, events)
        self._flush_token(events)
        return events

    def finish(self) -> None:
        if self._raw:
            self.dropped.append(self._raw)
        self._reset()

    def _step(self, char: str, events: List[Dict]):
        if char == "\n":
            self._end_line(events)
            return
        self._raw += char
        if self._speaker is None:
            if self._raw.endswith(self._terminator):
                match = self._prefix_re.match(self._raw)
                if match:
                    self._speaker = match.group("name")
                    self._mood = match.groupdict().get("mood")
                    events.append({"type": "start", "persona": self._speaker, "mood": self._mood})
            return
        for out in _SPOKEN.get(char, char):
            self._body_char(out)

    def _body_char(self, char: str):
        if char == _QUOTE and not self._spoken and _QUOTE not in self._held:
            return
        if char.isspace() or char == _QUOTE:
            self._held += " " if char.isspace() else char
            return
        held, self._held = self._held, ""
        if held:
            quotes = held.replace(" ", "")
            text = quotes
            if " " in held and self._spoken and not self._spoken.endswith(" ") and char not in _NO_SPACE_BEFORE:
                text = " " + quotes if held.startswith(" ") else quotes + " "
            self._emit(text)
        self._emit(char)

    def _emit(self, text: str):
        self._spoken += text
        self._pending += text

    def _flush_token(self, events: List[Dict]):
        if self._pending and self._speaker is not None:
            events.append({"type": "token", "persona": self._speaker, "token": self._pending})
        self._pending = ""

    def _end_line(self, events: List[Dict]):
        self._flush_token(events)
        if self._speaker is None:
            if self._raw:
                self.dropped.append(self._raw)
        else:
            line = ScriptLine(self._speaker, self._mood, self._raw, self._spoken)
            self.lines.append(line)
            events.append({"type": "done", "persona": line.speaker, "text": line.spoken})
        self._reset()
