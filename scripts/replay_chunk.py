"""Replay a chunk of the show's voice, kept in debug mode, through the app's /api/tts.

With show.debug on, every chunk the show says is kept in runs/<run-id>/debug/audio/: the audio and a .json of
what made it (app/show/debug.py, write_chunk). This asks the app for the chunk again, the way the page asked: the
same persona, clip and text, and the same seed — the one the page sent, or, when it sent none (show.voice_seed
off), the one the engine said it used. The app builds the engine's request as it did during the show (the seed
fitted into the engine's range, tts.parameters), so the replay differs only if something changed. The answer is
written beside the original as <chunk>.replay-seed<N>.wav, and the replay says whether it is byte-identical to the
kept one: the engine answers the same for a given clip, text and seed, so a difference means something else changed
(the engine, its library, the settings). Run from the repository root while the app is serving, for example:

    python3 scripts/replay_chunk.py runs/2026-09-30T18-51-36/debug/audio/r001-l1-c1-Daniel-ref-fear.json
    python3 scripts/replay_chunk.py runs/2026-09-30T18-51-36/debug/audio/r001-l1-c*.json --seed 42

--seed tries another seed instead. The clip must be the one the chunk was said with: if its file changed since (a
recast), the replay says so and asks nothing. Standard library only.
"""

import argparse
import base64
import hashlib
import io
import json
import sys
import urllib.request
import wave
from pathlib import Path


def seconds(audio):
    try:
        with wave.open(io.BytesIO(audio)) as w:
            return w.getnframes() / w.getframerate()
    except (wave.Error, EOFError):
        return None


def replay(path, base, seed):
    kept = json.loads(path.read_text(encoding="utf-8"))
    clip = Path(kept["clip"])
    if not clip.is_file():
        return f"{path.name}: the clip {clip} is gone"
    if hashlib.sha256(clip.read_bytes()).hexdigest() != kept["clip_sha256"]:
        return f"{path.name}: the clip {clip} changed since the chunk was said (recast?); not replayed"
    for candidate in (seed, kept["seed_asked"], kept["reply"].get("seed")):
        if candidate is not None:
            seed = candidate
            break
    else:
        return f"{path.name}: no seed was sent and the engine said none; give one with --seed"
    body = {"text": kept["text"], "persona_name": kept["persona"], "seed": seed}
    if kept["reference_asked"]:
        body["reference"] = kept["reference_asked"]
    request = urllib.request.Request(f"{base}/api/tts", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as resp:
        reply = json.load(resp)
    if reply.get("reference") != kept["reference_used"]:
        return f"{path.name}: the app spoke with {reply.get('reference')}, not {kept['reference_used']}; not compared"
    audio = base64.b64decode(reply["audio_base64"])
    used = reply.get("seed", seed)
    out = path.with_name(f"{path.stem}.replay-seed{used}.wav")
    out.write_bytes(audio)
    original = path.with_suffix(".wav").read_bytes()
    same = "byte-identical to the kept chunk" if audio == original else "DIFFERENT from the kept chunk"
    return (f"{path.name}: seed {used} (kept: {kept['reply'].get('seed')}), {seconds(audio) or 0:.2f} s "
            f"(kept: {seconds(original) or 0:.2f} s), engine {reply.get('time_used')} s; {same}\n  -> {out}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("chunks", nargs="+", type=Path, help="the chunks' .json files (or their .wav)")
    parser.add_argument("--base", default="http://127.0.0.1:8010", help="the app")
    parser.add_argument("--seed", type=int, help="replay with this seed instead")
    args = parser.parse_args()
    for chunk in args.chunks:
        path = chunk.with_suffix(".json")
        if not path.is_file():
            sys.exit(f"{path}: no such chunk")
        print(replay(path, args.base, args.seed), flush=True)


if __name__ == "__main__":
    main()
