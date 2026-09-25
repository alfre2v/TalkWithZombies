/**
 * test_show_page.js — Tests for the show page's scripts
 * (static/show/sse.js, player.js and show.js).
 *
 * Run with plain Node (Node 20+, no npm packages, no network):
 *
 *     node tests/test_show_page.js
 *
 * What it locks in:
 *   - the stream splitter: whole "data: " lines become events, a line split
 *     across network chunks waits for its end, other lines and data that is
 *     not JSON are skipped;
 *   - the reading loop over a response body, chunk by chunk;
 *   - the simulated clock of ?voice=off (about 15 characters a second);
 *   - the debug line under a round;
 *   - which rounds that ended early the server kept anyway (a Stop that
 *     lands after the round was recorded);
 *   - the accumulator's packing rules (ruled 2026-09-22): whole sentences
 *     up to 100 characters, a short one riding along up to 120, a long one
 *     alone, never across lines;
 *   - the voice queue, with fetch and AudioContext stubbed: chunks played in
 *     order, a line's start once at its first clip, the played seconds, the
 *     drain, a stop that cuts the voice, a failed chunk skipped.
 *
 * How it works: the show's scripts are browser globals (classic scripts,
 * like upstream's), so each test evaluates sse.js + player.js + show.js in a
 * fresh vm.Context — the technique of test_tts_settings.js — and calls their
 * functions. show.js only defines functions and registers its page wiring
 * at load time, so a document stub that takes the listener is all the DOM
 * it needs; the voice gets stubs for fetch and the AudioContext. The page
 * itself is checked by hand and by ear (docs/runbooks/show-page.md).
 *
 * NOTE: this file is intentionally NOT part of the pytest suite (which
 * must run with nothing but Python installed). Run it alongside:
 *     python3 -m pytest
 *     node tests/test_show_page.js
 */

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const SHOW_DIR = path.join(__dirname, "..", "static", "show");
const SHOW_SCRIPTS = ["sse.js", "player.js", "show.js"];

/** A fresh context with the show's scripts loaded; warnings are collected instead of printed. */
function loadShow(extra = {}) {
    const warnings = [];
    const sandbox = {
        console: { log: console.log, error: console.error, warn: (...args) => warnings.push(args) },
        document: { addEventListener: () => {} },
        TextDecoder,
        setTimeout,
        AbortController,
        atob,
        ...extra,
    };
    vm.createContext(sandbox);
    for (const file of SHOW_SCRIPTS) {
        const code = fs.readFileSync(path.join(SHOW_DIR, file), "utf8");
        vm.runInContext(code, sandbox, { filename: file });
    }
    return { sandbox, warnings };
}

/** A value made in the sandbox, as plain data (objects from another context have other prototypes). */
function plain(value) {
    return JSON.parse(JSON.stringify(value));
}

/** A fetch response whose body yields these text chunks, as a network would. */
function responseOf(chunks) {
    const encoder = new TextEncoder();
    const queue = chunks.map((chunk) => encoder.encode(chunk));
    return {
        body: {
            getReader: () => ({
                read: async () => (queue.length ? { done: false, value: queue.shift() } : { done: true }),
            }),
        },
    };
}

const DONE = 'data: {"type": "done", "persona": "Moira", "text": "Over."}';
const COMPLETE = 'data: {"type": "complete"}';

/* ==========================================================================
   The stream splitter
   ========================================================================== */

test("splitSSE: whole data lines become events, in order", () => {
    const { sandbox } = loadShow();

    const { events, rest } = sandbox.splitSSE(`${DONE}\n\n${COMPLETE}\n\n`);

    assert.deepEqual(plain(events), [{ type: "done", persona: "Moira", text: "Over." }, { type: "complete" }]);
    assert.equal(rest, "");
});

