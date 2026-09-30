"""Stories: the cast sheet template, its cast, its emotional palette, its events and its agenda.

A story is a folder ``stories/<name>/`` holding:

- ``cast_sheet.md`` — YAML front matter for the code (the title, the cast, the operator, the facts an orientation
  round tells newcomers, a stage direction for each receiver beat) and a Jinja body for the model;
- ``overtones.yaml`` — the emotional palette: the overtones in order, neighbors next to each other, each with the
  moods a line may carry, the voice each mood is spoken with (optional) and its tone words by theme; the overtones
  each kind of round may use; the weights of the free rounds' drift from one overtone to a neighbor;
- ``events.yaml`` — the events, filed by overtone, then by theme;
- ``agenda.yaml`` — what the cast want from a listener, one item per exchange; the first opens every contact;
- ``beats.yaml`` (optional) — the receiver beats' fixed lines, said word for word by a cast member instead of written
  by the model; without it, the model writes the beats.

The body's placeholders are filled at render time: ``model_prefix`` from the settings, ``format_rules`` from the
rule snippet the emotion switch picks, ``episode`` from the current episode.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import yaml
from jinja2 import Environment, StrictUndefined

from app import config as app_config
from app.config import ShowConfig
from app.services.persona_store import REFERENCE_CLIP, parse_frontmatter
from app.show.grammar import MOODS

_RULES_DIR = Path(__file__).resolve().parent / "rules"
_JINJA = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)
_MOOD = re.compile(r"[a-z]+(?:[ -][a-z]+)*")

# The kinds of round whose overtones a story's palette sets (free rounds drift instead), and the receiver beats
# that carry a stage direction.
KINDS = ("orientation", "repair", "exchange", "re-call", "breakdown", "switch-off")
DIRECTED = ("repair", "breakdown", "switch-off")


class StoryError(ValueError):
    pass


@dataclass(frozen=True)
class Overtone:
    """One overtone of a story's palette: the moods a line may carry, and the tone words by theme.

    voices names, for each mood, the reference clip a line in that mood is spoken with (ref.wav, the default
    voice, or a recording beside it such as ref-fear.wav, in every persona's folder); empty when the story
    declares no voices.
    """
    name: str
    moods: Tuple[str, ...]
    tones: Dict[str, Tuple[str, ...]]
    voices: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Beats:
    """The receiver beats' fixed lines (beats.yaml), several versions of each, drawn without repeats.

    A Repair is two lines, the announcement and the operator's call, told apart by how the receiver went off; the
    Breakdown's is the operator's closing line; the Switch-off's is the operator's opening line, told apart by
    whether nobody answered the call or the voice of a contact was lost.
    """
    repair_after_breakdown: Tuple[Tuple[str, str], ...]
    repair_after_switch_off: Tuple[Tuple[str, str], ...]
    breakdown: Tuple[str, ...]
    switch_off_nobody_answered: Tuple[str, ...]
    switch_off_voice_lost: Tuple[str, ...]


@dataclass(frozen=True)
class Story:
    """A loaded story.

    events and tones hold every event and every tone word, flattened; event_pools and overtones hold them filed
    by overtone and theme.
    """
    name: str
    title: str
    cast: Tuple[str, ...]
    operator: str
    template: str
    events: Tuple[str, ...]
    tones: Tuple[str, ...] = ()
    overtones: Tuple[Overtone, ...] = ()
    kinds: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    weights: Dict[str, float] = field(default_factory=dict)
    event_pools: Dict[str, Dict[str, Tuple[str, ...]]] = field(default_factory=dict)
    agenda: Tuple[str, ...] = ()
    orientation: str = ""
    directions: Dict[str, str] = field(default_factory=dict)
    beats: Optional[Beats] = None


def load_story(name: str, root: Optional[Path] = None) -> Story:
    folder = (root or app_config._PROJECT_ROOT / "stories") / name
    sheet = folder / "cast_sheet.md"
    if not sheet.is_file():
        raise StoryError(f"story {name!r}: {sheet} not found")
    meta, body = parse_frontmatter(sheet.read_text(encoding="utf-8"))

    title = meta.get("title")
    if not isinstance(title, str) or not title.strip():
        raise StoryError(f"story {name!r}: the front matter needs a title (missing or malformed front matter?)")
    cast = meta.get("cast")
    if not isinstance(cast, list) or not cast or not all(isinstance(n, str) and n.strip() for n in cast):
        raise StoryError(f"story {name!r}: the front matter needs a cast, a list of names")
    if len(set(cast)) != len(cast):
        raise StoryError(f"story {name!r}: the cast repeats a name: {cast}")
    operator = meta.get("operator")
    if operator not in cast:
        raise StoryError(f"story {name!r}: the operator {operator!r} is not in the cast {cast}")

    orientation = meta.get("orientation")
    if not isinstance(orientation, str) or not orientation.strip():
        raise StoryError(f"story {name!r}: the front matter needs an orientation, the facts newcomers are told")
    directions = meta.get("directions")
    if (not isinstance(directions, dict) or set(directions) != set(DIRECTED)
            or not all(isinstance(text, str) and text.strip() for text in directions.values())):
        raise StoryError(f"story {name!r}: the front matter needs directions, one stage direction for each of "
                         f"{', '.join(DIRECTED)}")

    voices = {p.name for p in app_config.get_personas().personas if p.reference_audio}
    missing = [n for n in cast if n not in voices]
    if missing:
        raise StoryError(f"story {name!r}: no persona with a reference voice for {', '.join(missing)}")

    overtones, kinds, weights = _load_overtones(name, folder / "overtones.yaml")
    pools = _load_events(name, folder / "events.yaml", [o.name for o in overtones])
    return Story(name=name, title=title.strip(), cast=tuple(cast), operator=operator, template=body,
                 events=tuple(e for themes in pools.values() for items in themes.values() for e in items),
                 tones=tuple(w for o in overtones for words in o.tones.values() for w in words),
                 overtones=overtones, kinds=kinds, weights=weights, event_pools=pools,
                 agenda=_load_agenda(name, folder / "agenda.yaml"), orientation=orientation.strip(),
                 directions={beat: text.strip() for beat, text in directions.items()},
                 beats=_load_beats(name, folder / "beats.yaml"))


def _read_yaml(name: str, path: Path) -> dict:
    """A story file's YAML mapping: a StoryError when the file is missing, an empty mapping when it holds none."""
    if not path.is_file():
        raise StoryError(f"story {name!r}: {path} not found")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _texts(value) -> Optional[Tuple[str, ...]]:
    """The value as a tuple of stripped strings, or None unless it is a non-empty list of non-blank strings."""
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v.strip() for v in value):
        return None
    return tuple(v.strip() for v in value)


