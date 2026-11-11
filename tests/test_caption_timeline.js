"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "..", "static", "editor.js"), "utf8");
const start = source.indexOf("    function movingCaptions(");
const end = source.indexOf("    function totalDuration()", start);
assert.ok(start >= 0 && end > start, "Caption movement helpers must exist");

function setup(captions, selected = []) {
    const context = {
        state: { project: { captions }, zoom: 80 },
        selectedCaptions: new Set(selected),
        clipEnd: clip => clip.start + clip.dur,
        inner: { querySelectorAll: () => [] },
    };
    vm.runInNewContext(source.slice(start, end), context);
    return context;
}

test("linked clips move each matching caption once using its start time", () => {
    const cues = [
        { start: 3.5, end: 4.5, text: "before" },
        { start: 4, end: 4.5, text: "start" },
        { start: 7.5, end: 8.5, text: "crossing" },
        { start: 8, end: 9, text: "after" },
    ];
    const context = setup(cues);
    const items = [{ clip: { start: 4, dur: 4 } }, { clip: { start: 4, dur: 4 } }];
    const positions = context.captionPositions(context.movingCaptions(items));
    context.moveCaptions(positions, 2);
    assert.deepEqual(cues.map(cue => cue.start), [3.5, 6, 9.5, 8]);
    assert.deepEqual(cues.map(cue => cue.end), [4.5, 6.5, 10.5, 9]);
    context.moveCaptions(positions, -1);
    assert.deepEqual(cues.map(cue => cue.start), [3.5, 3, 6.5, 8]);
});

test("explicit selection moves even outside clips and is not duplicated", () => {
    const cues = [{ start: 1, end: 2 }, { start: 4, end: 5 }, { start: 9, end: 10 }];
    const context = setup(cues, [cues[0], cues[1]]);
    const positions = context.captionPositions(context.movingCaptions([{ clip: { start: 3, dur: 3 } }]));
    assert.equal(positions.length, 2);
    context.moveCaptions(positions, 1);
    assert.deepEqual(cues.map(cue => cue.start), [2, 5, 9]);
});
