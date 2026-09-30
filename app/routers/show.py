"""Show router — open a run, then play its rounds.

GET /show serves the chooser (templates/show_choose.html): a card per design
of static/show/designs/, and one for the plain page. GET /show?design=<name>
serves the show page in that design (templates/show_design.html);
GET /show?design=plain the plain page (templates/show.html, with its own files
in static/show/), untouched.
POST /api/show/start opens a run of a story and gives the
page the settings it needs. POST /api/show/round plays
the run's next round and streams the chat's SSE events (start / token /
done) for each script line, then a "round" summary and "complete". The
server keeps no show state between requests: the caller sends the run id,
and the run is loaded from its record. Each request carries the running
total of show audio played. After a round whose summary says `listens`
(a Repair, an exchange, a re-call) the page listens: POST /api/show/listen
transcribes the recording with the show's Whisper settings, and the next
round request carries what was heard, with Whisper's confidence. The round
decides whether it counts as words or as silence with the transcript filter
(app/show/listen.py) — the director then plans an exchange or a Breakdown,
a re-call or a Switch-off — records what was heard either way, and reports
it on the "round" summary (`heard`: the text, Whisper's numbers, and why it
counted as silence, if it did). The summary also carries the round's
overtone, the agenda item it asked, what filled its event slot, the
listener's answers so far in a contact and the number that ends it, and
the stage direction of a receiver beat (the story's), and whether the
receiver is still on (`receiver`: through the rounds that listen and
the last exchange, which asks nothing before the Breakdown).
A round's fixed lines (the director's, said word for word: an event read
aloud, a receiver beat's key line) are streamed in their place with the
same events, marked `fixed`, and recorded with the model's; a round made
only of fixed lines does not ask the model.
With show.debug on, each round also leaves its debug files
(app/show/debug.py), failed rounds included, and a recorded round keeps
them even when the client leaves while they are being written.
"""

import asyncio
import base64
import dataclasses
import json
import logging
import random
import re
from pathlib import Path
from typing import AsyncIterator, List, Optional, Tuple

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app import config as app_config
from app.models import (ShowListenRequest, ShowListenResponse, ShowRoundRequest, ShowStartRequest,
                        ShowStartResponse)
from app.services.llm import stream_round
from app.services.stt_client import transcribe_for_show
from app.show.debug import write_round
from app.show.director import LISTENS, plan_round
from app.show.listen import usable
from app.show.parser import LineParser
from app.show.script import (Heard, Line, Round, Run, append_round, assemble_messages, load_run, new_run,
                             round_share, script_size, trim)
from app.show.story import Story, StoryError, load_story, render_cast_sheet, voice_map

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/show", tags=["show"])
page_router = APIRouter(tags=["show"])
_templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent.parent / "templates"))

_RUN_ID = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(-\d+)?$")
_DESIGNS = Path(__file__).resolve().parent.parent.parent / "static" / "show" / "designs"
_DESIGN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _designs() -> List[dict]:
    """The designs of static/show/designs/, in the chooser's order: each folder with a design.css, its design.yaml
    giving the title, a line about it and its place (the folder's name, no line and last without one)."""
    designs = []
    for folder in sorted(_DESIGNS.iterdir()):
        if not (_DESIGN.match(folder.name) and (folder / "design.css").is_file()):
            continue
        about = folder / "design.yaml"
        meta = (yaml.safe_load(about.read_text(encoding="utf-8")) or {}) if about.is_file() else {}
        designs.append({"name": folder.name, "title": str(meta.get("title", folder.name)),
                        "about": str(meta.get("about", "")), "order": int(meta.get("order", 1000))})
    return sorted(designs, key=lambda d: (d["order"], d["name"]))


def _story_title() -> str:
    """The configured story's title, for the chooser's heading; a plain one when the story does not load."""
    try:
        return load_story(app_config.get_settings().show.story).title
    except StoryError:
        return "The show"


