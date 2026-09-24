"""Stories: the cast sheet template, its cast, and its pool of events.

A story is a folder ``stories/<name>/`` holding ``cast_sheet.md`` (YAML
front matter for the code, a Jinja body for the model) and
``events.yaml``. The body's placeholders are filled at render time:
``model_prefix`` from the settings, ``format_rules`` from the rule
snippet the emotion switch picks, ``episode`` from the current episode.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import yaml
from jinja2 import Environment, StrictUndefined

from app import config as app_config
from app.config import ShowConfig
from app.services.persona_store import parse_frontmatter
from app.show.grammar import MOODS

_RULES_DIR = Path(__file__).resolve().parent / "rules"
_JINJA = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)


class StoryError(ValueError):
    pass


@dataclass(frozen=True)
class Story:
    name: str
    title: str
    cast: Tuple[str, ...]
    operator: str
    template: str
    events: Tuple[str, ...]


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

    voices = {p.name for p in app_config.get_personas().personas if p.reference_audio}
    missing = [n for n in cast if n not in voices]
    if missing:
        raise StoryError(f"story {name!r}: no persona with a reference voice for {', '.join(missing)}")

    return Story(name=name, title=title.strip(), cast=tuple(cast), operator=operator,
                 template=body, events=_load_events(name, folder / "events.yaml"))


def _load_events(name: str, path: Path) -> Tuple[str, ...]:
    if not path.is_file():
        raise StoryError(f"story {name!r}: {path} not found")
    events = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("events")
    if not isinstance(events, list) or not events or not all(isinstance(e, str) and e.strip() for e in events):
        raise StoryError(f"story {name!r}: events.yaml needs 'events', a list of sentences")
    return tuple(e.strip() for e in events)


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
