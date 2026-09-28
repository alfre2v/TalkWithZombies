/**
 * lab-terminal — adds the signal bar (the gauge: filled blocks for the sound level, 0-1; a still level for now,
 * the gauge's sound level will drive it in stage two).
 */

const SIGNAL_BLOCKS = 12;

/** The signal bar's text for a level (0-1): "SIGNAL [▮▮▮▮▯▯▯…]". */
function signalText(level) {
    const filled = Math.round(Math.max(0, Math.min(1, level)) * SIGNAL_BLOCKS);
    return `SIGNAL [${"▮".repeat(filled)}${"▯".repeat(SIGNAL_BLOCKS - filled)}]`;
}

document.addEventListener("DOMContentLoaded", () => {
    const bar = document.createElement("div");
    bar.className = "signal-bar";
    bar.textContent = signalText(0.6);
    document.getElementById("show").append(bar);
});
