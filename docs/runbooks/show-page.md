# Runbook: play the show in the browser

*Living, undated. Written 2026-09-25 with step 3.1 of the show engine's
slice 3, the page with text only; it grows with the voice (3.2) and
the listener's turn (3.3). The page is `GET /show`
(`templates/show.html`, with its own files in `static/show/`). The
plan it follows lives in the companion repository,
[alfre2v/zombie-radio](https://github.com/alfre2v/zombie-radio)
(`docs/discussions/2026-09-25-show-slice-3-browser-plan.md`); to play
rounds without a browser, see [show-driver.md](show-driver.md).*

All commands run from this repository's root,
`/Users/alfredo/workspace/hackTNT_2026/TalkWithZombies`.

## What you need

The same as for the driver ([show-driver.md](show-driver.md), "What
you need"): the model services and the SSH tunnel, the app's
dependencies in `.venv`, and a `settings.yaml` pointing at the
tunnel's ports and at a personas folder with a reference voice for
every cast member.

## Open the page

Start the app (it serves the page too):

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010
```

Then open <http://127.0.0.1:8010/show> and press **Start**. The page
opens a run, puts the story's title and cast at the top, and plays
rounds one after another until you press **Stop**.

## What you see

- **The header:** the story's title, the cast strip (the speaker of
  the newest line is lit), the **ON AIR** sign (lit while the show
  runs), and under it the **Captions** toggle.
- **The script:** one block per round — the event, when the round has
  one, as a stage direction in brackets, then the lines (speaker, mood,
  spoken text). The stage direction appears above the round's lines
  when the round's summary arrives, a moment after the lines.
- **The bottom bar:** Start / Stop / Resume, the state (Thinking…,
  On air, Listening… N s, Stopped, Error), and the **Hold to talk**
  button.
- **Captions** hide or show the lines and the stage directions
  together; the choice is remembered by this browser. The lines keep
  being added while hidden.

## For now: text only, on a simulated clock (step 3.1)

- **No voices yet.** After each round the page waits as long as its
  lines would take to say — about 15 characters a second — and reports
  that as played seconds with the next round, so the director's
  cadence runs as it will with voices.
- **The listening window.** After an invitation the state shows
  "Listening… N s" for `show.listen_window_s` seconds (10 by default);
  the talk button stays disabled (the microphone comes in step 3.3),
  so the next round is the static one.

## The debug line

With `debug: true` under `show:` in `settings.yaml` (restart the app),
each round gets a small line under it: the round's number and kind,
the allowed speakers, the event, the tone word, what was heard, the
trimmed and dropped rounds, the seconds to the first line and to the
round's end, and the run id — the run's record is
`runs/<run-id>/script.json`. The debug files of the driver's runbook
are written too.

## Stop, Resume, and a reload

- **Stop** abandons the round in flight (the server records nothing for
  it; the page marks it "stopped mid-round") and cuts a wait short. A
  Stop can land just after the server recorded the round, before its
  summary reached the page: after Resume, the next round's number tells,
  and the note becomes "stopped, but the server kept this round" — the
  model reads that round from then on. (Seen once, 2026-09-25, on a
  double Stop; the round's debug files are written either way.)
- **Resume** continues the same run: the next round is the one that was
  stopped or failed; after an invitation, the listening window opens
  first.
- **A reload** starts over: Start opens a new run. The old run's record
  stays in `runs/`.

## When something looks wrong

- **"Error: the show could not start: …"** — the app could not open a
  run: a persona without a reference voice (the message names it), or
  a story that does not load. Fix it and press Start again.
- **"Error: the round request failed …" or a failed round** — the model
  did not answer: check the tunnel (`curl localhost:8080/health` must
  say `{"status":"ok"}`), then press **Resume**; the failed round is
  asked for again.
- **Nothing happens on Start** — the app is not serving, or the browser
  console (Developer Tools) shows why.
