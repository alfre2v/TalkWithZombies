/**
 * test_show_page.js — Tests for the pure pieces of the show page
 * (static/show/sse.js and static/show/show.js).
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
 *   - the simulated clock of step 3.1 (about 15 characters a second);
 *   - the debug line under a round;
 *   - which rounds that ended early the server kept anyway (a Stop that
 *     lands after the round was recorded).
 *
 * How it works: the show's scripts are browser globals (classic scripts,
 * like upstream's), so each test evaluates sse.js + show.js in a fresh
 * vm.Context — the technique of test_tts_settings.js — and calls their pure
 * functions. show.js only defines functions and registers its page wiring
 * at load time, so a document stub that takes the listener is all the DOM
 * it needs. The page itself is checked by hand (docs/runbooks/show-page.md).
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
const SHOW_SCRIPTS = ["sse.js", "show.js"];

/** A fresh context with the show's scripts loaded; warnings are collected instead of printed. */
function loadShow() {
    const warnings = [];
    const sandbox = {
        console: { log: console.log, error: console.error, warn: (...args) => warnings.push(args) },
        document: { addEventListener: () => {} },
        TextDecoder,
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