test("splitSSE: an unfinished line waits for the next chunk", () => {
    const { sandbox } = loadShow();

    const first = sandbox.splitSSE(`${DONE}\n\n${COMPLETE.slice(0, 12)}`);
    const second = sandbox.splitSSE(first.rest + `${COMPLETE.slice(12)}\n\n`);

    assert.deepEqual(plain(first.events), [{ type: "done", persona: "Moira", text: "Over." }]);
    assert.equal(first.rest, COMPLETE.slice(0, 12));
    assert.deepEqual(plain(second.events), [{ type: "complete" }]);
});

test("splitSSE: other lines are skipped, and data that is not JSON is skipped with a warning", () => {
    const { sandbox, warnings } = loadShow();

    const { events } = sandbox.splitSSE(`: keep-alive\nevent: x\ndata: \ndata: {not json\n${COMPLETE}\n\n`);

    assert.deepEqual(plain(events), [{ type: "complete" }]);
    assert.equal(warnings.length, 1);
    assert.match(String(warnings[0][0]), /Failed to parse SSE event/);
});

test("readSSE: events arrive as their lines complete, whatever the chunk boundaries", async () => {
    const { sandbox } = loadShow();
    const whole = `${DONE}\n\n${COMPLETE}\n\n`;
    const received = [];

    await sandbox.readSSE(responseOf([whole.slice(0, 7), whole.slice(7, 70), whole.slice(70)]), (event) =>
        received.push(plain(event)),
    );

    assert.deepEqual(received, [{ type: "done", persona: "Moira", text: "Over." }, { type: "complete" }]);
});

/* ==========================================================================
   The simulated clock
   ========================================================================== */

test("speakingSeconds: about 15 characters a second", () => {
    const { sandbox } = loadShow();

    assert.equal(sandbox.speakingSeconds("x".repeat(30)), 2);
    assert.equal(sandbox.speakingSeconds(""), 0);
});

/* ==========================================================================
   The debug line
   ========================================================================== */

test("debugLine: a free round with its event, tone, trim and timings", () => {
    const { sandbox } = loadShow();
    const summary = {
        n: 14, kind: "free", speakers: ["Moira", "Ralph"], event: "A pipe bursts.", tone: "wry",
        heard: null, trimmed: [3, 4, 5], dropped: [],
    };

    const line = sandbox.debugLine(summary, { firstLineS: 0.83, seconds: 1.87 }, "2026-09-25T20-00-00");

    assert.equal(line, "round 14 · free · speakers Moira, Ralph · event A pipe bursts. · tone wry"
        + " · trimmed rounds 3, 4, 5 · first line 0.8 s · round 1.9 s · run 2026-09-25T20-00-00");
});

test("debugLine: an invitation without event or tone; what was heard, words or silence", () => {
    const { sandbox } = loadShow();
    const base = { n: 8, kind: "invitation", speakers: ["Samantha"], event: null, tone: null, trimmed: [],
        dropped: ["Samantha (calm): cut"] };
    const times = { firstLineS: null, seconds: 1.2 };

    assert.equal(sandbox.debugLine({ ...base, heard: null }, times, "r"),
        "round 8 · invitation · speakers Samantha · event — · tone — · dropped 1 · first line — s"
        + " · round 1.2 s · run r");
    assert.match(sandbox.debugLine({ ...base, heard: { text: "", silence: "nothing heard" } }, times, "r"),
        / · heard "" \(silence: nothing heard\) · /);
    assert.match(sandbox.debugLine({ ...base, heard: { text: "Moira?", silence: null } }, times, "r"),
        / · heard "Moira\?" \(words\) · /);
});

/* ==========================================================================
   Rounds that ended early
   ========================================================================== */

test("keptAttempts: the rounds between the last summary seen and this one were kept, the latest attempts", () => {
    const { sandbox } = loadShow();

    // Seen live on 2026-09-25: round 44 stopped twice; the second Stop came after the server recorded it.
    assert.equal(sandbox.keptAttempts(43, 45, 2), 1);
    assert.equal(sandbox.keptAttempts(43, 44, 1), 0); // stopped in time: the next summary is round 44 itself
    assert.equal(sandbox.keptAttempts(43, 46, 2), 2);
    assert.equal(sandbox.keptAttempts(0, 1, 0), 0);
    assert.equal(sandbox.keptAttempts(43, 47, 1), 1); // never more than the rounds that ended early
});

