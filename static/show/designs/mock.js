/**
 * mock.js — A recorded stretch of a show, put on the page for looking at a design without running one.
 *
 * Loaded only with /show?design=<name>&mock=1 (templates/show_design.html). It uses show.js's own functions
 * to fill the title, the cast, a few rounds and the lamps, exactly as a running show would. The lines are
 * rounds 63-66 of the owner's listen of 2026-09-28 (the fork's run 2026-09-28T13-43-28): an event read out,
 * the call, and two exchanges with a caller. ?mockstate=listening shows the page waiting for the listener.
 */

const MOCK_ROUNDS = [
    {
        direction: "The dead at the gate wander off, drawn away by a car alarm down the road.",
        lines: [
            ["Ralph", "relieved", "The dead at the gate wander off, drawn away by a car alarm down the road. Over."],
            ["Moira", "relieved", "They're distracted now. Over."],
            ["Ralph", "hopeful", "We can move safely for a while. Over."],
        ],
    },
    {
        direction: "The receiver crackles back to life.",
        lines: [
            ["Daniel", "hopeful", "Good news: the receiver works again. We patched the burnt circuit. Over."],
            ["Samantha", "happy", "The receiver's on, so we can hear you. Please, answer. Over."],
        ],
    },
    {
        heard: "Hello, this is Alfredo again from Texas. I was reviewing some samples of the virus. It seems that the "
            + "red blood count is very low, and the leucocytes are tremendously off the charts. What do you guys "
            + "find in your site?",
        lines: [
            ["Samantha", "calm", "Hello, Alfredo! We're here. How did you find us? Over."],
            ["Daniel", "determined", "What's your take on the blood count and white cells? Over."],
            ["Moira", "curious", "Do you have samples we could test? Over."],
        ],
    },
    {
        heard: "I just received some samples, but do you guys did any studies?",
        lines: [
            ["Moira", "hopeful", "Are you near the outbreak's origin? Over."],
            ["Daniel", "relieved", "Do you have a vehicle or supplies to share? Over."],
        ],
    },
];

document.addEventListener("DOMContentLoaded", () => {
    el("show-title").textContent = "The Lab at the End of the Frequency";
    renderCast(["Daniel", "Moira", "Ralph", "Samantha"]);
    let last = null;
    for (const round of MOCK_ROUNDS) {
        const block = addRoundElement();
        if (round.heard) addHeardCaption(block, { text: round.heard });
        for (const [speaker, mood, text] of round.lines) {
            addLine(block, speaker, mood, text, false);
            last = speaker;
        }
        addDirection(block, round.direction);
    }
    setReceiver(true);
    if (new URLSearchParams(location.search).get("mockstate") === "listening") {
        setState("listening", "8 s");
        el("btn-talk").disabled = false;
        lightSpeaker(null);
    } else {
        setState("on air");
        lightSpeaker(last);
    }
});
