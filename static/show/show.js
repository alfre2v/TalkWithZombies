/**
 * show.js — The show page: open a run, play its rounds one after another,
 * and open the listening window when the director invites the listeners.
 *
 * Each line goes to the voice (player.js) as soon as it is written, and
 * appears on the page when its voice starts; the next round is asked for
 * when the voice has said everything, with the seconds of audio played so
 * far. With ?voice=off the page plays the text only, on the simulated clock
 * of step 3.1: it waits as long as a round's lines would take to say, about
 * 15 characters a second. After an invitation the listening window counts
 * down with the talk button still disabled (the microphone comes in step
 * 3.3), and the next round goes without a transcript: the static round.
 *
 * A classic script sharing globals, like upstream's; sse.js and player.js
 * load first. At load time it only defines functions and wires the page on
 * DOMContentLoaded, so the Node tests can load it without a DOM.
 */

const SPEAKING_CHARS_PER_S = 15;
const CAPTIONS_KEY = "show.captions";
const RUNNING_STATES = ["thinking", "on air", "listening"];
const STATE_TEXT = {
    idle: "Press Start to go on air.",
    thinking: "Thinking…",
    "on air": "On air",
    listening: "Listening…",
    stopped: "Stopped.",
    error: "Error:",
};

const show = {
    run: null,          // the start response: run_id, title, cast, listen_window_s, press_cap_s, debug, ...
    playedS: 0,         // seconds of show audio played so far (simulated with ?voice=off)
    voice: true,        // false with ?voice=off: text only, on the simulated clock
    current: null,      // the round being said, which the played clips count towards
    lastKind: null,     // the kind of the last round that completed
    lastN: 0,           // the number of the last round whose summary arrived
    unsure: [],         // rounds that ended early since then: {note, reason}; the next summary tells if kept
    controller: null,   // aborts the round request or the wait in progress
    state: "idle",
};

/* ==========================================================================
   Pure helpers (tested in tests/test_show_page.js)
   ========================================================================== */

/** How long a text takes to say, at about 15 characters a second: the simulated clock of ?voice=off. */
function speakingSeconds(text) {
    return text.length / SPEAKING_CHARS_PER_S;
}

/**
 * How many of the rounds that ended early the server kept anyway.
 *
 * Each round the server records moves its count on by one, so the kept ones
 * are the rounds between the last summary seen (lastN) and this one (n) —
 * the latest of the early attempts.
 */
function keptAttempts(lastN, n, early) {
    return Math.min(early, Math.max(0, n - lastN - 1));
}

/** Seconds with one decimal, or a dash when unknown. */
function formatSeconds(seconds) {
    return seconds === null || seconds === undefined ? "—" : seconds.toFixed(1);
}

/**
 * The debug line under a round: what the director chose, what was heard,
 * how long the round took to write, and — once it has been said — how long
 * the listener waited for its first sound and how much audio it played.
 */
function debugLine(summary, times, runId) {
    const parts = [
        `round ${summary.n}`,
        summary.kind,
        `speakers ${summary.speakers.join(", ")}`,
        `event ${summary.event || "—"}`,
        `tone ${summary.tone || "—"}`,
    ];
    if (summary.heard) {
        const verdict = summary.heard.silence ? `silence: ${summary.heard.silence}` : "words";
        parts.push(`heard "${summary.heard.text}" (${verdict})`);
    }
    if (summary.trimmed && summary.trimmed.length) parts.push(`trimmed rounds ${summary.trimmed.join(", ")}`);
    if (summary.dropped && summary.dropped.length) parts.push(`dropped ${summary.dropped.length}`);
    parts.push(
        `first line ${formatSeconds(times.firstLineS)} s`,
        `round ${formatSeconds(times.seconds)} s`,
    );
    if (times.firstSoundS !== undefined) parts.push(`first sound ${formatSeconds(times.firstSoundS)} s`);
    if (times.playedS !== undefined) parts.push(`played ${formatSeconds(times.playedS)} s`);
    parts.push(`run ${runId}`);
    return parts.join(" · ");
}

