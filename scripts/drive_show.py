"""Drive the show without a browser: open a run, play N rounds, print what streams.

Run from the repository root while the app is serving, for example:

    python3 scripts/drive_show.py --base http://127.0.0.1:8010 --rounds 10

The listener: after each invitation, the next --heard item answers, in turn
("-" is a silent window). By default the words go into the next round request
as text; with --speak they go the real way: the app's TTS speaks them in the
operator's voice and /api/show/listen transcribes them (a silent window sends
two seconds of silence). Without --heard, or once the items run out, nothing
is sent and the window counts as silence.

--report judges the drive against the checkpoint's criteria, from the run's
record and its debug folder (show.debug on), and prints PASS or FAIL for each:

    python3 scripts/drive_show.py --rounds 20 --heard "Moira, is it airborne?" --heard - --report

--control checks that the grammar binds, without the app and without opening a
run: it takes the cast sheet of an existing run (--run-id, or the newest in
--runs-dir) and sends one request straight to llama.cpp with a grammar that
allows only a speaker absent from it ("Operator"); every line must come back
as Operator's. Only the tunnel is needed:

    python3 scripts/drive_show.py --control

Standard library only.
"""

import argparse
import base64
import io
import json
import re
import sys
import time
import urllib.request
import wave
from pathlib import Path

MOODS = ("calm", "happy", "sad", "afraid", "terrified", "doubtful", "angry", "urgent", "exhausted")


def post(url, body, timeout=120):
    request = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(request, timeout=timeout)


def start(base, story):
    with post(f"{base}/api/show/start", {"story": story} if story else {}) as resp:
        return json.load(resp)


def play_round(base, run_id, played_s, heard=None):
    t0 = time.monotonic()
    first, lines, summary, error, mood = None, 0, None, None, None
    with post(f"{base}/api/show/round", {"run_id": run_id, "played_s": played_s, **(heard or {})}) as resp:
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


def silence_wav(seconds=2.0, rate=24000):
    """A WAV of silence: what a window where nobody speaks records."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


def listener_says(base, run, item, speak):
    """The next round request's listener fields for one --heard item: the words as text, or spoken and transcribed."""
    words = "" if item == "-" else item
    if not speak:
        return {"transcript": words}
    t0 = time.monotonic()
    if words:
        with post(f"{base}/api/tts", {"text": words, "persona_name": run["operator"]}) as resp:
            audio = base64.b64decode(json.load(resp)["audio_base64"])
    else:
        audio = silence_wav()
    t1 = time.monotonic()
    body = {"run_id": run["run_id"], "audio_base64": base64.b64encode(audio).decode(), "audio_mime_type": "audio/wav"}
    with post(f"{base}/api/show/listen", body) as resp:
        heard = json.load(resp)
    said = f'"{words}" in {run["operator"]}\'s voice ({t1 - t0:.2f}s)' if words else "nothing (2 s of silence)"
    numbers = ", ".join(f"{key} {heard[key]:.3f}" for key in ("no_speech_prob", "avg_logprob")
                        if heard[key] is not None)
    print(f'  the listener says {said}; Whisper heard "{heard["text"]}"' + (f" ({numbers})" if numbers else "")
          + f" in {time.monotonic() - t1:.2f}s")
    return {"transcript": heard["text"], "no_speech_prob": heard["no_speech_prob"],
            "avg_logprob": heard["avg_logprob"]}


def heard_line(summary):
    """What the listening window came to, printed after the round that follows an invitation; None otherwise."""
    heard = summary.get("heard")
    if summary.get("kind") == "answer":
        return f'  listener: "{heard["text"]}"'
    if summary.get("kind") == "static":
        return f'  heard: "{heard["text"]}" -> silence: {heard["silence"]}' if heard else "  heard: nothing sent"
    return None


