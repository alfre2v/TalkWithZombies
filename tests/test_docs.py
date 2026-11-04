"""Docs consistency: AGENTS.md's API table must match the registered routes, and the show's settings named in the
docs' examples must exist.

The endpoint table is hand-maintained next to the code, so it drifts
silently (it has, historically). This test extracts the real /api/ routes
from the FastAPI app and compares them against the markdown table, failing
loudly if either set diverges. Route metadata (methods, paths) is static
at import time, so no lifespan, config, or network access is needed.

The runbooks' recipes (docs/runbooks/show-settings.md above all) and the README show settings as YAML examples
under `show:`. The app ignores a name it does not know without a word, so a renamed setting would leave a recipe
that silently does nothing: every name under `show:` in a YAML example must be a field of ShowConfig.

settings.example.yaml sets every show setting at its default value: it must name every field of ShowConfig once and
nothing else, and load through the app's own load_settings giving the defaults. So the reference cannot drift from
the code: a new setting, a renamed one or a changed default fails here until the example follows. And every show
setting is mentioned in docs/runbooks/show-settings.md, so a new one cannot ship without a recipe.
"""

import re
from collections import Counter
from pathlib import Path

import yaml

from app.config import ShowConfig, load_settings
from app.main import app

REPO = Path(__file__).resolve().parent.parent
AGENTS_MD = REPO / "AGENTS.md"
SETTINGS_EXAMPLE = REPO / "settings.example.yaml"
EXAMPLE_SHOW_LINE = re.compile(r"^  ([a-z_]+):")
YAML_BLOCK = re.compile(r"^[ \t]*```yaml\n(.*?)^[ \t]*```", re.S | re.M)

# Starlette auto-registers HEAD (for GET routes) and OPTIONS; they are not
# part of the documented API surface.
_IGNORED_METHODS = {"HEAD", "OPTIONS"}


def _actual_api_routes() -> set[tuple[str, str]]:
    """(METHOD, path) pairs exposed by the app, scoped to /api/ routes.

    Derived from the OpenAPI schema rather than app.routes: modern
    Starlette keeps included routers as lazy wrapper nodes in app.routes,
    so a flat scan no longer enumerates them, and the schema is the public
    surface the table actually documents. (It is also what HEAD/OPTIONS
    filtering falls out of for free — the schema lists neither.)
    Scoped to /api/ on purpose: the table documents the API, not the UI
    (GET /) or the /static mount.
    """
    routes = set()
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api/"):
            continue
        for method in operations:
            if method.upper() in _IGNORED_METHODS:
                continue
            routes.add((method.upper(), path))
    return routes


def _documented_api_routes() -> list[tuple[str, str]]:
    """(METHOD, path) pairs from the '## API endpoints' table in AGENTS.md.

    Returns a list (not a set) so the test can also detect duplicate rows.
    """
    text = AGENTS_MD.read_text(encoding="utf-8")
    match = re.search(
        r"^## API endpoints\s*$(.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, "AGENTS.md is missing the '## API endpoints' section"

    rows = []
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        method, path = cells[0], cells[1]
        # Skip the header row and the |---|---|---| separator row.
        if method.upper() == "METHOD" or set(method) <= {"-"}:
            continue
        method = method.strip("`").upper()
        # The table annotates one endpoint with an illustrative query string
        # (?room=<room>); route paths carry no query part.
        path = path.strip("`").split("?", 1)[0]
        rows.append((method, path))

    assert rows, "The AGENTS.md '## API endpoints' table contains no data rows"
    return rows


def test_agents_md_api_endpoints_table_matches_registered_routes():
    actual = _actual_api_routes()
    documented_rows = _documented_api_routes()
    documented = set(documented_rows)

    duplicates = sorted(r for r, count in Counter(documented_rows).items() if count > 1)
    assert not duplicates, f"Duplicate rows in the AGENTS.md API table: {duplicates}"

    missing_from_docs = sorted(actual - documented)
    assert not missing_from_docs, (
        "Routes registered on the app but missing from the AGENTS.md API table: "
        + ", ".join(f"{method} {path}" for method, path in missing_from_docs)
    )

    ghost_rows = sorted(documented - actual)
    assert not ghost_rows, (
        "Rows in the AGENTS.md API table that match no registered route: "
        + ", ".join(f"{method} {path}" for method, path in ghost_rows)
    )


def _show_examples():
    """(file, setting) for every name under `show:` in the YAML examples of the runbooks and the README."""
    found = []
    for path in sorted((REPO / "docs" / "runbooks").glob("*.md")) + [REPO / "README.md"]:
        for block in YAML_BLOCK.findall(path.read_text(encoding="utf-8")):
            lines = block.splitlines()
            indent = min((len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0)
            data = yaml.safe_load("\n".join(line[indent:] for line in lines))
            if isinstance(data, dict) and isinstance(data.get("show"), dict):
                found += [(path.name, name) for name in data["show"]]
    return found


def test_the_docs_show_setting_examples_exist():
    examples = _show_examples()
    assert len(examples) >= 20, f"too few show settings found in the docs' examples: {examples}"
    unknown = sorted({(file, name) for file, name in examples if name not in ShowConfig.model_fields})
    assert not unknown, "Settings in the docs' YAML examples that ShowConfig does not have: " + ", ".join(
        f"{name} ({file})" for file, name in unknown)


def _settings_example_show_names() -> list[str]:
    """The names set under `show:` in settings.example.yaml, in order; a name set twice is listed twice (YAML itself
    would keep only the last)."""
    lines = SETTINGS_EXAMPLE.read_text(encoding="utf-8").splitlines()
    names = []
    for line in lines[lines.index("show:") + 1:]:
        if line.strip() and not line.startswith(" "):
            break
        match = EXAMPLE_SHOW_LINE.match(line)
        if match:
            names.append(match.group(1))
    return names


def test_the_settings_example_lists_every_show_setting():
    names = _settings_example_show_names()
    twice = sorted(name for name, count in Counter(names).items() if count > 1)
    assert not twice, f"Show settings set twice in settings.example.yaml: {twice}"
    unknown = sorted(set(names) - set(ShowConfig.model_fields))
    assert not unknown, f"Show settings in settings.example.yaml that ShowConfig does not have: {unknown}"
    missing = sorted(set(ShowConfig.model_fields) - set(names))
    assert not missing, f"ShowConfig settings missing from settings.example.yaml: {missing}"


def test_the_settings_example_loads_at_the_defaults():
    written = yaml.safe_load(SETTINGS_EXAMPLE.read_text(encoding="utf-8"))["show"]
    assert len(written) == len(ShowConfig.model_fields), (
        f"settings.example.yaml sets {len(written)} show settings; ShowConfig has {len(ShowConfig.model_fields)}")
    settings = load_settings(SETTINGS_EXAMPLE)
    assert settings.show == ShowConfig(), "settings.example.yaml's show settings are not the defaults"
    assert settings.llm.base_url == "http://localhost:8080"


def test_every_show_setting_has_a_recipe():
    runbook = (REPO / "docs" / "runbooks" / "show-settings.md").read_text(encoding="utf-8")
    missing = [name for name in ShowConfig.model_fields
               if not re.search(rf"(?<![A-Za-z0-9_]){name}(?![A-Za-z0-9_])", runbook)]
    assert not missing, f"Show settings that docs/runbooks/show-settings.md never mentions: {missing}"
