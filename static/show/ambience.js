/**
 * ambience.js — The world outside the lab: the dead, the fighting, the people, the weather, heard through the
 * broadcast under the show.
 *
 * Loaded after bed.js, wherever bed.js is (the designed pages; the plain page only with ?bed=on), and like it, it
 * edits none of the page's scripts: it wraps setState (show.js) from outside, as bed.js does, and reuses bed.js's
 * rules (bedShuffle, bedBetween, bedFadingTarget). The run's start reply brings the ambience (show.run.ambience):
 * its clips — a file served at /api/show/ambience/<file>, a gain each (measured to a common level by zombie-radio's
 * tools/sounds/prepare_ambience.py) and a kind, texture or spot — and its settings. No ambience in the reply, or no
 * voice, no sound.
 *
 * The textures (long, continuous: the dead moaning, the warfare, the storm) play one after another in a shuffled
 * order, as the bed's clips do, never the same twice across the seam. The spots (short, single events: a shriek, an
 * explosion, a scream, a laugh) play one at a time, after a random wait in spot_every_s, at spot_volume times a
 * texture's level, never the same spot twice in a row. Each streams through its own <audio> element:
 *
 *     a texture → its gain → the silences' gate ─┐
 *     a spot → its gain × spot_volume ───────────┴→ the ambience's level (mono) → the AM filter (or straight on)
 *     → the fading → the A key's mute → the speakers
 *
 * The level follows the show as the bed's does: volume_voice while a round is said, volume_between while the page
 * waits, silent while the listener holds to talk, paused on Stop; it goes on while the receiver is on (the world
 * outside does not stop for a call). Its silences (silences: after a random time in silence_every_s the textures fade
 * out and pause for a random length in silence_s; a spot may still come out of one) and its fading (within plus or
 * minus fading_db every fading_every_s) run on timers of their own, never in step with the bed's. The AM filter is
 * the bed's, at the bed's band (filter, filter_low_hz-filter_high_hz, from the bed's settings): inside the broadcast,
 * one radio — the F key flips both, the ambience following the bed. The A key mutes and unmutes the ambience alone;
 * the M key mutes the static only. With the run's debug on, the console says what the ambience does.
 *
 * Sound cues: a round whose event names a sound (a keyword of a clip, in the story's ambience.yaml) brings a cue
 * (show.current.cue, from the round's "cue" event: a file and its kind), played once, when the round's first line is
 * heard (the page goes "on air"): a spot at once, cutting a spot under way, the next random spot set from its end; a
 * texture in place of the current one, to its end, ending a silence under way and setting the next one from now,
 * then the shuffle goes on. A cue switches nothing on: no spot when the run has spots off, nothing heard when the A
 * key has muted the ambience.
 *
 * A classic script sharing globals, like the page's own.
 */

const AMB = {
    silenceS: 0.15,     // how fast the ambience goes silent when the listener presses to talk
    clipFadeS: 0.6,     // each texture fades in over this, so a join never clicks in
    spotFadeS: 0.05,    // a spot comes in at once, without a click
    muteFadeS: 0.3,     // the A key's fade
    muteKey: "KeyA",
    filterKey: "KeyF",
};

const amb = {
    ctx: null,          // the page's AudioContext, once the ambience is wired into it
    mute: null,         // the A key's gain
    fading: null,       // the fading's gain, gliding around 1
    highpass: null,     // the AM filter's two halves (the bed's band)
    lowpass: null,
    layer: null,        // the ambience's level, mixed down to mono
    gate: null,         // the silences' gain, on the textures only
    textureGain: null,  // the texture's own gain
    spotGain: null,     // the spot's own gain, times spot_volume
    texture: null,      // the <audio> element of the textures
    spot: null,         // the <audio> element of the spots
    runId: null,
    order: [],          // the textures still to play in this pass, by index among the textures
    current: null,      // the texture loaded now, by index
    lastSpot: null,     // the spot heard last, by index among the spots
    cued: null,         // the round whose cue has been played, so it plays once
    failures: 0,        // textures that failed to load in a row: when every one has, the textures give up
    gaveUp: false,
    playing: false,
    silent: false,      // a silence under way, on the textures
    silenceTimer: null,
    fadingTimer: null,
    spotTimer: null,
    filterOn: false,
    muted: false,
    level: 0,
    random: Math.random, // the dice (the tests load their own)
};

/* ==========================================================================
   The rules (tested in tests/test_show_ambience.js)
   ========================================================================== */