/* ==========================================================================
   The accumulator
   ========================================================================== */

/** A sentence of exactly `length` characters, ending with a period. */
function sentence(length, letter = "x") {
    return letter.repeat(length - 1) + ".";
}

test("chunks: short sentences are packed into one chunk", () => {
    const { sandbox } = loadShow();

    assert.deepEqual(plain(sandbox.chunks("Testing. 1. 2. 3. Over.")), ["Testing. 1. 2. 3. Over."]);
    assert.deepEqual(plain(sandbox.chunks("Could this be... a distraction? Over.")),
        ["Could this be... a distraction? Over."]);
});

test("chunks: a sentence longer than 100 goes whole and alone; what follows starts a new chunk", () => {
    const { sandbox } = loadShow();
    const long = sentence(180);

    assert.deepEqual(plain(sandbox.chunks(long)), [long]);
    assert.deepEqual(plain(sandbox.chunks(`${long} Over.`)), [long, "Over."]);
});

test("chunks: two sentences that do not fit in 100 go apart", () => {
    const { sandbox } = loadShow();
    const a = sentence(60, "a");
    const b = sentence(60, "b");

    assert.deepEqual(plain(sandbox.chunks(`${a} ${b}`)), [a, b]);
});

test("chunks: a sentence under 30 rides along up to 120, a longer one does not", () => {
    const { sandbox } = loadShow();
    const s98 = sentence(98);

    assert.deepEqual(plain(sandbox.chunks(`${s98} Over.`)), [`${s98} Over.`]);
    const s40 = sentence(40, "z");
    assert.deepEqual(plain(sandbox.chunks(`${s98} ${s40}`)), [s98, s40]);
});

test("sentencesOf: a sentence ends where marks meet whitespace or the end; numbers stay whole", () => {
    const { sandbox } = loadShow();

    assert.deepEqual(plain(sandbox.sentencesOf("Take 3.5 milligrams. Over.")), ["Take 3.5 milligrams.", "Over."]);
    assert.deepEqual(plain(sandbox.sentencesOf("Ask the U.S. team, e.g. Moira.")),
        ["Ask the U.S.", "team, e.g.", "Moira."]);
    assert.deepEqual(plain(sandbox.sentencesOf("What??? They are here!!! ... Let's go")),
        ["What???", "They are here!!!", "...", "Let's go"]);
    assert.deepEqual(plain(sandbox.sentencesOf("They're here… run.")), ["They're here…", "run."]);
});

test("chunks: the voice gets the text as written — never \"3. 5\" for \"3.5\"", () => {
    const { sandbox } = loadShow();

    for (const text of ["Take 3.5 milligrams. Over.", "Ask the U.S. team, e.g. Moira. Over.",
        "What??? They are here!!! ... Let's go"]) {
        assert.deepEqual(plain(sandbox.chunks(text)), [text]);
    }
});

test("chunks: an unfinished tail is a sentence; an empty line says nothing", () => {
    const { sandbox } = loadShow();

    assert.deepEqual(plain(sandbox.chunks("We need to move. Now")), ["We need to move. Now"]);
    assert.deepEqual(plain(sandbox.chunks("")), []);
});

/* ==========================================================================
   The voice queue
   ========================================================================== */

/**
 * The show's scripts with a stubbed voice: /api/tts answers with the chunk's
 * text as its "audio" (failing for the texts in `failing`), a clip lasts one
 * second per 10 characters, and clips end by themselves unless `manual`,
 * when the test ends them with endClip().
 */
