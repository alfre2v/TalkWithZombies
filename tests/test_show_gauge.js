/**
 * test_show_gauge.js — Tests for the designs' gauge (static/show/gauge.js).
 *
 * Run with plain Node (Node 20+, no npm packages, no network):
 *
 *     node tests/test_show_gauge.js
 *
 * What it locks in:
 *   - the level math: the loudness of a frame (RMS), and the smoothing — quick up, slow down;
 *   - the voice's tap: once the page unlocks its audio, every clip sent to the speakers also feeds the gauge's
 *     analyser, and a node connected elsewhere does not;
 *   - the microphone's tap: an open microphone feeds a second analyser (never the speakers), and closing it
 *     disconnects it;
 *   - the gauge's frame: the voice's level, or the microphone's while the listener records, handed to the
 *     registered listeners;
 *   - the plain page's scripts alone define no gauge and keep their own functions.
 *
 * How it works: like test_show_page.js, the page's scripts (sse.js, player.js, mic.js, show.js) and gauge.js are
 * evaluated in a fresh vm.Context, with stubs for the AudioContext and the microphone.
 *
 * NOTE: this file is intentionally NOT part of the pytest suite. Run it alongside:
 *     python3 -m pytest
 *     node tests/test_show_gauge.js
 */

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const SHOW_DIR = path.join(__dirname, "..", "static", "show");
const PAGE_SCRIPTS = ["sse.js", "player.js", "mic.js", "show.js"];

/** An analyser stub whose frames hold one value. */
function analyserStub() {
    return {
        fftSize: 2048,
        value: 0,
        getFloatTimeDomainData(buffer) { buffer.fill(this.value); },
    };
}

/** An AudioContext stub recording what each source connects to. */
function audioContextClass(made) {
    return class AudioContextStub {
        constructor() {
            this.state = "running";
            this.destination = { name: "speakers" };
            this.analysers = [];
            this.streamSources = [];
            made.push(this);
        }
        resume() {}
        createAnalyser() {
            const analyser = analyserStub();
            this.analysers.push(analyser);
            return analyser;
        }
        createBufferSource() {
            return { connected: [], connect(node) { this.connected.push(node); return node; } };
        }
        createMediaStreamSource(stream) {
            const source = { stream, connected: [], disconnected: false,
                connect(node) { this.connected.push(node); }, disconnect() { this.disconnected = true; } };
            this.streamSources.push(source);
            return source;
        }
    };
}

/** A fresh context with the page's scripts, and gauge.js unless told otherwise. */
function load({ withGauge = true } = {}) {
    const contexts = [];
    const stream = { getTracks: () => [] };
    const sandbox = {
        console: { log: () => {}, error: () => {}, warn: () => {} },
        document: { addEventListener: () => {} },
        navigator: { mediaDevices: { getUserMedia: async () => stream } },
        AudioContext: audioContextClass(contexts),
        TextDecoder, setTimeout, clearTimeout, AbortController, atob, btoa, Blob, performance,
    };
    vm.createContext(sandbox);
    for (const file of withGauge ? [...PAGE_SCRIPTS, "gauge.js"] : PAGE_SCRIPTS) {
        vm.runInContext(fs.readFileSync(path.join(SHOW_DIR, file), "utf8"), sandbox, { filename: file });
    }
    const get = (expression) => vm.runInContext(expression, sandbox);
    return { sandbox, contexts, stream, get };
}

/* ==========================================================================
   The level math
   ========================================================================== */

test("rmsLevel: the loudness of a frame", () => {
    const { sandbox } = load();
    assert.equal(sandbox.rmsLevel(new Float32Array([0, 0, 0, 0])), 0);
    assert.ok(Math.abs(sandbox.rmsLevel(new Float32Array([0.5, -0.5, 0.5, -0.5])) - 0.5) < 1e-9);
    assert.equal(sandbox.rmsLevel(new Float32Array([])), 0);
});