/** The ambience's level for a state of the show: null when it pauses, 0 when silent, else a level from it. */
function ambLevel(state, settings) {
    if (!RUNNING_STATES.includes(state)) return null;
    if (state === "recording") return 0;
    return state === "on air" ? settings.volume_voice : settings.volume_between;
}

/** The clips of a kind, by their place among the run's clips. */
function ambOfKind(clips, kind) {
    return clips.filter((clip) => clip.kind === kind);
}

/** A random spot, by index among n, never last (the spot heard last) when there is another. */
function ambPickSpot(n, last, random = Math.random) {
    if (n <= 1) return 0;
    const pick = Math.floor(random() * (n - 1));
    return last !== null && pick >= last ? pick + 1 : pick;
}

/* ==========================================================================
   The sound
   ========================================================================== */

/** Move an audio parameter to target over seconds, from wherever it is now (at once when seconds is 0). */
function ambRamp(param, target, seconds) {
    const now = amb.ctx.currentTime;
    param.cancelScheduledValues(now);
    param.setValueAtTime(param.value, now);
    if (seconds > 0) param.linearRampToValueAtTime(target, now + seconds);
    else param.setValueAtTime(target, now);
}

/** An <audio> element streaming into a gain node of the page's AudioContext. */
function ambElement(gainNode, onEnded, onError) {
    const audio = new globalThis.Audio();
    audio.preload = "auto";
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("error", onError);
    amb.ctx.createMediaElementSource(audio).connect(gainNode);
    return audio;
}

/** Wire the ambience into the page's AudioContext, once per context; false when the browser cannot. */
function ambWire() {
    if (amb.ctx === voice.ctx) return true;
    const ctx = voice.ctx;
    if (typeof ctx.createMediaElementSource !== "function" || typeof globalThis.Audio !== "function") return false;
    amb.ctx = ctx;
    amb.mute = ctx.createGain();
    amb.mute.gain.value = amb.muted ? 0 : 1;
    amb.mute.connect(ctx.destination);
    amb.fading = ctx.createGain();
    amb.fading.connect(amb.mute);
    amb.highpass = ctx.createBiquadFilter();
    amb.highpass.type = "highpass";
    amb.lowpass = ctx.createBiquadFilter();
    amb.lowpass.type = "lowpass";
    for (const filter of [amb.highpass, amb.lowpass]) filter.Q.value = Math.SQRT1_2; // Flat, no peak at the edge
    amb.highpass.connect(amb.lowpass);
    amb.lowpass.connect(amb.fading);
    amb.layer = ctx.createGain();
    amb.layer.channelCount = 1; // Mixed down to mono, (left + right) / 2, as a radio's speaker
    amb.layer.channelCountMode = "explicit";
    amb.layer.channelInterpretation = "speakers";
    amb.layer.gain.value = 0;
    amb.layer.connect(amb.fading);
    amb.gate = ctx.createGain();
    amb.gate.connect(amb.layer);
    amb.textureGain = ctx.createGain();
    amb.textureGain.connect(amb.gate);
    amb.spotGain = ctx.createGain();
    amb.spotGain.connect(amb.layer);
    amb.texture = ambElement(amb.textureGain, ambNext, ambFailed);
    amb.texture.addEventListener("playing", () => { amb.failures = 0; });
    amb.spot = ambElement(amb.spotGain, ambScheduleSpot, ambScheduleSpot);
    amb.level = 0;
    return true;
}

/** Route the ambience's level through the AM filter, at the bed's band, or straight on to the fading. */
function ambRoute() {
    const settings = show.run.ambience;
    amb.highpass.frequency.value = settings.filter_low_hz;
    amb.lowpass.frequency.value = settings.filter_high_hz;
    amb.layer.disconnect();
    amb.layer.connect(amb.filterOn ? amb.highpass : amb.fading);
}

/** Follow the show's state: the level it asks for, a pause when it stops. */
function ambFollow() {
    const settings = show.run && show.run.ambience;
    if (!settings || !settings.clips.length || !voice.ctx) return;
    const target = ambLevel(show.state, settings);
    if (target === null) {
        ambPause();
        return;
    }
    if (!ambWire()) return;
    if (amb.runId !== show.run.run_id) {
        amb.runId = show.run.run_id;
        amb.order = [];
        amb.current = null;
        amb.lastSpot = null;
        amb.cued = null;
        amb.failures = 0;
        amb.gaveUp = false;
        amb.filterOn = Boolean(settings.filter);
        ambRoute();
    }
    if (target !== amb.level) {
        let seconds = target < amb.level ? settings.dip_s : settings.rise_s;
        if (show.state === "recording") seconds = AMB.silenceS;
        ambRamp(amb.layer.gain, target, seconds);
        amb.level = target;
    }
    if (!amb.playing) {
        amb.playing = true;
        if (ambOfKind(settings.clips, "texture").length && !amb.gaveUp) {
            if (amb.current === null) ambNext();
            else ambPlay();
            ambScheduleSilence();
        }
        ambScheduleSpot();
        ambFade();
    }
    const round = show.current;
    if (show.state === "on air" && round && round.cue && amb.cued !== round) {
        amb.cued = round;
        ambCue(round.cue);
    }
}