def _load_overtones(name: str, path: Path) -> Tuple[Tuple[Overtone, ...], Dict[str, Tuple[str, ...]],
                                                    Dict[str, float]]:
    """Read overtones.yaml: the overtones in order, the overtones each kind of round may use, and the weights.

    Checks what the director relies on: each mood a plain lowercase word, in one overtone only; each tone word
    once, and never a mood; every kind of round given one overtone or two neighbors; a weight of at least 0 for
    every overtone, not all 0. The voices are optional, but all or nothing: once one overtone names them, every
    overtone must, for each of its moods and no other, each a reference clip's plain name.
    """
    def fail(what: str):
        raise StoryError(f"story {name!r}: overtones.yaml {what}")

    data = _read_yaml(name, path)
    raw = data.get("overtones")
    if not isinstance(raw, dict) or not raw:
        fail("needs 'overtones', a mapping of overtone names")
    overtones: List[Overtone] = []
    mood_home: Dict[str, str] = {}
    tone_home: Dict[str, str] = {}
    for overtone, spec in raw.items():
        overtone = str(overtone)
        moods = _texts(spec.get("moods")) if isinstance(spec, dict) else None
        if moods is None or not all(_MOOD.fullmatch(m) for m in moods):
            fail(f"needs moods under {overtone!r}, a list of plain lowercase words")
        themes = spec.get("tones") or {}
        if not isinstance(themes, dict):
            fail(f"needs tones under {overtone!r}, a mapping of themes to lists of words")
        tones = {}
        for theme, words in themes.items():
            tones[str(theme)] = _texts(words) or fail(f"needs a list of words under {overtone!r} / {theme!r}")
        for mood in moods:
            if mood in mood_home:
                fail(f"puts the mood {mood!r} in two overtones, {mood_home[mood]!r} and {overtone!r}")
            mood_home[mood] = overtone
        for word in (w for words in tones.values() for w in words):
            if word in tone_home:
                fail(f"repeats the tone word {word!r}")
            tone_home[word] = overtone
        voices = _voices(spec.get("voices"), moods, lambda what: fail(f"{what} under {overtone!r}"))
        overtones.append(Overtone(name=overtone, moods=moods, tones=tones, voices=voices))
    voiced = [o.name for o in overtones if o.voices]
    if voiced and len(voiced) < len(overtones):
        fail(f"names voices under {', '.join(voiced)} but not under every overtone")
    both = sorted(set(mood_home) & set(tone_home))
    if both:
        fail(f"uses {', '.join(both)} as both a mood and a tone word")

    names = [o.name for o in overtones]
    raw_kinds = data.get("kinds")
    if not isinstance(raw_kinds, dict) or set(raw_kinds) != set(KINDS):
        fail(f"needs 'kinds', the overtones for each of {', '.join(KINDS)}")
    kinds = {}
    for kind, allowed in raw_kinds.items():
        allowed = _texts(allowed)
        if (allowed is None or len(allowed) > 2 or not set(allowed) <= set(names)
                or len(allowed) == 2 and abs(names.index(allowed[0]) - names.index(allowed[1])) != 1):
            fail(f"gives {kind!r} {raw_kinds[kind]!r}: it needs one overtone, or two neighbors, of {names}")
        kinds[kind] = allowed

    weights = data.get("weights")
    if (not isinstance(weights, dict) or set(weights) != set(names)
            or not all(isinstance(w, (int, float)) and not isinstance(w, bool) and w >= 0 for w in weights.values())
            or not sum(weights.values())):
        fail(f"needs 'weights', a number of at least 0 for each of {names}, not all 0")
    return tuple(overtones), kinds, {o: float(weights[o]) for o in names}


