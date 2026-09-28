/**
 * amateur-radio-transmitter — adds the oscilloscope's trace (the gauge: a still wave for now; the sound level will
 * drive its height in stage two), two needle meters and the desk microphone to the panel.
 */

const SCOPE_POINTS = 160;

/** The trace's path across the scope: a wave whose height follows the level (0-1). */
function scopePath(level) {
    const points = [];
    for (let i = 0; i <= SCOPE_POINTS; i++) {
        const x = (i / SCOPE_POINTS) * 1000;
        const y = 35 - level * 28 * Math.sin(i * 0.45) * Math.sin(i * 0.07 + 0.6);
        points.push(`${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`);
    }
    return points.join(" ");
}

document.addEventListener("DOMContentLoaded", () => {
    const show = document.getElementById("show");

    const trace = document.createElement("div");
    trace.className = "scope-trace";
    trace.innerHTML = `<svg viewBox="0 0 1000 70" preserveAspectRatio="none">
        <path d="${scopePath(0.8)}" fill="none" stroke="#7dff9a" stroke-width="3"/></svg>`;

    const meters = document.createElement("div");
    meters.className = "meters";
    meters.innerHTML = `
        <div class="meter" style="--needle: 18deg"><div class="needle"></div><div class="caption">PLATE mA</div></div>
        <div class="meter" style="--needle: -22deg"><div class="needle"></div><div class="caption">SIGNAL</div></div>`;

    const mic = document.createElement("div");
    mic.className = "desk-mic";
    mic.innerHTML = `<svg viewBox="0 0 120 150" aria-hidden="true">
        <defs><linearGradient id="chrome" x1="0" x2="1"><stop offset="0" stop-color="#8a8f95"/>
            <stop offset="0.45" stop-color="#f2f4f6"/><stop offset="1" stop-color="#6d7277"/></linearGradient></defs>
        <rect x="20" y="130" width="80" height="14" rx="7" fill="url(#chrome)"/>
        <rect x="56" y="78" width="8" height="54" fill="url(#chrome)"/>
        <rect x="30" y="8" width="60" height="78" rx="30" fill="url(#chrome)" stroke="#444" stroke-width="2"/>
        <g stroke="#555" stroke-width="2">${[22, 32, 42, 52, 62, 72].map((y) =>
            `<line x1="36" y1="${y}" x2="84" y2="${y}"/>`).join("")}</g></svg>`;

    show.append(trace, meters, mic);
});