/** Say what the ambience does in the browser's console, when the run's debug is on. */
function ambLog(message) {
    if (show.run && show.run.debug) console.info(`Show: ambience ${message}`);
}

/* The textures: one after another, shuffled, as the bed's clips. */

/** Load the next texture of the order (a new shuffle when it is used up), and play it if the ambience is playing. */
function ambNext() {
    const textures = ambOfKind(show.run.ambience.clips, "texture");
    if (!textures.length) return;
    if (!amb.order.length) {
        amb.order = bedShuffle(textures.length, amb.current, amb.random);
        ambLog(`shuffled: a new pass of ${textures.length} textures`);
    }
    ambLoad(amb.order.shift(), `texture ${textures.length - amb.order.length} of ${textures.length}`);
}

/** Load the texture at index among the textures, fading in, and play it if the ambience is playing; what says why. */
function ambLoad(index, what) {
    const clip = ambOfKind(show.run.ambience.clips, "texture")[index];
    amb.current = index;
    ambLog(`${what}: ${clip.file}`);
    amb.texture.src = `/api/show/ambience/${encodeURIComponent(clip.file)}`;
    amb.textureGain.gain.cancelScheduledValues(amb.ctx.currentTime);
    amb.textureGain.gain.setValueAtTime(0, amb.ctx.currentTime);
    amb.textureGain.gain.linearRampToValueAtTime(clip.gain, amb.ctx.currentTime + AMB.clipFadeS);
    if (amb.playing && !amb.silent) ambPlay();
}

/** Play the loaded texture from where it is; a refusal is logged, the show goes on. */
function ambPlay() {
    const played = amb.texture.play();
    if (played && typeof played.catch === "function") {
        played.catch((err) => console.warn("Show: the ambience could not play:", err));
    }
}

/** A texture could not be loaded: the next one, unless every texture has failed in a row. */
function ambFailed() {
    amb.failures += 1;
    if (amb.failures >= ambOfKind(show.run.ambience.clips, "texture").length) {
        console.warn("Show: no texture of the ambience would load; the textures are off for this run");
        amb.gaveUp = true;
        amb.texture.pause();
        return;
    }
    ambNext();
}

/* The spots: one at a time, after a random wait; never the same twice in a row. */

/** Set the next spot, a random time in spot_every_s from now (when the run has spots and the ambience plays). */
function ambScheduleSpot() {
    const settings = show.run && show.run.ambience;
    globalThis.clearTimeout(amb.spotTimer);
    amb.spotTimer = null;
    if (!amb.playing || !settings || !settings.spots || !ambOfKind(settings.clips, "spot").length) return;
    amb.spotTimer = globalThis.setTimeout(ambSpot, bedBetween(settings.spot_every_s, amb.random) * 1000);
}

/** A spot: a random one, at its gain times spot_volume; the next is set when it ends. */
function ambSpot() {
    amb.spotTimer = null;
    if (!amb.playing) return;
    const settings = show.run.ambience;
    const spots = ambOfKind(settings.clips, "spot");
    amb.lastSpot = ambPickSpot(spots.length, amb.lastSpot, amb.random);
    ambPlaySpot(spots[amb.lastSpot], "spot");
}

/** Play a spot at its gain times spot_volume, cutting one under way; the next random spot is set when it ends. */
function ambPlaySpot(clip, what) {
    const settings = show.run.ambience;
    globalThis.clearTimeout(amb.spotTimer);
    amb.spotTimer = null;
    ambLog(`${what}: ${clip.file}`);
    amb.spot.src = `/api/show/ambience/${encodeURIComponent(clip.file)}`;
    ambRamp(amb.spotGain.gain, clip.gain * settings.spot_volume, AMB.spotFadeS);
    const played = amb.spot.play();
    if (played && typeof played.catch === "function") {
        played.catch((err) => {
            console.warn("Show: an ambience spot could not play:", err);
            ambScheduleSpot();
        });
    }
}

/* The sound cues: the round's event named a sound. */

