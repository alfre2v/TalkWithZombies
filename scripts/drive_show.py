"""Drive the show without a browser: open a run, play N rounds, print what streams.

Run from the repository root while the app is serving, for example:

    python3 scripts/drive_show.py --base http://127.0.0.1:8010 --rounds 10

--control checks that the grammar binds, without the app and without opening a
run: it takes the cast sheet of an existing run (--run-id, or the newest in
--runs-dir) and sends one request straight to llama.cpp with a grammar that
allows only a speaker absent from it ("Operator"); every line must come back
as Operator's. Only the tunnel is needed:

    python3 scripts/drive_show.py --control

Standard library only.
"""

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

MOODS = ("calm", "happy", "sad", "afraid", "terrified", "doubtful", "angry", "urgent", "exhausted")


def post(url, body, timeout=120):
    request = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(request, timeout=timeout)


def start(base, story):
    with post(f"{base}/api/show/start", {"story": story} if story else {}) as resp:
        return json.load(resp)


def play_round(base, run_id, played_s):
    t0 = time.monotonic()
    first, lines, summary, error, mood = None, 0, None, None, None
    with post(f"{base}/api/show/round", {"run_id": run_id, "played_s": played_s}) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: "):])
            elapsed = time.monotonic() - t0
            if event["type"] == "start":
                mood = event.get("mood")
            elif event["type"] == "done":
                first = first if first is not None else elapsed
                lines += 1
                tag = f" ({mood})" if mood else ""
                print(f"  [{elapsed:5.2f}s] {event['persona']}{tag}: {event['text']}")
            elif event["type"] == "round":
                summary = event
            elif event["type"] == "error":
                error = event["message"]
    return {"seconds": time.monotonic() - t0, "first": first, "lines": lines, "summary": summary, "error": error}


def control(llm, system):
    grammar = "\n".join([
        "root    ::= line{1,2}",
        'line    ::= speaker " (" emotion "): " text "\\n"',
        'speaker ::= "Operator"',
        "emotion ::= " + " | ".join(f'"{m}"' for m in MOODS),
        "text    ::= [^\\n\\[\\]()]+",
    ]) + "\n"
    body = {"model": "default", "stream": False, "max_tokens": 200, "temperature": 0.8, "seed": 42,
            "grammar": grammar,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": "Moira and Ralph speak next: the next two lines, "
                                                     "each with the emotion in its voice."}]}
    with post(f"{llm}/v1/chat/completions", body) as resp:
        text = json.load(resp)["choices"][0]["message"]["content"]
    lines = [line for line in text.split("\n") if line]
    print("control reply:")
    for line in lines:
        print(f"  {line}")
    ok = bool(lines) and all(line.startswith("Operator (") for line in lines)
    print("control:", "PASS — every line is Operator's" if ok else "FAIL")
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--llm", default="http://localhost:8080")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--story")
    parser.add_argument("--played", type=float, default=20.0,
                        help="seconds of audio each round is taken to play; the running total is reported")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--control", action="store_true")
    parser.add_argument("--run-id", help="with --control: the run whose cast sheet to use (default: the newest)")
    args = parser.parse_args()

    if args.control:
        runs = sorted(p.parent for p in Path(args.runs_dir).glob("*/script.json"))
        if not runs:
            print(f"no run in {args.runs_dir}/ to take a cast sheet from")
            return 1
        record = (Path(args.runs_dir) / args.run_id if args.run_id else runs[-1]) / "script.json"
        print(f"control, with the cast sheet of {record}")
        return 0 if control(args.llm, json.loads(record.read_text())["systems"][""]) else 1

    run = start(args.base, args.story)
    record = Path(args.runs_dir) / run["run_id"] / "script.json"
    print(f"run {run['run_id']} — {run['title']} — cast {', '.join(run['cast'])} — seed {run['seed']}")

    results = []
    for i in range(args.rounds):
        result = play_round(args.base, run["run_id"], args.played * i)
        summary = result["summary"] or {}
        results.append(result)
        if result["error"]:
            print(f"round error: {result['error']}")
            return 1
        print(f"round {summary.get('n')} ({summary.get('kind')}): {result['lines']} line(s) of "
              f"{', '.join(summary.get('speakers', []))} · event: {summary.get('event') or '—'}"
              f" · tone: {summary.get('tone') or '—'} · dropped: {len(summary.get('dropped') or [])}"
              f" · finish: {summary.get('finish_reason')} · first line {result['first'] or 0:.2f}s,"
              f" round {result['seconds']:.2f}s")

    rounds = json.loads(record.read_text())["rounds"]
    timings = rounds[-1].get("timings") or {}
    size = sum(timings.get(key, 0) for key in ("prompt_n", "cache_n", "predicted_n"))
    print(f"\n{len(results)} rounds · {sum(r['lines'] for r in results)} lines · "
          f"{sum(len((r['summary'] or {}).get('dropped') or []) for r in results)} dropped · "
          f"average round {sum(r['seconds'] for r in results) / len(results):.2f}s · "
          f"script after the last round: {size} tokens")
    print(f"record: {record}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