@page_router.get("/show", response_class=HTMLResponse)
async def show_page(request: Request, design: Optional[str] = None, mock: bool = False):
    """Serve the show page, which opens a run and plays its rounds.

    Without ?design, the chooser (templates/show_choose.html): a card per design, with a live miniature of it, and one
    for the plain page. With ?design=<name> naming a folder of static/show/designs/ that holds a design.css, the page
    in that design (templates/show_design.html: the same elements, the design's files on top; with ?mock=1, a
    recorded stretch of a show fills the page, for looking at a design without running one). With ?design=plain, or
    any other name, the plain page, unchanged; with ?mock=1 as well, the plain look filled with that recorded stretch
    (the chooser's preview of the plain page), served from the design template with no design on top.
    """
    if design is None:
        return _templates.TemplateResponse(request, "show_choose.html", {
            "designs": _designs(), "title": _story_title()})
    if _DESIGN.match(design) and (_DESIGNS / design / "design.css").is_file():
        return _templates.TemplateResponse(request, "show_design.html", {
            "design": design, "design_js": (_DESIGNS / design / "design.js").is_file(), "mock": mock})
    if mock:
        return _templates.TemplateResponse(request, "show_design.html",
                                           {"design": None, "design_js": False, "mock": True})
    return _templates.TemplateResponse(request, "show.html")


@router.post("/start", response_model=ShowStartResponse)
def start(req: ShowStartRequest):
    """Open a new run: load and check the story, render its cast sheet, pick the seed."""
    show = app_config.get_settings().show
    try:
        story = load_story(req.story or show.story)
    except StoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    seed = show.seed if show.seed is not None else random.randrange(1, 2**31)
    run = new_run(story, show, render_cast_sheet(story, show), seed)
    logger.info("Show run %s opened: story %s, seed %s", run.run_id, story.name, seed)
    return ShowStartResponse(run_id=run.run_id, story=story.name, title=story.title,
                             cast=list(story.cast), operator=story.operator, seed=seed,
                             listen_window_s=show.listen_window_s, press_cap_s=show.press_cap_s,
                             debug=show.debug, voices=voice_map(story) if show.mood_voices else {})


