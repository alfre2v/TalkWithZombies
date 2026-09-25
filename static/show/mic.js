/**
 * mic.js — The listener's microphone: hold to talk, then hear what was said.
 *
 * The recording code is copied from upstream's stt.js (getUserMedia,
 * MediaRecorder, the recorded chunks into a Blob), without the chat's
 * message box and audio upload. The microphone is open only while the
 * radio listens: primeMic asks for permission once, at Start, so the prompt
 * never eats a listening window; openMic warms the microphone when a window
 * opens, so a press records at once (opening it on the press can clip the
 * first syllable); closeMic releases it when the window ends. hear() sends
 * the recording to the show's own transcription route.
 *
 * A classic script sharing globals, like upstream's; show.js drives it.
 */

const mic = {
    stream: null,         // the open microphone, while a window is open
    recorder: null,       // the MediaRecorder, while a press records
    chunks: [],           // the recorded pieces
    mime: "audio/webm",   // what the browser records (webm, ogg, mp4...)
    allowed: null,        // after primeMic: true, false (denied or no microphone), null (not asked yet)
    held: false,          // the talk button (or the space bar) is held
    pressWaiters: [],     // resolvers of nextPress()
    releaseWaiters: [],   // resolvers of nextRelease()
};

/** Ask for the microphone once, at Start, and release it at once; resolves whether it was granted. */
async function primeMic() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((track) => track.stop());
        mic.allowed = true;
    } catch (err) {
        console.warn("Show microphone: not available:", err);
        mic.allowed = false;
    }
    return mic.allowed;
}

/** Open the microphone for a listening window; resolves false when it cannot be opened. */
async function openMic() {
    try {
        mic.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        return true;
    } catch (err) {
        console.warn("Show microphone: could not open:", err);
        mic.stream = null;
        return false;
    }
}

/** Close the microphone: a recording in progress is discarded, and a held button counts as released. */
function closeMic() {
    if (mic.recorder && mic.recorder.state !== "inactive") {
        mic.recorder.onstop = null;
        mic.recorder.stop();
    }
    mic.recorder = null;
    mic.chunks = [];
    if (mic.stream) mic.stream.getTracks().forEach((track) => track.stop());
    mic.stream = null;
    mic.held = false;
    mic.pressWaiters = [];
    mic.releaseWaiters = [];
}

/** Start recording from the open microphone. */
function startRecording() {
    mic.chunks = [];
    mic.recorder = new MediaRecorder(mic.stream);
    // Capture the actual MIME type the browser chose (webm, ogg, mp4...), as upstream does
    mic.mime = mic.recorder.mimeType || "audio/webm";
    mic.recorder.ondataavailable = (e) => {
        if (e.data.size > 0) mic.chunks.push(e.data);
    };
    mic.recorder.start();
}

/** Stop recording; resolves with the recording as a Blob, or null when nothing was recording. */
function stopRecording() {
    return new Promise((resolve) => {
        const recorder = mic.recorder;
        if (!recorder || recorder.state === "inactive") {
            resolve(null);
            return;
        }
        recorder.onstop = () => resolve(new Blob(mic.chunks, { type: mic.mime }));
        recorder.stop();
    });
}

/** The talk button (or the space bar) went down. */
function talkPress() {
    if (mic.held) return;
    mic.held = true;
    const waiters = mic.pressWaiters;
    mic.pressWaiters = [];
    for (const resolve of waiters) resolve();
}

/** The talk button (or the space bar) came up. */
function talkRelease() {
    if (!mic.held) return;
    mic.held = false;
    const waiters = mic.releaseWaiters;
    mic.releaseWaiters = [];
    for (const resolve of waiters) resolve();
}

/** Resolves at the next press. */
function nextPress() {
    return new Promise((resolve) => mic.pressWaiters.push(resolve));
}

/** Resolves at the next release (at once if nothing is held). */
function nextRelease() {
    if (!mic.held) return Promise.resolve();
    return new Promise((resolve) => mic.releaseWaiters.push(resolve));
}

/** A Blob as base64, for the JSON body of /api/show/listen. */
async function blobToBase64(blob) {
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let binary = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
        binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    }
    return btoa(binary);
}

/**
 * Send a recording to the show's transcription route.
 *
 * Resolves with {text, no_speech_prob, avg_logprob}; an empty recording is
 * heard as nothing (text ""), without a request. Throws when the route fails.
 */
async function hear(blob, mime, runId, signal) {
    if (!blob || !blob.size) return { text: "", no_speech_prob: null, avg_logprob: null };
    const resp = await fetch("/api/show/listen", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId, audio_base64: await blobToBase64(blob), audio_mime_type: mime }),
        signal,
    });
    if (!resp.ok) throw new Error(`the transcription failed (HTTP ${resp.status})`);
    return await resp.json();
}
