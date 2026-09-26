"""Stories: the cast sheet template, its cast, its emotional palette, its events and its agenda.

A story is a folder ``stories/<name>/`` holding:

- ``cast_sheet.md`` — YAML front matter for the code (the title, the cast, the operator, the facts an orientation
  round tells newcomers, a stage direction for each receiver beat) and a Jinja body for the model;
- ``overtones.yaml`` — the emotional palette: the overtones in order, neighbors next to each other, each with the
  moods a line may carry and its tone words by theme; the overtones each kind of round may use; the weights of the
  free rounds' drift from one overtone to a neighbor;
- ``events.yaml`` — the events, filed by overtone, then by theme;
- ``agenda.yaml`` — what the cast want from a listener, one item per exchange; the first opens every contact.

The body's placeholders are filled at render time: ``model_prefix`` from the settings, ``format_rules`` from the
rule snippet the emotion switch picks, ``episode`` from the current episode.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from jinja2 import Environment, StrictUndefined

from app import config as app_config
from app.config import ShowConfig
from app.services.persona_store import parse_frontmatter
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
    """One overtone of a story's palette: the moods a line may carry, and the tone words by theme."""
    name: str
    moods: Tuple[str, ...]
    tones: Dict[str, Tuple[str, ...]]


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
                 directions={beat: text.strip() for beat, text in directions.items()})


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
    every overtone, not all 0.
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
        overtones.append(Overtone(name=overtone, moods=moods, tones=tones))
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


def format_rules(emotion_tags: bool) -> str:
    snippet = (_RULES_DIR / ("format_moods.md" if emotion_tags else "format_plain.md")).read_text(encoding="utf-8")
    return _JINJA.from_string(snippet.strip()).render(moods=", ".join(MOODS))


def render_cast_sheet(story: Story, show: ShowConfig, episode: str = "") -> str:
    rendered = _JINJA.from_string(story.template).render(
        model_prefix=show.model_prefix,
        format_rules=format_rules(show.emotion_tags),
        episode=episode,
    )
    return rendered.strip()