def report(runs_dir, run_id, asked):
    """Judge a drive against the checkpoint's criteria from its record and debug folder; True when all pass."""
    folder = Path(runs_dir) / run_id
    rounds = json.loads((folder / "script.json").read_text())["rounds"]
    checks = [(len(rounds) == asked and asked >= 10,
               f"{len(rounds)} of {asked} rounds played and recorded (10 needed)")]

    strays = [f"round {r['n']}: {line['speaker']} not allowed" for r in rounds for line in r["lines"]
              if line["speaker"] not in r["speakers"]]
    over = [f"round {r['n']}: {len(r['lines'])} lines of {r['max_lines']}" for r in rounds
            if len(r["lines"]) > r["max_lines"]]
    empty = [f"round {r['n']}: no line" for r in rounds if not r["lines"]]
    faults = strays + over + empty
    checks.append((not faults, f"speakers and line counts obey the director: {sum(len(r['lines']) for r in rounds)} "
                               f"lines, {sum(len(r['dropped']) for r in rounds)} dropped"
                               + (f"; {'; '.join(faults)}" if faults else "")))

    answers = [r for r in rounds if r["kind"] == "answer" and r["lines"]]
    checks.append((bool(answers), "an invitation answered from the listener's words: " + (
        "; ".join(f'round {r["n"]} heard "{r["listener"]}" -> '
                  f'{", ".join(dict.fromkeys(line["speaker"] for line in r["lines"]))}' for r in answers)
        or "none (give --heard with words)")))

    statics = [r for r in rounds if r["kind"] == "static" and r["lines"]]
    checks.append((bool(statics), "a silent window gave the static round: " + (
        "; ".join(f'round {r["n"]} ({r["heard"]["silence"] if r["heard"] else "nothing sent"})' for r in statics)
        or "none")))

    trims = [r for r in rounds if r["trims"]]
    checks.append((bool(trims), "the trim fired: " + (
        "; ".join(f"before round {r['n']} (rounds {', '.join(map(str, r['trims']))})" for r in trims)
        or "no (set show.context_budget to 1500 and drive 20 rounds)")))

    debug = folder / "debug"
    missing, off = [], []
    for r in rounds:
        text_file = debug / f"r{r['n']:03d}.txt"
        if not (text_file.exists() and (debug / f"r{r['n']:03d}.request.json").exists()):
            missing.append(r["n"])
            continue
        found = re.search(r"^token check: .*difference (-?\d+)$", text_file.read_text(encoding="utf-8"), re.M)
        if not (found and found.group(1) == "0"):
            off.append(r["n"])
    with_files = len(rounds) - len(missing)
    checks.append((bool(rounds) and not missing and not off,
                   f"debug files for {with_files} of {len(rounds)} rounds; token check difference 0 in "
                   f"{with_files - len(off)} of them"
                   + (f"; missing: rounds {', '.join(map(str, missing))}" if missing else "")
                   + (f"; not 0 or not available: rounds {', '.join(map(str, off))}" if off else "")
                   + (" (is show.debug on?)" if not debug.exists() else "")))

    print(f"checkpoint report, run {run_id}:")
    for ok, text in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {text}")
    passed = sum(ok for ok, _ in checks)
    print(f"{passed} of {len(checks)} criteria pass")
    return passed == len(checks)


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
    parser.add_argument("--heard", action="append", default=[], metavar="WORDS",
                        help='what the listener says at the next invitation, one per invitation; "-" is silence')
    parser.add_argument("--speak", action="store_true",
                        help="send each --heard item the real way: spoken by the app's TTS, heard by Whisper")
    parser.add_argument("--report", action="store_true",
                        help="after the drive, judge it against the checkpoint's criteria")
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

    results, windows, failed = [], list(args.heard), False
    for i in range(args.rounds):
        heard = None
        if results and (results[-1]["summary"] or {}).get("kind") == "invitation" and windows:
            heard = listener_says(args.base, run, windows.pop(0), args.speak)
        result = play_round(args.base, run["run_id"], args.played * i, heard)
        summary = result["summary"] or {}
        results.append(result)
        if result["error"]:
            print(f"round error: {result['error']}")
            failed = True
            break
        print(f"round {summary.get('n')} ({summary.get('kind')}): {result['lines']} line(s) of "
              f"{', '.join(summary.get('speakers', []))} · event: {summary.get('event') or '—'}"
              f" · tone: {summary.get('tone') or '—'} · dropped: {len(summary.get('dropped') or [])}"
              f" · finish: {summary.get('finish_reason')} · first line {result['first'] or 0:.2f}s,"
              f" round {result['seconds']:.2f}s")
        if heard_line(summary):
            print(heard_line(summary))
        if summary.get("trimmed"):
            print(f"  trimmed before this round: rounds {', '.join(map(str, summary['trimmed']))}"
                  " (the model no longer reads them)")

    if not failed:
        rounds = json.loads(record.read_text())["rounds"]
        timings = rounds[-1].get("timings") or {}
        size = sum(timings.get(key, 0) for key in ("prompt_n", "cache_n", "predicted_n"))
        print(f"\n{len(results)} rounds · {sum(r['lines'] for r in results)} lines · "
              f"{sum(len((r['summary'] or {}).get('dropped') or []) for r in results)} dropped · "
              f"average round {sum(r['seconds'] for r in results) / len(results):.2f}s · "
              f"script after the last round: {size} tokens")
        print(f"record: {record}")
        if windows:
            print(f"{len(windows)} --heard item(s) unused: the drive had fewer invitations")
    if args.report:
        print()
        failed = not report(args.runs_dir, run["run_id"], args.rounds) or failed
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
