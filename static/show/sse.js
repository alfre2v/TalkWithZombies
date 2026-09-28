/**
 * sse.js — Read a show round's server-sent events from a fetch response.
 *
 * Copied from upstream's chat.js (the reading loop in sendMessage), so the
 * show can change it without touching the chat. A round is a POST, and
 * EventSource only does GET, so the body is read by hand. splitSSE is the
 * pure part: whole "data: " lines become events; a partial line waits for
 * the next network chunk.
 */

/**
 * Split buffered stream text into its events and the unfinished rest.
 *
 * Lines that are not "data: " lines are skipped, and so is data that is not
 * JSON (with a warning).
 */
function splitSSE(buffer) {
    const lines = buffer.split("\n");
    const rest = lines.pop(); // Keep the incomplete line for the next chunk
    const events = [];
    for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const json = line.slice(6);
        if (!json.trim()) continue;
        try {
            events.push(JSON.parse(json));
        } catch (e) {
            console.warn("Failed to parse SSE event:", json, e);
        }
    }
    return { events, rest };
}

/** Read a response body to its end, calling onEvent with each event as it arrives. */
async function readSSE(resp, onEvent) {
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const { events, rest } = splitSSE(buffer);
        buffer = rest;
        for (const event of events) onEvent(event);
    }
}
