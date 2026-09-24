"""The debug switch: with show.debug on, each round leaves what the model read and wrote.

Two files per round in ``runs/<run-id>/debug/``: ``rNNN.txt`` to read (the
numbers, the grammar, the prompt exactly as the model read it, rendered by the
model server's /apply-template, and the reply as it streamed) and
``rNNN.request.json``, the exact request body, to replay with curl. The
rendered prompt's token count is checked against the size the server reported
for the request (prompt_n + cache_n); a difference is logged. Writing the files
never breaks a round: a failure is noted in the file, or logged.
"""

import json
import logging
from typing import Dict, List, Optional, Tuple

from app.services.llm import count_tokens, render_prompt, round_payload
from app.show.script import runs_root

logger = logging.getLogger(__name__)


async def write_round(run_id: str, n: int, kind: str, messages: List[Dict[str, str]], *, grammar: str,
                      max_tokens: int, seed: int, reply: str, final: dict, error: Optional[str] = None) -> None:
    """Write round n's two debug files; never raise."""
    try:
        folder = runs_root() / run_id / "debug"
        folder.mkdir(parents=True, exist_ok=True)
        payload = round_payload(messages, grammar=grammar, max_tokens=max_tokens, seed=seed)
        (folder / f"r{n:03d}.request.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False),
                                                     encoding="utf-8")
        prompt, check = await _rendered(run_id, n, messages, final.get("timings"))
        text = "\n".join([
            f"round {n} ({kind}) of run {run_id}",
            f"seed {seed} | max_tokens {max_tokens} | finish {final.get('finish_reason')} | "
            f"timings {json.dumps(final.get('timings'))}",
            f"token check: {check}",
            *([f"error: {error}"] if error else []),
            "", "== grammar ==", grammar.rstrip("\n"),
            "", "== the prompt as the model read it (/apply-template) ==", prompt,
            "", "== the reply as it streamed ==", reply,
        ])
        (folder / f"r{n:03d}.txt").write_text(text + "\n", encoding="utf-8")
    except Exception as exc:
        logger.warning("Show run %s, round %s: debug files not written: %s", run_id, n, exc)


async def _rendered(run_id: str, n: int, messages: List[Dict[str, str]],
                    timings: Optional[Dict[str, int]]) -> Tuple[str, str]:
    """The rendered prompt and the token check's line; a warning when the counts differ."""
    try:
        prompt = await render_prompt(messages)
        counted = await count_tokens(prompt)
    except Exception as exc:
        logger.warning("Show run %s, round %s: the prompt could not be rendered for debug: %s", run_id, n, exc)
        return f"(not available: {exc})", "not available"
    if not timings:
        return prompt, f"the rendered prompt has {counted} tokens; the server reported no size"
    reported = timings.get("prompt_n", 0) + timings.get("cache_n", 0)
    if counted != reported:
        logger.warning("Show run %s, round %s: the rendered prompt has %s tokens but the server read %s",
                       run_id, n, counted, reported)
    return prompt, (f"the rendered prompt has {counted} tokens; the server read {reported} "
                    f"(prompt_n + cache_n); difference {counted - reported}")