/* ==========================================================================
   The loop
   ========================================================================== */

/** Open a run, then play it. */
async function startShow() {
    if (show.voice) unlockAudio();
    el("btn-start").disabled = true;
    try {
        const resp = await fetch("/api/show/start", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: "{}",
        });
        const body = await resp.json();
        if (!resp.ok) throw new Error(body.detail || `HTTP ${resp.status}`);
        show.run = body;
        show.playedS = 0;
        show.lastKind = null;
        show.lastN = 0;
        show.unsure = [];
        el("show-title").textContent = body.title;
        renderCast(body.cast);
        runShow();
    } catch (err) {
        fail(`the show could not start: ${err.message}`);
    } finally {
        el("btn-start").disabled = false;
    }
}

/**
 * Play rounds one after another until Stop or a failure.
 *
 * After an invitation the listening window comes first, so a Resume after a
 * stop there opens it again.
 */
async function runShow() {
    const controller = new AbortController();
    show.controller = controller;
    try {
        while (true) {
            if (show.lastKind === "invitation") await listenWindow(controller.signal);
            const round = await playRound(controller.signal);
            show.lastKind = round.summary.kind;
            if (show.voice) await playOut(round, controller.signal);
            else await onAir(round, controller.signal);
        }
    } catch (err) {
        if (show.controller !== controller) return; // A Resume has started a newer loop
        stopVoice();
        if (controller.signal.aborted) setState("stopped");
        else fail(err.message);
    }
}

/**
 * Ask for the next round and give each line to the voice as it completes.
 *
 * With the voice, a line appears when its voice starts; with ?voice=off, at
 * once. Resolves with the round's summary, its lines and its timings; throws
 * on an HTTP error, an "error" event, or a stream that ends without its
 * summary. The stage direction goes above the round's lines when the
 * summary brings the event.
 */
async function playRound(signal) {
    setState("thinking");
    lightSpeaker(null);
    const started = performance.now();
    const round = {
        summary: null, lines: [], started, firstLineS: null, seconds: null, element: addRoundElement(),
        firstSoundS: show.voice ? null : undefined, playedS: show.voice ? 0 : undefined, debugElement: null,
    };
    show.current = round;
    let mood = null;
    let error = null;
    try {
        const resp = await fetch("/api/show/round", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ run_id: show.run.run_id, played_s: show.playedS }),
            signal,
        });
        if (!resp.ok || !resp.body) throw new Error(`the round request failed (HTTP ${resp.status})`);
        await readSSE(resp, (event) => {
            if (event.type === "start") {
                mood = event.mood;
            } else if (event.type === "done") {
                if (round.firstLineS === null) round.firstLineS = (performance.now() - started) / 1000;
                round.lines.push(event);
                const line = addLine(round.element, event.persona, mood, event.text, show.voice);
                if (show.voice) {
                    const persona = event.persona;
                    speakLine(persona, event.text, {
                        onStart: () => lineStarts(round, line, persona),
                        onFail: (err) => voiceFailed(round, persona, err),
                    });
                } else {
                    lightSpeaker(event.persona);
                }
            } else if (event.type === "round") {
                round.summary = event;
            } else if (event.type === "error") {
                error = event.message;
            }
        });
        if (error) throw new Error(error);
        if (!round.summary) throw new Error("the round ended without its summary");
    } catch (err) {
        round.element.classList.add("failed");
        const note = addNote(round.element,
            signal.aborted ? "(stopped mid-round)" : `(this round failed: ${err.message})`);
        show.unsure.push({ note, reason: signal.aborted ? "stopped" : "failed" });
        throw err;
    }
    round.seconds = (performance.now() - started) / 1000;
    settleUnsure(round.summary.n);
    addDirection(round.element, round.summary.event);
    if (show.run.debug) {
        const written = { firstLineS: round.firstLineS, seconds: round.seconds }; // The voice's timings come once said
        round.debugElement = addDebugLine(round.element, debugLine(round.summary, written, show.run.run_id));
    }
    return round;
}

