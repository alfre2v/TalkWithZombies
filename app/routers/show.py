"""Show router — open a run, then play its rounds.

POST /api/show/start opens a run of a story. POST /api/show/round plays
the run's next round and streams the chat's SSE events (start / token /
done) for each script line, then a "round" summary and "complete". The
server keeps no show state between requests: the caller sends the run id,
and the run is loaded from its record.
"""

import asyncio
import dataclasses
import json
import logging
import random
import re
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app import config as app_config
from app.models import ShowRoundRequest, ShowStartRequest, ShowStartResponse
from app.services.llm import stream_round
from app.show.director import plan_round
from app.show.parser import LineParser
from app.show.script import Line, Round, Run, append_round, assemble_messages, load_run, new_run
from app.show.story import Story, StoryError, load_story, render_cast_sheet

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/show", tags=["show"])

_RUN_ID = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(-\d+)?$")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


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
                             cast=list(story.cast), operator=story.operator, seed=seed)


@router.post("/round")
async def play_round(req: ShowRoundRequest):
    """Play the run's next round and return an SSE stream of its lines."""
    if not _RUN_ID.match(req.run_id):
        raise HTTPException(status_code=404, detail=f"Unknown run {req.run_id!r}")
    try:
        run = load_run(req.run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Unknown run {req.run_id!r}")
    try:
        story = load_story(run.story)
    except StoryError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return StreamingResponse(
        _round_stream(run, story),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _round_stream(run: Run, story: Story) -> AsyncIterator[str]:
    show = app_config.get_settings().show
    n = len(run.rounds) + 1
    plan = plan_round(run, story, run.moods)
    parser = LineParser(run.moods)
    line_no = 0
    final: dict = {}
    try:
        async for item in stream_round(assemble_messages(run, plan.instruction), grammar=plan.grammar,
                                       max_tokens=show.max_tokens, seed=run.seed + n):
            if "token" not in item:
                final = item
                continue
            for event in parser.feed(item["token"]):
                if event["type"] == "start":
                    line_no += 1
                if event["type"] in ("start", "done"):
                    event["message_id"] = f"{run.run_id}-r{n:03d}-l{line_no}"
                yield _sse(event)
    except (asyncio.CancelledError, GeneratorExit):
        logger.info("Show run %s, round %s abandoned by the client; nothing recorded", run.run_id, n)
        raise
    except Exception as exc:
        logger.warning("Show run %s, round %s failed; nothing recorded: %s", run.run_id, n, exc)
        yield _sse({"type": "error", "message": str(exc)})
        yield _sse({"type": "complete"})
        return

    parser.finish()
    round_ = Round(
        n=n, instruction=plan.instruction, speakers=list(plan.speakers), max_lines=plan.max_lines,
        event=plan.event, lines=[Line(**dataclasses.asdict(line)) for line in parser.lines],
        dropped=parser.dropped, timings=final.get("timings"), finish_reason=final.get("finish_reason"),
    )
    append_round(run, round_)
    if parser.dropped:
        logger.warning("Show run %s, round %s dropped %s line(s); finish_reason=%s",
                       run.run_id, n, len(parser.dropped), round_.finish_reason)
    yield _sse({"type": "round", "n": n, "speakers": list(plan.speakers), "event": plan.event,
                "dropped": parser.dropped, "finish_reason": round_.finish_reason})
    yield _sse({"type": "complete"})