def _load_events(name: str, path: Path, overtones: List[str]) -> Dict[str, Dict[str, Tuple[str, ...]]]:
    """Read events.yaml: the events by overtone, then by theme. An overtone may have none; no event twice."""
    def fail(what: str):
        raise StoryError(f"story {name!r}: events.yaml {what}")

    raw = _read_yaml(name, path).get("events")
    if not isinstance(raw, dict) or not raw or not {str(o) for o in raw} <= set(overtones):
        fail(f"needs 'events', filed under the story's overtones {overtones}")
    pools: Dict[str, Dict[str, Tuple[str, ...]]] = {}
    seen = set()
    for overtone, themes in raw.items():
        if not isinstance(themes, dict) or not themes:
            fail(f"needs themes under {overtone!r}, each a list of events")
        pool = {}
        for theme, items in themes.items():
            items = _texts(items) or fail(f"needs a list of events under {overtone!r} / {theme!r}")
            for event in items:
                if event in seen:
                    fail(f"repeats the event {event!r}")
                seen.add(event)
            pool[str(theme)] = items
        pools[str(overtone)] = pool
    return pools


def _load_agenda(name: str, path: Path) -> Tuple[str, ...]:
    """Read agenda.yaml: what the cast want from a listener, the first item opening every contact."""
    agenda = _texts(_read_yaml(name, path).get("agenda"))
    if agenda is None or len(agenda) < 2 or len(set(agenda)) != len(agenda):
        raise StoryError(f"story {name!r}: agenda.yaml needs 'agenda', a list of at least two different items")
    return agenda


def _load_beats(name: str, path: Path) -> Optional[Beats]:
    """Read beats.yaml, if the story has one: every list non-empty, every text a non-blank string, each Repair a
    pair of lines. None without the file."""
    if not path.is_file():
        return None
    data = _read_yaml(name, path)

    def fail(what: str):
        raise StoryError(f"story {name!r}: beats.yaml needs {what}")

    def section(key: str) -> dict:
        value = data.get(key)
        return value if isinstance(value, dict) else fail(f"'{key}', a mapping")

    def texts(value, where: str) -> Tuple[str, ...]:
        return _texts(value) or fail(f"'{where}', a list of lines")

    def pairs(value, where: str) -> Tuple[Tuple[str, str], ...]:
        if not isinstance(value, list) or not value:
            fail(f"'{where}', a list of pairs of lines")
        found = [texts(pair, where) for pair in value]
        return tuple((a, b) for a, b in found) if all(len(p) == 2 for p in found) else fail(
            f"'{where}' of pairs: the announcement, then the call")

    repair, switch_off = section("repair"), section("switch-off")
    return Beats(repair_after_breakdown=pairs(repair.get("after-breakdown"), "repair: after-breakdown"),
                 repair_after_switch_off=pairs(repair.get("after-switch-off"), "repair: after-switch-off"),
                 breakdown=texts(data.get("breakdown"), "breakdown"),
                 switch_off_nobody_answered=texts(switch_off.get("nobody-answered"), "switch-off: nobody-answered"),
                 switch_off_voice_lost=texts(switch_off.get("voice-lost"), "switch-off: voice-lost"))


def _voices(raw, moods: Tuple[str, ...], fail) -> Dict[str, str]:
    """An overtone's voices: a clip's plain name for each of its moods, or none at all."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        fail("needs voices as a mapping of moods to reference clips")
    voices = {str(mood): str(clip) for mood, clip in raw.items()}
    if set(voices) != set(moods):
        fail(f"needs a voice for each mood ({', '.join(moods)}) and no other")
    bad = sorted(clip for clip in voices.values() if not REFERENCE_CLIP.fullmatch(clip))
    if bad:
        fail(f"names {', '.join(bad)}, not a reference clip (ref.wav or ref-<word>.wav)")
    return voices


def voice_map(story: Story) -> Dict[str, str]:
    """Every mood of the story and the reference clip it is spoken with; empty when the story declares no voices."""
    return {mood: clip for o in story.overtones for mood, clip in o.voices.items()}


def all_moods(story: Story) -> List[str]:
    """Every mood of the story's overtones, in order; the engine's nine for a story without overtones."""
    return [m for o in story.overtones for m in o.moods] or list(MOODS)


def format_rules(emotion_tags: bool, moods: Sequence[str] = MOODS) -> str:
    """The format paragraph of the cast sheet: the one with the emotion tags and their list, or the plain one."""
    snippet = (_RULES_DIR / ("format_moods.md" if emotion_tags else "format_plain.md")).read_text(encoding="utf-8")
    return _JINJA.from_string(snippet.strip()).render(moods=", ".join(moods))


def render_cast_sheet(story: Story, show: ShowConfig, episode: str = "") -> str:
    rendered = _JINJA.from_string(story.template).render(
        model_prefix=show.model_prefix,
        format_rules=format_rules(show.emotion_tags, all_moods(story)),
        episode=episode,
    )
    return rendered.strip()