/** A line's voice has started: show the line, light its speaker, and say the show is on air. */
function lineStarts(round, line, persona) {
    if (round.firstSoundS === null) round.firstSoundS = (performance.now() - round.started) / 1000;
    line.hidden = false;
    lightSpeaker(persona);
    if (show.state === "thinking") setState("on air");
    scrollToEnd();
}

/** A chunk could not be said: it is skipped, and with debug on the round says so. */
function voiceFailed(round, persona, err) {
    if (show.run.debug) addNote(round.element, `(the voice failed for ${persona}: ${err.message})`);
}

/** Wait until the round has been said; its clips' durations have counted as played. */
async function playOut(round, signal) {
    await drained();
    if (signal.aborted) throw new Error("stopped");
    lightSpeaker(null);
    if (round.debugElement) round.debugElement.textContent = debugLine(round.summary, round, show.run.run_id);
}

/**
 * Correct the notes of the rounds that ended early, now that a summary tells what the server kept.
 *
 * A Stop can land after the server has recorded the round but before its
 * summary reached the page (seen live on 2026-09-25); the model reads that
 * round from then on, though the page never finished showing it.
 */
function settleUnsure(n) {
    const kept = keptAttempts(show.lastN, n, show.unsure.length);
    for (const attempt of show.unsure.slice(show.unsure.length - kept)) {
        attempt.note.textContent = `(${attempt.reason}, but the server kept this round)`;
    }
    show.unsure = [];
    show.lastN = n;
}

/** Simulated playback (step 3.1): wait as long as the round's lines take to say, then count them as played. */
async function onAir(round, signal) {
    const seconds = speakingSeconds(round.lines.map((line) => line.text).join(" "));
    setState("on air");
    await sleep(seconds * 1000, signal);
    show.playedS += seconds;
}

/** The listening window after an invitation: count down listen_window_s; the microphone comes in step 3.3. */
async function listenWindow(signal) {
    for (let left = Math.ceil(show.run.listen_window_s); left > 0; left--) {
        setState("listening", `${left} s`);
        await sleep(1000, signal);
    }
}

/** Stop now: the round in flight is abandoned, the voice is cut, and a wait is cut short. */
function stopShow() {
    if (show.controller) show.controller.abort();
    stopVoice();
    setState("stopped");
}

/** Continue the same run from where it stopped or failed. */
function resumeShow() {
    if (!show.run || RUNNING_STATES.includes(show.state)) return;
    if (show.voice) unlockAudio();
    runShow();
}

/** A clip has been played to its end: its seconds count as played, for the show and for its round. */
function countPlayed(seconds) {
    show.playedS += seconds;
    if (show.current && show.current.playedS !== undefined) show.current.playedS += seconds;
}

/** Stop the show and say why; Resume continues the run, or Start opens one if none opened. */
function fail(message) {
    console.error("Show:", message);
    setState("error", message);
}

/** Wait ms milliseconds; rejects when the signal aborts first. */
function sleep(ms, signal) {
    return new Promise((resolve, reject) => {
        if (signal.aborted) return reject(new Error("stopped"));
        const timer = setTimeout(resolve, ms);
        signal.addEventListener("abort", () => {
            clearTimeout(timer);
            reject(new Error("stopped"));
        }, { once: true });
    });
}

/* ==========================================================================
   The page
   ========================================================================== */

/** The element with this id. */
function el(id) {
    return document.getElementById(id);
}