def _load(run_id: str) -> Tuple[Run, Story]:
    """The run and its story, or the HTTP error: 404 for an unknown or malformed run id, 422 for a broken story."""
    if not _RUN_ID.match(run_id):
        raise HTTPException(status_code=404, detail=f"Unknown run {run_id!r}")
    try:
        run = load_run(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Unknown run {run_id!r}")
    try:
        return run, load_story(run.story)
    except StoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/listen", response_model=ShowListenResponse)
async def listen(req: ShowListenRequest):
    """Transcribe what a listener said after an invitation, with the cast's names as Whisper's hint."""
    settings = app_config.get_settings()
    if not settings.stt.is_active:
        return JSONResponse(status_code=503, content={"detail": "STT is disabled in settings"})
    run, story = _load(req.run_id)
    try:
        audio_bytes = base64.b64decode(req.audio_base64)
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Invalid audio data"})
    heard = await transcribe_for_show(audio_bytes, req.audio_mime_type or "audio/webm",
                                      prompt=", ".join(story.cast), language=settings.show.stt_language)
    if heard is None:
        return JSONResponse(status_code=502, content={"detail": "Unable to process STT data"})
    return ShowListenResponse(**heard)


@router.post("/round")
async def play_round(req: ShowRoundRequest):
    """Play the run's next round and return an SSE stream of its lines."""
    run, story = _load(req.run_id)
    return StreamingResponse(
        _round_stream(run, story, req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _round_stream(run: Run, story: Story, req: ShowRoundRequest) -> AsyncIterator[str]:
    show = app_config.get_settings().show
    n = len(run.rounds) + 1
    heard, words = None, None
    if req.transcript is not None:
        if run.rounds and run.rounds[-1].kind in LISTENS:
            words, silence = usable(req.transcript, req.no_speech_prob, req.avg_logprob, show)
            heard = Heard(text=req.transcript, no_speech_prob=req.no_speech_prob, avg_logprob=req.avg_logprob,
                          silence=silence)
            if silence:
                logger.info("Show run %s, round %s: the listener's %r counts as silence: %s",
                            run.run_id, n, req.transcript, silence)
        else:
            logger.warning("Show run %s, round %s: a transcript arrived outside a listening window; ignored",
                           run.run_id, n)
    size_before = script_size(run)
    trimmed = trim(run, show.context_budget)
    flagged = set(trimmed)
    trimmed_tokens = sum(r.tokens or 0 for r in run.rounds if r.n in flagged)
    if trimmed:
        logger.info("Show run %s, round %s: script at %s tokens (budget %s); trimmed rounds %s, about %s tokens",
                    run.run_id, n, size_before, show.context_budget, trimmed, trimmed_tokens)
    plan = plan_round(run, story, show, req.played_s, words)
    messages = assemble_messages(run, plan.instruction)
    request = {"grammar": plan.grammar, "max_tokens": show.max_tokens, "seed": run.seed + n}
    parser = LineParser(run.moods)
    counted = {"lines": 0}
    fixed_at = set()
    final: dict = {}
    pieces = []

    def feed(piece: str, fixed: bool = False) -> list:
        """Feed the parser the model's tokens, or a fixed line whole; the SSE events it gives, fixed ones marked."""
        known = len(parser.lines)
        events = []
        for event in parser.feed(piece):
            if event["type"] == "start":
                counted["lines"] += 1
            if event["type"] in ("start", "done"):
                event["message_id"] = f"{run.run_id}-r{n:03d}-l{counted['lines']}"
                if fixed:
                    event["fixed"] = True
            events.append(_sse(event))
        if fixed:
            fixed_at.update(range(known, len(parser.lines)))
        return events

    def said(line) -> str:
        """A fixed line as the model would have written it: the speaker, the mood, the text, the line break."""
        return f"{line.speaker} ({line.mood}): {line.text}\n" if line.mood else f"{line.speaker}: {line.text}\n"

    try:
        for line in plan.before:
            for event in feed(said(line), fixed=True):
                yield event
        if plan.max_lines:
            async for item in stream_round(messages, **request):
                if "token" not in item:
                    final = item
                    continue
                pieces.append(item["token"])
                for event in feed(item["token"]):
                    yield event
    except (asyncio.CancelledError, GeneratorExit):
        logger.info("Show run %s, round %s abandoned by the client; nothing recorded", run.run_id, n)
        raise
    except Exception as exc:
        logger.warning("Show run %s, round %s failed; nothing recorded: %s", run.run_id, n, exc)
        if show.debug:
            await write_round(run.run_id, n, plan.kind, messages, **request, reply="".join(pieces), final=final,
                              heard=heard, error=str(exc))
        yield _sse({"type": "error", "message": str(exc)})
        yield _sse({"type": "complete"})
        return

    parser.finish()
    round_ = Round(
        n=n, kind=plan.kind, played_s=req.played_s, instruction=plan.instruction, listener=plan.listener,
        heard=heard, speakers=list(plan.speakers), max_lines=plan.max_lines, event=plan.event, tone=plan.tone,
        lines=[Line(**dataclasses.asdict(line), fixed=i in fixed_at) for i, line in enumerate(parser.lines)],
        dropped=parser.dropped, timings=final.get("timings"), finish_reason=final.get("finish_reason"),
        tokens=round_share(size_before, trimmed_tokens, final.get("timings")), trims=trimmed,
        overtone=plan.overtone, agenda=plan.agenda, slot=plan.slot, recollects=plan.recollects,
    )
    append_round(run, round_)
    if show.debug:
        # Shielded: the round is recorded now, so its files are written even if the client leaves meanwhile
        await asyncio.shield(write_round(run.run_id, n, plan.kind, messages, **request, reply="".join(pieces),
                                         final=final, heard=heard))
    if parser.dropped:
        logger.warning("Show run %s, round %s dropped %s line(s); finish_reason=%s",
                       run.run_id, n, len(parser.dropped), round_.finish_reason)
    yield _sse({"type": "round", "n": n, "kind": plan.kind, "speakers": list(plan.speakers), "event": plan.event,
                "tone": plan.tone, "heard": heard.model_dump() if heard else None, "trimmed": trimmed,
                "dropped": parser.dropped, "finish_reason": round_.finish_reason, "listens": plan.listens,
                "receiver": plan.receiver_on,
                "overtone": plan.overtone, "agenda": plan.agenda, "slot": plan.slot,
                "answers": list(plan.answers) if plan.answers else None,
                "direction": story.directions.get(plan.kind)})
    yield _sse({"type": "complete"})