/** Play a cue: a spot at once (when the run has spots), or a texture in place of the current one, to its end. */
function ambCue(cue) {
    const settings = show.run.ambience;
    const clips = ambOfKind(settings.clips, cue.kind);
    const index = clips.findIndex((clip) => clip.file === cue.file);
    if (index < 0) return;
    if (cue.kind === "spot") {
        if (!settings.spots) return;
        amb.lastSpot = index;
        ambPlaySpot(clips[index], "cue, spot");
        return;
    }
    if (amb.gaveUp) return;
    if (amb.silent) {
        globalThis.clearTimeout(amb.silenceTimer);
        amb.silent = false;
        ambRamp(amb.gate.gain, 1, AMB.clipFadeS);
    }
    if (settings.silences) ambScheduleSilence();
    amb.order = amb.order.filter((i) => i !== index);
    ambLoad(index, "cue, texture");
}

/** Pause the ambience at once, keeping the texture's place; no silence or spot due; the next level rises from 0. */
function ambPause() {
    amb.playing = false;
    for (const timer of ["silenceTimer", "fadingTimer", "spotTimer"]) {
        globalThis.clearTimeout(amb[timer]);
        amb[timer] = null;
    }
    amb.silent = false;
    if (!amb.texture) return;
    amb.texture.pause();
    amb.spot.pause();
    ambRamp(amb.layer.gain, 0, 0);
    ambRamp(amb.gate.gain, 1, 0);
    amb.level = 0;
}

/* The silences, on the textures: a fade out, the texture paused, a fade back in where it stopped. */

/** Set the next silence, a random time in silence_every_s from now (when the run's ambience has silences). */
function ambScheduleSilence() {
    const settings = show.run.ambience;
    globalThis.clearTimeout(amb.silenceTimer);
    amb.silenceTimer = settings.silences
        ? globalThis.setTimeout(ambSilence, bedBetween(settings.silence_every_s, amb.random) * 1000)
        : null;
}

/** A silence: fade the textures out, then pause the texture for a random length in silence_s. */
function ambSilence() {
    if (!amb.playing) return;
    const settings = show.run.ambience;
    const seconds = bedBetween(settings.silence_s, amb.random);
    amb.silent = true;
    ambLog(`silence: ${seconds.toFixed(1)} s`);
    ambRamp(amb.gate.gain, 0, settings.silence_fade_s);
    amb.silenceTimer = globalThis.setTimeout(() => {
        amb.texture.pause();
        amb.silenceTimer = globalThis.setTimeout(ambSilenceEnds, seconds * 1000);
    }, settings.silence_fade_s * 1000);
}

/** The silence is over: the texture goes on where it stopped, fading back in, and the next silence is set. */
function ambSilenceEnds() {
    amb.silent = false;
    ambPlay();
    ambRamp(amb.gate.gain, 1, show.run.ambience.silence_fade_s);
    ambScheduleSilence();
}

/** The fading: glide to a new level within plus or minus fading_db, over a random time in fading_every_s. */
function ambFade() {
    const settings = show.run.ambience;
    if (!amb.playing || !(settings.fading_db > 0)) return;
    const seconds = bedBetween(settings.fading_every_s, amb.random);
    ambRamp(amb.fading.gain, bedFadingTarget(settings.fading_db, amb.random), seconds);
    amb.fadingTimer = globalThis.setTimeout(ambFade, seconds * 1000);
}

/* The keys: A mutes the ambience; F flips the AM filter, with the bed's. */

/** The A key: mute or unmute the ambience (the static keeps playing). */
function ambMute() {
    amb.muted = !amb.muted;
    if (amb.mute) ambRamp(amb.mute.gain, amb.muted ? 0 : 1, AMB.muteFadeS);
    ambLog(amb.muted ? "muted (A)" : "unmuted (A)");
}

/** The F key: the AM filter on or off, as the bed's is now (bed.js has flipped it first); nothing before it plays. */
function ambFlipFilter() {
    if (!amb.ctx || !show.run || !show.run.ambience) return;
    amb.filterOn = typeof bed !== "undefined" && bed.ctx ? bed.filterOn : !amb.filterOn;
    ambRoute();
    ambLog(amb.filterOn ? "filter on (F)" : "filter off (F)");
}

/* The wrap: the page's setState (already wrapped by bed.js), called as before, then followed. */

const ambPageSetState = setState;
setState = function (...args) {
    const result = ambPageSetState.apply(this, args);
    ambFollow();
    return result;
};

document.addEventListener("keydown", (e) => {
    if (e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.code === AMB.muteKey) ambMute();
    else if (e.code === AMB.filterKey) ambFlipFilter();
});