/** Show a state in the state line, light the ON AIR sign while running, and show the buttons that fit. */
function setState(name, detail) {
    show.state = name;
    el("show-state").textContent = detail ? `${STATE_TEXT[name]} ${detail}` : STATE_TEXT[name];
    el("on-air").classList.toggle("lit", RUNNING_STATES.includes(name));
    el("btn-start").hidden = !(name === "idle" || (name === "error" && !show.run));
    el("btn-stop").hidden = !RUNNING_STATES.includes(name);
    el("btn-resume").hidden = !(show.run && (name === "stopped" || name === "error"));
    el("btn-talk").classList.toggle("window-open", name === "listening");
}

/** The cast strip: one name per cast member. */
function renderCast(cast) {
    const strip = el("cast");
    strip.textContent = "";
    for (const name of cast) {
        const member = document.createElement("span");
        member.className = "cast-member";
        member.dataset.name = name;
        member.textContent = name;
        strip.appendChild(member);
    }
}

/** Light the cast member speaking now; null lights no one. */
function lightSpeaker(name) {
    for (const member of el("cast").children) {
        member.classList.toggle("speaking", member.dataset.name === name);
    }
}

/** A new block in the script for the round about to play. */
function addRoundElement() {
    const block = document.createElement("div");
    block.className = "round";
    el("script").appendChild(block);
    return block;
}

/** A line of the script: the speaker, the mood, the spoken text; hidden until its voice starts, if asked. */
function addLine(block, speaker, mood, text, hidden) {
    const line = document.createElement("p");
    line.className = "line";
    line.hidden = Boolean(hidden);
    const who = document.createElement("span");
    who.className = "speaker";
    who.textContent = speaker;
    line.appendChild(who);
    if (mood) {
        const how = document.createElement("span");
        how.className = "mood";
        how.textContent = ` (${mood})`;
        line.appendChild(how);
    }
    line.appendChild(document.createTextNode(`: ${text}`));
    block.appendChild(line);
    scrollToEnd();
    return line;
}

/** The round's event as a stage direction, above its lines; captions off hide it with them. */
function addDirection(block, event) {
    if (!event) return;
    const direction = document.createElement("p");
    direction.className = "direction";
    direction.textContent = `[${event}]`;
    block.prepend(direction);
}

/** The debug line under a round (only while show.debug is on); returns it, to be completed once said. */
function addDebugLine(block, text) {
    const line = document.createElement("p");
    line.className = "debug";
    line.textContent = text;
    block.appendChild(line);
    scrollToEnd();
    return line;
}

/** A note under a round that stopped or failed; returns it, to be corrected if the server kept the round. */
function addNote(block, text) {
    const note = document.createElement("p");
    note.className = "note";
    note.textContent = text;
    block.appendChild(note);
    scrollToEnd();
    return note;
}

/** Keep the newest line in view. */
function scrollToEnd() {
    const script = el("script");
    script.scrollTop = script.scrollHeight;
}

/** Show or hide the captions: the lines and the stage directions. */
function applyCaptions(on) {
    document.body.classList.toggle("captions-off", !on);
    el("btn-captions").textContent = on ? "Captions: on" : "Captions: off";
    el("btn-captions").setAttribute("aria-pressed", String(on));
}

/** Flip the captions and remember the choice in this browser. */
function toggleCaptions() {
    const on = document.body.classList.contains("captions-off");
    applyCaptions(on);
    try {
        localStorage.setItem(CAPTIONS_KEY, on ? "on" : "off");
    } catch (e) {
        // Storage blocked: the choice lasts until the page reloads
    }
}

/** The remembered captions choice; on unless turned off before. */
function savedCaptions() {
    try {
        return localStorage.getItem(CAPTIONS_KEY) !== "off";
    } catch (e) {
        return true;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    show.voice = new URLSearchParams(location.search).get("voice") !== "off";
    voice.onPlayed = countPlayed;
    applyCaptions(savedCaptions());
    el("btn-start").addEventListener("click", startShow);
    el("btn-stop").addEventListener("click", stopShow);
    el("btn-resume").addEventListener("click", resumeShow);
    el("btn-captions").addEventListener("click", toggleCaptions);
    setState("idle");
});
