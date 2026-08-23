// Tests for Tunings.js, run with `node tests/tunings.test.mjs`. Node built-ins
// only: the plugin has no package manifest and must not gain one, so anything
// that needs an install step cannot be a test dependency here.

import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

// Tunings.js is CommonJS-shaped so that QML can also load it, and this file is
// an ES module, so it needs an explicit require. Resolving against
// import.meta.url rather than the working directory keeps the test runnable
// from anywhere.
const require = createRequire(import.meta.url);
const Tunings = require("../Tunings.js");

// A frequency that is exactly `cents` away from `hz`, which is how the detuned
// inputs below are built: stating the offset is clearer than a magic number.
function detune(hz, cents) {
    return hz * Math.pow(2, cents / 1200);
}

function values(rows) {
    return rows.map(row => row.value);
}

function labels(rows) {
    return rows.map(row => row.label);
}

// -- notation ---------------------------------------------------------------

test("A4 is MIDI 69", () => {
    assert.equal(Tunings.midiOf("A4"), 69);
});

test("midiOf and nameOf round-trip across B0..E4", () => {
    for (let midi = Tunings.midiOf("B0"); midi <= Tunings.midiOf("E4"); midi++) {
        const name = Tunings.nameOf(midi);
        assert.equal(Tunings.midiOf(name), midi, `${midi} -> ${name} -> ?`);
        assert.match(name, /^[A-G]#?-?\d+$/, `${name} is not sharps-only notation`);
    }
});

test("midiOf accepts flats on input but nameOf never spells them", () => {
    assert.equal(Tunings.midiOf("Eb2"), Tunings.midiOf("D#2"));
    assert.equal(Tunings.nameOf(Tunings.midiOf("Eb2")), "D#2");
});

test("midiOf returns null on garbage", () => {
    for (const garbage of ["", "H4", "E", "E 2", "E#b2", "x", null, undefined, {}]) {
        assert.equal(Tunings.midiOf(garbage), null, `${String(garbage)} should not parse`);
    }
});

test("nameOf maps MIDI numbers to sharps-only names", () => {
    assert.equal(Tunings.nameOf(40), "E2");
    assert.equal(Tunings.nameOf(69), "A4");
    assert.equal(Tunings.nameOf(23), "B0");
    assert.equal(Tunings.nameOf(63), "D#4");
});

test("nameOf rejects anything that is not a finite number", () => {
    for (const garbage of [null, undefined, "40", "", {}, NaN, Infinity]) {
        assert.equal(Tunings.nameOf(garbage), null, `${String(garbage)} should not name a note`);
    }
});

test("hzOf derives target frequencies from concert pitch", () => {
    assert.equal(Tunings.hzOf("A4"), 440);
    for (const [name, expected] of [["E2", 82.4069], ["B0", 30.8677], ["E1", 41.2034]]) {
        const actual = Tunings.hzOf(name);
        assert.ok(Math.abs(actual - expected) < 0.01, `${name} was ${actual}, expected ${expected}`);
    }
});

// Concert pitch is a constant in the module rather than an argument, so this is
// what pins it: every A is a power-of-two multiple of 440, which no arithmetic
// slip in the exponent survives.
test("concert pitch is 440 and octaves are exact doublings", () => {
    assert.equal(Tunings.CONCERT_A_HZ, 440);
    for (const [name, expected] of [["A0", 27.5], ["A1", 55], ["A2", 110], ["A3", 220], ["A4", 440], ["A5", 880]]) {
        const actual = Tunings.hzOf(name);
        assert.ok(Math.abs(actual - expected) < 1e-9, `${name} was ${actual}, expected ${expected}`);
    }
});

test("transpose moves a note by whole semitones and rejects garbage", () => {
    assert.equal(Tunings.transpose("E2", -2), "D2");
    assert.equal(Tunings.transpose("B0", -2), "A0");
    assert.equal(Tunings.transpose("E2", 12), "E3");
    assert.equal(Tunings.transpose("nope", -1), null);
});

test("pitchClassOf drops the octave and normalises the spelling", () => {
    assert.equal(Tunings.pitchClassOf("D2"), "D");
    assert.equal(Tunings.pitchClassOf("A0"), "A");
    assert.equal(Tunings.pitchClassOf("Eb3"), "D#");
    assert.equal(Tunings.pitchClassOf("nope"), "");
});

// -- the instrument table ---------------------------------------------------

// Every instrument's standard strings with the frequency each has at a 440 Hz
// reference, written out in full rather than derived. Octave numbering is the
// easiest thing to get wrong here, and no other test in this file can catch
// it: the round-trip and transform tests are generic over whatever the table
// happens to hold. Shifting a whole instrument up an octave passes all of
// them, so these literals are the only thing standing between a transposed
// table and a tuner that confidently names the wrong string.
//
// The three anchors docs/design.md states independently -- E2 at 82.41 Hz in
// the --meter sample, and the 30.87-329.63 Hz selftest range, which is exactly
// B0 to E4 -- pin the octaves of the guitar and bass outer strings to the
// detector's own measured output.
const canonicalStrings = {
    guitar6: [["E2", 82.4069], ["A2", 110.0000], ["D3", 146.8324], ["G3", 195.9977], ["B3", 246.9417], ["E4", 329.6276]],
    guitar7: [["B1", 61.7354], ["E2", 82.4069], ["A2", 110.0000], ["D3", 146.8324], ["G3", 195.9977], ["B3", 246.9417], ["E4", 329.6276]],
    bass4: [["E1", 41.2034], ["A1", 55.0000], ["D2", 73.4162], ["G2", 97.9989]],
    bass5: [["B0", 30.8677], ["E1", 41.2034], ["A1", 55.0000], ["D2", 73.4162], ["G2", 97.9989]],
    bass6: [["B0", 30.8677], ["E1", 41.2034], ["A1", 55.0000], ["D2", 73.4162], ["G2", 97.9989], ["C3", 130.8128]]
};

test("every instrument holds its canonical strings at the right octave", () => {
    assert.deepEqual(Tunings.instruments.map(i => i.id), Object.keys(canonicalStrings));

    for (const instrument of Tunings.instruments) {
        const expected = canonicalStrings[instrument.id];
        assert.deepEqual(instrument.strings, expected.map(([name]) => name), `${instrument.id} strings`);

        for (const [name, hz] of expected) {
            const actual = Tunings.hzOf(name);
            assert.ok(Math.abs(actual - hz) < 0.01, `${instrument.id} ${name} was ${actual} Hz, expected ${hz} Hz`);
        }
    }
});

// An instrument transposed by a whole octave is the failure the literals above
// exist for, so it is worth proving they actually catch one.
test("the canonical table rejects an instrument moved by an octave", () => {
    const bass5 = canonicalStrings.bass5.map(([name]) => name);
    const shifted = bass5.map(name => Tunings.transpose(name, 12));
    assert.notDeepEqual(shifted, bass5);
    assert.deepEqual(shifted, ["B1", "E2", "A2", "D3", "G3"]);
});

// Note names are the storage format, so every string has to be a name the
// module can actually resolve. A typo here would otherwise surface as a blank
// entry in the panel's target strip rather than as a failure.
test("every string of every instrument is a resolvable note name", () => {
    let checked = 0;
    for (const instrument of Tunings.instruments) {
        for (const name of instrument.strings) {
            assert.notEqual(Tunings.midiOf(name), null, `${instrument.id} has unresolvable string ${name}`);
            assert.equal(Tunings.nameOf(Tunings.midiOf(name)), name, `${instrument.id} string ${name} is not canonically spelled`);
            checked++;
        }
    }
    assert.ok(checked > 0, "no strings were checked");
});

// Chromatic is a family, not an instrument. An entry in this table with no
// strings would be an instrument the tuning row could never serve.
test("every instrument belongs to a real family and carries strings", () => {
    for (const instrument of Tunings.instruments) {
        assert.ok(instrument.strings.length > 0, `${instrument.id} has no strings`);
        assert.ok(Tunings.familyById(instrument.family), `${instrument.id} has no family`);
        assert.notEqual(instrument.family, "chromatic", `${instrument.id} is in the chromatic family`);
    }
});

// -- menus ------------------------------------------------------------------

test("the big toggle offers exactly chromatic, guitar and bass", () => {
    assert.deepEqual(values(Tunings.familyOptions()), ["chromatic", "guitar", "bass"]);
    assert.deepEqual(labels(Tunings.familyOptions()), ["Chromatic", "Guitar", "Bass"]);
});

test("each family lists its own instruments, and chromatic lists none", () => {
    assert.deepEqual(values(Tunings.instrumentOptions("guitar")), ["guitar6", "guitar7"]);
    assert.deepEqual(values(Tunings.instrumentOptions("bass")), ["bass4", "bass5", "bass6"]);
    // No instrument and so no reference: both rows are hidden and the readout
    // names whichever semitone is nearest.
    assert.deepEqual(Tunings.instrumentOptions("chromatic"), []);
    assert.deepEqual(Tunings.tuningOptions(""), []);
    assert.deepEqual(Tunings.instrumentOptions("no-such-family"), []);
});

// Both menus have to stay short enough that the dropdown never scrolls, which
// is the whole reason the flat preset list was split in two. Eight rows is the
// point at which the popup starts clipping.
test("neither menu can overflow the dropdown", () => {
    for (const family of Tunings.families) {
        const rows = Tunings.instrumentOptions(family.id);
        assert.ok(rows.length <= 8, `${family.id} has ${rows.length} instruments`);
        for (const row of rows)
            assert.ok(Tunings.tuningOptions(row.value).length <= 8, `${row.value} has too many tunings`);
    }
});

test("every menu row carries a non-empty label", () => {
    const rows = Tunings.familyOptions()
        .concat(Tunings.families.flatMap(f => Tunings.instrumentOptions(f.id)))
        .concat(Tunings.instruments.flatMap(i => Tunings.tuningOptions(i.id)));
    assert.ok(rows.length > 0);
    for (const row of rows)
        assert.ok(typeof row.label === "string" && row.label.length > 0, `${row.value} has no label`);
});

test("the tuning menu offers only references the instrument can take", () => {
    assert.deepEqual(values(Tunings.tuningOptions("guitar6")), ["standard", "drop", "half-down", "full-down", "dadgad"]);
    // DADGAD is a six-string voicing, so it is absent everywhere else.
    assert.deepEqual(values(Tunings.tuningOptions("guitar7")), ["standard", "drop", "half-down", "full-down"]);
    assert.deepEqual(values(Tunings.tuningOptions("bass4")), ["standard", "drop", "half-down", "full-down"]);
    assert.deepEqual(values(Tunings.tuningOptions("bass5")), ["standard", "drop", "half-down", "full-down"]);
    assert.deepEqual(values(Tunings.tuningOptions("bass6")), ["standard", "drop", "half-down", "full-down"]);
    assert.deepEqual(Tunings.tuningOptions("no-such-instrument"), []);
});

test("a drop row names the note the bottom string lands on", () => {
    assert.equal(Tunings.tuningLabel("guitar6", "drop"), "Drop D");
    assert.equal(Tunings.tuningLabel("guitar7", "drop"), "Drop A");
    assert.equal(Tunings.tuningLabel("bass4", "drop"), "Drop D");
    assert.equal(Tunings.tuningLabel("bass5", "drop"), "Drop A");
    assert.equal(Tunings.tuningLabel("bass6", "drop"), "Drop A");
    assert.equal(Tunings.tuningLabel("guitar6", "half-down"), "Half-step down");
    assert.equal(Tunings.tuningLabel("guitar6", "no-such-tuning"), "");
});

// -- string sets ------------------------------------------------------------

// The transform results, written out rather than derived, for the same reason
// the standard sets are: a sign slip in the shift is invisible to a test that
// recomputes it the same way.
const canonicalCombinations = [
    ["guitar6", "standard", ["E2", "A2", "D3", "G3", "B3", "E4"]],
    ["guitar6", "drop", ["D2", "A2", "D3", "G3", "B3", "E4"]],
    ["guitar6", "half-down", ["D#2", "G#2", "C#3", "F#3", "A#3", "D#4"]],
    ["guitar6", "full-down", ["D2", "G2", "C3", "F3", "A3", "D4"]],
    ["guitar6", "dadgad", ["D2", "A2", "D3", "G3", "A3", "D4"]],
    ["guitar7", "standard", ["B1", "E2", "A2", "D3", "G3", "B3", "E4"]],
    ["guitar7", "drop", ["A1", "E2", "A2", "D3", "G3", "B3", "E4"]],
    ["guitar7", "half-down", ["A#1", "D#2", "G#2", "C#3", "F#3", "A#3", "D#4"]],
    ["bass4", "standard", ["E1", "A1", "D2", "G2"]],
    ["bass4", "drop", ["D1", "A1", "D2", "G2"]],
    ["bass4", "half-down", ["D#1", "G#1", "C#2", "F#2"]],
    ["bass4", "full-down", ["D1", "G1", "C2", "F2"]],
    ["bass5", "drop", ["A0", "E1", "A1", "D2", "G2"]],
    ["bass6", "standard", ["B0", "E1", "A1", "D2", "G2", "C3"]],
    ["bass6", "drop", ["A0", "E1", "A1", "D2", "G2", "C3"]],
    // A reference that does not apply degrades to the instrument's own
    // strings rather than to an empty strip.
    ["guitar7", "dadgad", ["B1", "E2", "A2", "D3", "G3", "B3", "E4"]],
    // No instrument, which is the chromatic family.
    ["", "standard", []],
    ["", "", []],
    ["no-such-instrument", "standard", []]
];

test("every instrument and reference pair yields its canonical string set", () => {
    for (const [instrument, tuning, expected] of canonicalCombinations)
        assert.deepEqual(Tunings.stringsFor(instrument, tuning), expected, `${instrument} + ${tuning}`);
});

test("drop lowers only the bottom string, and by a whole tone", () => {
    for (const id of Tunings.instruments.map(instrument => instrument.id)) {
        const standard = Tunings.stringsFor(id, "standard");
        const dropped = Tunings.stringsFor(id, "drop");
        assert.equal(dropped.length, standard.length, `${id} string count`);
        assert.equal(Tunings.midiOf(dropped[0]) - Tunings.midiOf(standard[0]), -2, `${id} bottom string`);
        assert.deepEqual(dropped.slice(1), standard.slice(1), `${id} upper strings`);
    }
});

test("a step down moves every string by the same interval", () => {
    for (const [tuning, semitones] of [["half-down", -1], ["full-down", -2]]) {
        for (const instrument of Tunings.instruments) {
            const standard = Tunings.stringsFor(instrument.id, "standard");
            const shifted = Tunings.stringsFor(instrument.id, tuning);
            assert.equal(shifted.length, standard.length, `${instrument.id} ${tuning} string count`);
            for (let index = 0; index < standard.length; index++)
                assert.equal(Tunings.midiOf(shifted[index]) - Tunings.midiOf(standard[index]), semitones, `${instrument.id} ${tuning} string ${index}`);
        }
    }
});

test("a string set never contains an unresolvable name", () => {
    for (const instrument of Tunings.instruments) {
        for (const row of Tunings.tuningOptions(instrument.id)) {
            const set = Tunings.stringsFor(instrument.id, row.value);
            assert.equal(set.length, instrument.strings.length, `${instrument.id} + ${row.value} lost a string`);
            for (const name of set)
                assert.equal(Tunings.nameOf(Tunings.midiOf(name)), name, `${instrument.id} + ${row.value} produced ${name}`);
        }
    }
});

// -- stored settings --------------------------------------------------------

test("normalize maps every pre-split preset id onto the two axes", () => {
    const legacy = {
        chromatic: { family: "chromatic", instrument: "", tuning: "" },
        guitar: { family: "guitar", instrument: "guitar6", tuning: "standard" },
        "drop-d": { family: "guitar", instrument: "guitar6", tuning: "drop" },
        dadgad: { family: "guitar", instrument: "guitar6", tuning: "dadgad" },
        "half-down": { family: "guitar", instrument: "guitar6", tuning: "half-down" },
        bass4: { family: "bass", instrument: "bass4", tuning: "standard" },
        bass5: { family: "bass", instrument: "bass5", tuning: "standard" }
    };
    for (const [stored, expected] of Object.entries(legacy))
        assert.deepEqual(Tunings.normalize({ target: "", tuning: stored }), expected, `legacy ${stored}`);
});

// Chromatic was briefly an instrument inside each family rather than a family
// of its own, so a record can still name it that way.
test("normalize reads chromatic-as-an-instrument as the chromatic family", () => {
    for (const family of ["guitar", "bass", "other", undefined])
        assert.deepEqual(Tunings.normalize({ family, instrument: "chromatic", tuning: "standard" }), {
            family: "chromatic",
            instrument: "",
            tuning: ""
        }, `family ${family}`);
});

test("normalize keeps a valid triple untouched", () => {
    for (const [instrument, tuning] of [["guitar6", "dadgad"], ["bass5", "drop"], ["guitar7", "half-down"]]) {
        const stored = { family: Tunings.instrumentById(instrument).family, instrument, tuning };
        assert.deepEqual(Tunings.normalize(stored), stored);
    }
    const chromatic = { family: "chromatic", instrument: "", tuning: "" };
    assert.deepEqual(Tunings.normalize(chromatic), chromatic);
});

test("normalize falls back to a tunable default on anything it cannot read", () => {
    const fallback = { family: "chromatic", instrument: "", tuning: "" };
    for (const stored of [undefined, null, {}, "", 7, { instrument: "no-such-instrument" }, { family: "nope" }])
        assert.deepEqual(Tunings.normalize(stored), fallback, `${JSON.stringify(stored)}`);
});

test("normalize resets a reference the instrument cannot take", () => {
    assert.equal(Tunings.normalize({ instrument: "guitar7", tuning: "dadgad" }).tuning, "standard");
    assert.equal(Tunings.normalize({ instrument: "bass4", tuning: "dadgad" }).tuning, "standard");
    assert.equal(Tunings.normalize({ instrument: "bass4", tuning: "no-such-tuning" }).tuning, "standard");
});

// Switching the toggle is a normalize with a new family, which is why the
// panel needs no separate rule for it: an instrument never spans two families,
// so the new family's first is always what it lands on.
test("normalize takes the new family's first instrument when the stored one is elsewhere", () => {
    assert.deepEqual(Tunings.normalize({ family: "bass", instrument: "guitar6", tuning: "drop" }), {
        family: "bass",
        instrument: "bass4",
        tuning: "drop"
    });
    assert.deepEqual(Tunings.normalize({ family: "bass", instrument: "guitar6", tuning: "dadgad" }), {
        family: "bass",
        instrument: "bass4",
        tuning: "standard"
    });
    assert.deepEqual(Tunings.normalize({ family: "chromatic", instrument: "guitar6", tuning: "dadgad" }), {
        family: "chromatic",
        instrument: "",
        tuning: ""
    });
    // An instrument stored without a family keeps the one it belongs to.
    assert.equal(Tunings.normalize({ instrument: "bass5" }).family, "bass");
});

test("the shipped default is a valid triple and asks nothing", () => {
    const defaults = Tunings.normalize({ family: Tunings.DEFAULT_FAMILY });
    assert.deepEqual(defaults, { family: "chromatic", instrument: "", tuning: "" });
    assert.deepEqual(Tunings.normalize(defaults), defaults);
    assert.deepEqual(Tunings.stringsFor(defaults.instrument, defaults.tuning), []);
});

// Whatever normalize answers, the panel binds three rows to it -- so every
// answer has to be one the menus can actually display.
test("normalize always answers something the menus can show", () => {
    const stored = [
        undefined, {}, { family: "chromatic" }, { family: "guitar" }, { family: "bass" },
        { tuning: "bass4" }, { tuning: "dadgad" }, { instrument: "ukulele" },
        { family: "other", instrument: "ukulele", tuning: "half-down" },
        { family: "bass", instrument: "guitar7", tuning: "drop" }
    ];
    for (const record of stored) {
        const next = Tunings.normalize(record);
        assert.ok(Tunings.familyById(next.family), `${JSON.stringify(record)} -> unknown family`);
        const instruments = values(Tunings.instrumentOptions(next.family));
        if (instruments.length === 0) {
            assert.equal(next.instrument, "", `${JSON.stringify(record)} -> stray instrument`);
            assert.equal(next.tuning, "", `${JSON.stringify(record)} -> stray tuning`);
            continue;
        }
        assert.ok(instruments.includes(next.instrument), `${JSON.stringify(record)} -> ${next.instrument}`);
        assert.ok(values(Tunings.tuningOptions(next.instrument)).includes(next.tuning), `${JSON.stringify(record)} -> ${next.tuning}`);
        // Idempotent, so re-reading what the panel wrote changes nothing.
        assert.deepEqual(Tunings.normalize(next), next, `${JSON.stringify(record)} is not stable`);
    }
});

// -- resolution -------------------------------------------------------------

test("chromatic mode reports the nearest semitone", () => {
    for (const name of ["B0", "E1", "E2", "A2", "D3", "A4", "E4"]) {
        const resolved = Tunings.resolve(Tunings.hzOf(name), []);
        assert.equal(resolved.name, name);
        assert.ok(Math.abs(resolved.cents) < 0.01, `${name} read ${resolved.cents} cents off`);
        assert.equal(resolved.targetIndex, -1);
    }
});

test("chromatic mode reports the deviation of a detuned input", () => {
    const resolved = Tunings.resolve(detune(82.4069, -30), []);
    assert.equal(resolved.name, "E2");
    assert.ok(Math.abs(resolved.cents + 30) < 0.1, `read ${resolved.cents} cents`);
    assert.equal(resolved.targetIndex, -1);
});

test("a string set snaps a badly flat low E to E2, not to D#2", () => {
    const resolved = Tunings.resolve(detune(82.4069, -40), Tunings.stringsFor("guitar6", "standard"));
    assert.equal(resolved.name, "E2");
    assert.ok(Math.abs(resolved.cents + 40) < 0.1, `read ${resolved.cents} cents`);
    assert.equal(resolved.targetIndex, 0);
});

// The -40 cent case above is also what plain semitone rounding would answer, so
// it does not on its own prove the nearest-string search. A whole tone flat
// does: chromatic hears D2, and a guitar still has to name the string the
// player meant.
test("a string set still names E2 for a string a whole tone flat", () => {
    const flat = detune(82.4069, -200);
    assert.equal(Tunings.resolve(flat, []).name, "D2");

    const resolved = Tunings.resolve(flat, Tunings.stringsFor("guitar6", "standard"));
    assert.equal(resolved.name, "E2");
    assert.ok(Math.abs(resolved.cents + 200) < 0.1, `read ${resolved.cents} cents`);
    assert.equal(resolved.targetIndex, 0);
});

test("a string set never names a note outside itself", () => {
    for (const [instrument, tuning] of [["bass4", "standard"], ["guitar7", "drop"], ["bass6", "full-down"]]) {
        const targets = Tunings.stringsFor(instrument, tuning);
        for (let hz = 25; hz <= 500; hz += 0.25) {
            const resolved = Tunings.resolve(hz, targets);
            assert.ok(targets.includes(resolved.name), `${instrument} + ${tuning}: ${hz} Hz resolved to ${resolved.name}`);
            assert.equal(targets[resolved.targetIndex], resolved.name);
        }
    }
});

test("resolve returns null when there is no pitch", () => {
    const targets = Tunings.stringsFor("guitar6", "standard");
    for (const hz of [0, -1, -82.4069, NaN, Infinity, null, undefined]) {
        assert.equal(Tunings.resolve(hz, targets), null, `${String(hz)} should not resolve`);
    }
});

test("resolve tolerates a missing or malformed target list", () => {
    for (const targets of [undefined, null, [], [""], ["nope"]]) {
        const resolved = Tunings.resolve(82.4069, targets);
        assert.equal(resolved.name, "E2", `${JSON.stringify(targets)}`);
        assert.equal(resolved.targetIndex, -1);
    }
});
