"""The debug switch: with show.debug on, each round leaves what the model read and wrote.

Two files per round in ``runs/<run-id>/debug/``: ``rNNN.txt`` to read (the
numbers, the grammar, the prompt exactly as the model read it, rendered by the
model server's /apply-template, and the reply as it streamed) and
``rNNN.request.json``, the exact request body, to replay with curl. The
rendered prompt's token count is checked against the size the server reported
for the request (prompt_n + cache_n); a difference is logged. Writing the files
never breaks a round: a failure is noted in the file, or logged.

The voice's side: the page tags each chunk it asks the voice for with its run
and place (``<run-id>/r009-l2-c1``: round 9, line 2, chunk 1), and the voice
route keeps the chunk in ``runs/<run-id>/debug/audio/``: the audio as the
engine returned it (``r009-l2-c1-Daniel-ref-extasy.wav``) and a ``.json``
beside it with what made it (the text, the clip asked for and used, the
clip's SHA-256 and transcript, the seed the page asked for, the engine's reply
without the audio: the seed it used, its timing). A tag that is not a run's and a place's,
or names a run with no folder, keeps nothing. Keeping a chunk never breaks the
voice: a failure is logged.
"""

import base64
import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.services.llm import count_tokens, render_prompt, round_payload
from app.show.script import RUN_ID, Heard, runs_root

logger = logging.getLogger(__name__)

_CHUNK_TAG = re.compile(rf"(?P<run_id>{RUN_ID.pattern})/(?P<place>r\d{{3}}-l\d+-c\d+)")
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


async def write_round(run_id: str, n: int, kind: str, messages: List[Dict[str, str]], *, grammar: str,
                      max_tokens: int, seed: int, reply: str, final: dict, heard: Optional[Heard] = None,
                      error: Optional[str] = None) -> None:
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
            *([_listener_line(heard)] if heard else []),
            *([f"error: {error}"] if error else []),
            "", "== grammar ==", grammar.rstrip("\n"),
            "", "== the prompt as the model read it (/apply-template) ==", prompt,
            "", "== the reply as it streamed ==", reply,
        ])
        (folder / f"r{n:03d}.txt").write_text(text + "\n", encoding="utf-8")
    except Exception as exc:
        logger.warning("Show run %s, round %s: debug files not written: %s", run_id, n, exc)


def write_chunk(tag: str, *, persona: str, text: str, language: str, asked: Optional[str], used: str, clip: Path,
                transcript: str, seed: Optional[int], reply: dict) -> Optional[Path]:
    """Keep one chunk of the show's voice, when its tag names a run and a place; the .wav's path, or None.

    `asked` is the clip the page named, `used` the one spoken with, `clip` its file and `transcript` its text;
    `seed` is the seed the page asked for, before the app fitted it into the engine's range (None: the engine picked
    one; the seed it used is in its reply, if it says); `reply` is the engine's reply. Never raises.
    """
    match = _CHUNK_TAG.fullmatch(tag)
    if not match:
        logger.warning("Show voice: the debug tag %r is not a run's and a place's; the chunk is not kept", tag)
        return None
    run_dir = runs_root() / match["run_id"]
    if not run_dir.is_dir():
        logger.warning("Show voice: no run %s; chunk %s is not kept", match["run_id"], match["place"])
        return None
    try:
        folder = run_dir / "debug" / "audio"
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{match['place']}-{_UNSAFE.sub('_', persona)}-{_UNSAFE.sub('_', Path(used).stem)}"
        wav = folder / f"{stem}.wav"
        wav.write_bytes(base64.b64decode(reply.get("audio_base64") or ""))
        record = {
            "tag": tag,
            "kept": datetime.now().isoformat(timespec="milliseconds"),
            "persona": persona,
            "text": text,
            "language": language,
            "reference_asked": asked,
            "reference_used": used,
            "clip": str(clip),
            "clip_sha256": hashlib.sha256(clip.read_bytes()).hexdigest(),
            "transcript": transcript,
            "seed_asked": seed,
            "reply": {k: v for k, v in reply.items() if k != "audio_base64"},
        }
        (folder / f"{stem}.json").write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n",
                                             encoding="utf-8")
        return wav
    except Exception as exc:
        logger.warning("Show voice: chunk %s not kept: %s", tag, exc)
        return None


def _listener_line(heard: Heard) -> str:
    """What Whisper heard, its confidence, and whether it counted as words or as silence."""
    verdict = f"silence: {heard.silence}" if heard.silence else "words"
    return (f"listener: heard {heard.text!r} | no_speech_prob {heard.no_speech_prob} | "
            f"avg_logprob {heard.avg_logprob} | {verdict}")


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
