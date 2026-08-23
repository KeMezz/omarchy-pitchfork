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

// Interval between two frequencies in cents, which is how the assertions below
// state a deviation instead of comparing raw hertz.
function centsBetween(hz, against) {
    return 1200 * Math.log2(hz / against);
}

// A frequency that is exactly `cents` away from `hz`, which is how the detuned
// inputs below are built: stating the offset is clearer than a magic number.
function detune(hz, cents) {
    return hz * Math.pow(2, cents / 1200);
}

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
    for (const [name, expected] of [["A0", 27.5], ["A1", 55], ["A2", 110], ["A3", 220], ["A4", 440], ["A5", 880]]) {
        const actual = Tunings.hzOf(name);
        assert.ok(Math.abs(actual - expected) < 1e-9, `${name} was ${actual}, expected ${expected}`);
    }
});

// Every preset target with the frequency it has at a 440 Hz reference, written
// out in full rather than derived. Octave numbering is the easiest thing to get
// wrong here, and no other test in this file can catch it: the round-trip and
// reference-shift tests are generic over whatever the table happens to hold,
// and the bass4 sweep only checks that a preset agrees with itself. Shifting a
// whole preset up an octave passes all of them, so these literals are the only
// thing standing between a transposed table and a tuner that confidently names
// the wrong string.
//
// The three anchors docs/design.md states independently -- E2 at 82.41 Hz in the
// --meter sample, and the 30.87-329.63 Hz selftest range, which is exactly
// B0 to E4 -- pin the octaves of the outer strings to the detector's own
// measured output.
const canonicalTargets = {
    chromatic: [],
    guitar: [["E2", 82.4069], ["A2", 110.0000], ["D3", 146.8324], ["G3", 195.9977], ["B3", 246.9417], ["E4", 329.6276]],
    "drop-d": [["D2", 73.4162], ["A2", 110.0000], ["D3", 146.8324], ["G3", 195.9977], ["B3", 246.9417], ["E4", 329.6276]],
    dadgad: [["D2", 73.4162], ["A2", 110.0000], ["D3", 146.8324], ["G3", 195.9977], ["A3", 220.0000], ["D4", 293.6648]],
    "half-down": [["D#2", 77.7817], ["G#2", 103.8262], ["C#3", 138.5913], ["F#3", 184.9972], ["A#3", 233.0819], ["D#4", 311.1270]],
    bass4: [["E1", 41.2034], ["A1", 55.0000], ["D2", 73.4162], ["G2", 97.9989]],
    bass5: [["B0", 30.8677], ["E1", 41.2034], ["A1", 55.0000], ["D2", 73.4162], ["G2", 97.9989]]
};

test("every preset holds its canonical targets at the right octave", () => {
    // The order is asserted too, because byId falls back to list[0] and that
    // fallback is only harmless while the first entry is the chromatic one.
    assert.deepEqual(Tunings.list.map(tuning => tuning.id), Object.keys(canonicalTargets));

    for (const tuning of Tunings.list) {
        const expected = canonicalTargets[tuning.id];
        assert.deepEqual(tuning.targets, expected.map(([name]) => name), `${tuning.id} targets`);

        for (const [name, hz] of expected) {
            const actual = Tunings.hzOf(name);
            assert.ok(Math.abs(actual - hz) < 0.01, `${tuning.id} ${name} was ${actual} Hz, expected ${hz} Hz`);
        }
    }
});

// A preset transposed by a whole octave is the failure the literals above
// exist for, so it is worth proving they actually catch one.
test("the canonical table rejects a preset moved by an octave", () => {
    const bass5 = canonicalTargets.bass5.map(([name]) => name);
    const shifted = bass5.map(name => Tunings.nameOf(Tunings.midiOf(name) + 12));
    assert.notDeepEqual(shifted, bass5);
    assert.deepEqual(shifted, ["B1", "E2", "A2", "D3", "G3"]);
});

// Note names are the storage format, so every preset entry has to be a name the
// module can actually resolve. A typo here would otherwise surface as a blank
// string in the panel's target strip rather than as a failure.
test("every preset target is a resolvable note name", () => {
    let checked = 0;
    for (const tuning of Tunings.list) {
        for (const target of tuning.targets) {
            assert.notEqual(Tunings.midiOf(target), null, `${tuning.id} has unresolvable target ${target}`);
            assert.equal(Tunings.nameOf(Tunings.midiOf(target)), target, `${tuning.id} target ${target} is not canonically spelled`);
            checked++;
        }
    }
    assert.ok(checked > 0, "no targets were checked");
});

test("byId finds every preset and falls back to chromatic", () => {
    for (const tuning of Tunings.list) {
        assert.equal(Tunings.byId(tuning.id), tuning);
    }
    assert.equal(Tunings.byId("no-such-tuning").id, "chromatic");
    assert.equal(Tunings.byId(undefined).id, "chromatic");
});

test("chromatic mode reports the nearest semitone", () => {
    const chromatic = Tunings.byId("chromatic");
    for (const name of ["B0", "E1", "E2", "A2", "D3", "A4", "E4"]) {
        const resolved = Tunings.resolve(Tunings.hzOf(name), chromatic);
        assert.equal(resolved.name, name);
        assert.ok(Math.abs(resolved.cents) < 0.01, `${name} read ${resolved.cents} cents off`);
        assert.equal(resolved.targetIndex, -1);
    }
});

test("chromatic mode reports the deviation of a detuned input", () => {
    const resolved = Tunings.resolve(detune(82.4069, -30), Tunings.byId("chromatic"));
    assert.equal(resolved.name, "E2");
    assert.ok(Math.abs(resolved.cents + 30) < 0.1, `read ${resolved.cents} cents`);
    assert.equal(resolved.targetIndex, -1);
});

test("guitar mode snaps a badly flat low E to E2, not to D#2", () => {
    const resolved = Tunings.resolve(detune(82.4069, -40), Tunings.byId("guitar"));
    assert.equal(resolved.name, "E2");
    assert.ok(Math.abs(resolved.cents + 40) < 0.1, `read ${resolved.cents} cents`);
    assert.equal(resolved.targetIndex, 0);
});

// The -40 cent case above is also what plain semitone rounding would answer, so
// it does not on its own prove the nearest-target search. A whole tone flat
// does: chromatic hears D2, and guitar mode still has to name the string the
// player meant.
test("guitar mode still names E2 for a string a whole tone flat", () => {
    const flat = detune(82.4069, -200);
    assert.equal(Tunings.resolve(flat, Tunings.byId("chromatic")).name, "D2");

    const resolved = Tunings.resolve(flat, Tunings.byId("guitar"));
    assert.equal(resolved.name, "E2");
    assert.ok(Math.abs(resolved.cents + 200) < 0.1, `read ${resolved.cents} cents`);
    assert.equal(resolved.targetIndex, 0);
});

test("bass4 mode never names a note outside its own targets", () => {
    const bass4 = Tunings.byId("bass4");
    for (let hz = 30; hz <= 350; hz += 0.25) {
        const resolved = Tunings.resolve(hz, bass4);
        assert.ok(bass4.targets.includes(resolved.name), `${hz} Hz resolved to ${resolved.name}`);
        assert.equal(bass4.targets[resolved.targetIndex], resolved.name);
    }
});

test("resolve returns null when there is no pitch", () => {
    for (const hz of [0, -1, -82.4069, NaN, Infinity, null, undefined]) {
        assert.equal(Tunings.resolve(hz, Tunings.byId("guitar")), null, `${String(hz)} should not resolve`);
    }
});