test("smoothLevel: rises quickly toward a louder frame, falls back slowly", () => {
    const { sandbox, get } = load();
    const { attack, release } = get("GAUGE");
    assert.ok(Math.abs(sandbox.smoothLevel(0, 1) - attack) < 1e-9);
    assert.ok(Math.abs(sandbox.smoothLevel(1, 0) - (1 - release)) < 1e-9);
    assert.ok(attack > release);
});

/* ==========================================================================
   The taps
   ========================================================================== */

test("the voice's tap: after the page unlocks its audio, clips sent to the speakers also feed the gauge", () => {
    const { sandbox, contexts, get } = load();
    sandbox.unlockAudio();
    const ctx = contexts[0];
    assert.equal(get("voice.ctx"), ctx);
    const analyser = get("gauge.voice");
    assert.ok(analyser);

    const toSpeakers = ctx.createBufferSource();
    toSpeakers.connect(ctx.destination);
    assert.deepEqual(toSpeakers.connected, [analyser, ctx.destination]);

    const elsewhere = ctx.createBufferSource();
    const other = { name: "other" };
    elsewhere.connect(other);
    assert.deepEqual(elsewhere.connected, [other]);
});

test("the voice's tap is made once, however often the page unlocks its audio", () => {
    const { sandbox, contexts, get } = load();
    sandbox.unlockAudio();
    const analyser = get("gauge.voice");
    sandbox.unlockAudio();
    assert.equal(contexts.length, 1);
    assert.equal(get("gauge.voice"), analyser);
});

test("the microphone's tap: an open microphone feeds its own analyser, not the speakers; closing disconnects",
    async () => {
    const { sandbox, contexts, stream, get } = load();
    sandbox.unlockAudio();
    const ctx = contexts[0];

    assert.equal(await sandbox.openMic(), true);
    const source = ctx.streamSources[0];
    assert.equal(source.stream, stream);
    assert.deepEqual(source.connected, [get("gauge.mic")]);
    assert.ok(!source.connected.includes(ctx.destination));

    sandbox.closeMic();
    assert.equal(source.disconnected, true);
    assert.equal(get("gauge.mic"), null);
    assert.equal(get("mic.stream"), null);
});

/* ==========================================================================
   The gauge's frame
   ========================================================================== */

test("gaugeTick: the voice's level reaches the listeners; while the listener records, the microphone's", async () => {
    const { sandbox, get } = load();
    sandbox.unlockAudio();
    await sandbox.openMic();
    get("gauge.voice").value = 0.1;
    get("gauge.mic").value = 0.25;
    const heard = [];
    sandbox.onGaugeLevel((levels) => heard.push(levels));

    for (let i = 0; i < 30; i++) sandbox.gaugeTick();
    const onAir = heard.at(-1);
    assert.ok(Math.abs(onAir.voice - 0.35) < 0.01, `voice ${onAir.voice}`);
    assert.ok(Math.abs(onAir.mic - 0.875) < 0.01, `mic ${onAir.mic}`);
    assert.equal(onAir.level, onAir.voice);

    get("show").state = "recording";
    sandbox.gaugeTick();
    assert.equal(heard.at(-1).level, heard.at(-1).mic);
});

test("gaugeTick: a loud frame is capped at 1", () => {
    const { sandbox, get } = load();
    sandbox.unlockAudio();
    get("gauge.voice").value = 0.9;
    for (let i = 0; i < 30; i++) sandbox.gaugeTick();
    assert.ok(get("gauge.voiceLevel") <= 1);
});

/* ==========================================================================
   The plain page
   ========================================================================== */

test("the plain page's scripts alone define no gauge and keep their own functions", () => {
    const { sandbox, contexts, get } = load({ withGauge: false });
    assert.equal(typeof sandbox.gaugeTick, "undefined");
    assert.equal(get("typeof gauge"), "undefined");
    sandbox.unlockAudio();
    const source = contexts[0].createBufferSource();
    source.connect(contexts[0].destination);
    assert.deepEqual(source.connected, [contexts[0].destination]);
});