function voiceHarness({ failing = [], manual = false } = {}) {
    const log = [];
    const live = [];
    const fetchStub = async (url, options) => {
        const { text } = JSON.parse(options.body);
        if (failing.includes(text)) return { ok: false, status: 502, json: async () => ({}) };
        return { ok: true, json: async () => ({ audio_base64: Buffer.from(text).toString("base64") }) };
    };
    class AudioContextStub {
        constructor() {
            this.state = "running";
            this.destination = {};
        }
        async decodeAudioData(buffer) {
            const text = new TextDecoder().decode(new Uint8Array(buffer));
            return { duration: text.length / 10, text };
        }
        createBufferSource() {
            const source = {
                connect() {},
                start() {
                    log.push(`play ${source.buffer.text}`);
                    if (manual) live.push(source);
                    else setTimeout(() => source.onended(), 0);
                },
                stop() {
                    setTimeout(() => source.onended(), 0);
                },
            };
            return source;
        }
    }
    const { sandbox, warnings } = loadShow({ fetch: fetchStub, AudioContext: AudioContextStub });
    vm.runInContext("VOICE.pauseInLineMs = 0; VOICE.pauseBetweenLinesMs = 0;", sandbox);
    sandbox.recordPlayed = (seconds) => log.push(`played ${seconds}`);
    vm.runInContext("voice.onPlayed = recordPlayed;", sandbox);
    sandbox.unlockAudio();
    const hooks = (name) => ({
        onStart: () => log.push(`start ${name}`),
        onFail: (err) => log.push(`fail ${name}: ${err.message}`),
    });
    const endClip = () => live.shift().onended();
    const until = async (predicate) => {
        for (let i = 0; i < 200 && !predicate(); i++) await new Promise((resolve) => setTimeout(resolve, 1));
    };
    return { sandbox, log, hooks, endClip, until, warnings };
}

test("the voice: chunks play in order, a line starts once at its first clip, the drain waits for all", async () => {
    const { sandbox, log, hooks } = voiceHarness();
    const a = sentence(60, "a");
    const b = sentence(60, "b");

    sandbox.speakLine("Moira", `${a} ${b}`, hooks("Moira"));
    sandbox.speakLine("Ralph", "Over.", hooks("Ralph"));
    await sandbox.drained();

    assert.deepEqual(log, [
        "start Moira", `play ${a}`, "played 6", `play ${b}`, "played 6",
        "start Ralph", "play Over.", "played 0.5",
    ]);
});

test("the voice: a stop cuts the clip playing, which does not count, and nothing more plays", async () => {
    const { sandbox, log, hooks, until } = voiceHarness({ manual: true });

    sandbox.speakLine("Moira", "First line.", hooks("Moira"));
    sandbox.speakLine("Ralph", "Second line.", hooks("Ralph"));
    await until(() => log.includes("play First line."));
    sandbox.stopVoice();
    await sandbox.drained();
    await new Promise((resolve) => setTimeout(resolve, 10));

    assert.deepEqual(log, ["start Moira", "play First line."]);
});

test("the voice: a chunk that cannot be said is skipped; its line still starts, the rest plays", async () => {
    const { sandbox, log, hooks, warnings } = voiceHarness({ failing: ["Lost."] });

    sandbox.speakLine("Moira", "Lost.", hooks("Moira"));
    sandbox.speakLine("Ralph", "Heard.", hooks("Ralph"));
    await sandbox.drained();

    assert.deepEqual(log, [
        "fail Moira: the voice request failed (HTTP 502)", "start Moira",
        "start Ralph", "play Heard.", "played 0.6",
    ]);
    assert.equal(warnings.length, 1);
});

test("debugLine: once said, the round's first sound and the audio it played", () => {
    const { sandbox } = loadShow();
    const summary = { n: 3, kind: "free", speakers: ["Moira"], event: null, tone: null, heard: null, trimmed: [],
        dropped: [] };

    const line = sandbox.debugLine(summary, { firstLineS: 0.9, seconds: 2.1, firstSoundS: 3.2, playedS: 14.25 }, "r");

    assert.equal(line, "round 3 · free · speakers Moira · event — · tone — · first line 0.9 s · round 2.1 s"
        + " · first sound 3.2 s · played 14.3 s · run r");
});
