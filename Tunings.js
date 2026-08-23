// Tunings for the tuner panel: the preset list, pitch-notation arithmetic, and
// the note the readout should show for a detected frequency.
//
// This file is a plain JavaScript module so that both worlds can load it. QML
// takes it as a JS resource with `import "Tunings.js" as Tunings`, and
// `tests/tunings.test.mjs` requires it under plain node. That rules out
// `.pragma library`, which QML would accept and node would reject as a syntax
// error, so do not add one.

// Twelve-tone names indexed by pitch class, sharps only. A tuner never needs
// the flat spelling: the target is a string, not a key signature.
var noteNames = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

// Semitones above C for each letter, so a name can be read without a table
// lookup per accidental.
var letterOffsets = {
    "C": 0,
    "D": 2,
    "E": 4,
    "F": 5,
    "G": 7,
    "A": 9,
    "B": 11
};

// Concert pitch. Fixed rather than configurable: the panel offered an
// adjustable A4 and it was removed as something nobody reaches for outside
// ensemble work. Note that no measurement could tell the two apart anyway --
// a string 8 cents sharp at A4=440 and a string in tune at A4=442 are the same
// frequency, so which one it is lives in the player's intent, not the signal.
var CONCERT_A_HZ = 440;

// Targets are stored as note names rather than frequencies. Frequencies would
// be a table of magic numbers that no reader can check against a fretboard,
// and they would hide the octave -- which is the single likeliest thing to get
// wrong here, and the thing the tests assert hardest.
var list = [
    {
        id: "chromatic",
        label: "Chromatic",
        targets: []
    },
    {
        id: "guitar",
        label: "Guitar standard",
        targets: ["E2", "A2", "D3", "G3", "B3", "E4"]
    },
    {
        id: "drop-d",
        label: "Drop D",
        targets: ["D2", "A2", "D3", "G3", "B3", "E4"]
    },
    {
        id: "dadgad",
        label: "DADGAD",
        targets: ["D2", "A2", "D3", "G3", "A3", "D4"]
    },
    {
        id: "half-down",
        label: "Half-step down",
        targets: ["D#2", "G#2", "C#3", "F#3", "A#3", "D#4"]
    },
    {
        id: "bass4",
        label: "Bass 4-string",
        targets: ["E1", "A1", "D2", "G2"]
    },
    {
        id: "bass5",
        label: "Bass 5-string",
        targets: ["B0", "E1", "A1", "D2", "G2"]
    }
];

// -- helpers ----------------------------------------------------------------

// Fractional MIDI number, which is the space the rest of the module measures
// in: a semitone is one unit and a cent is a hundredth of one.
function midiFromHz(hz) {
    return 69 + 12 * Math.log(hz / CONCERT_A_HZ) / Math.LN2;
}

// -- notation ---------------------------------------------------------------

// Flats are accepted on input only so a hand-written preset or a stored value
// still resolves; everything this module produces is spelled with sharps.
function midiOf(name) {
    var match = /^([A-Ga-g])([#b]?)(-?\d+)$/.exec(String(name === null || name === undefined ? "" : name).trim());
    if (!match)
        return null;

    var offset = letterOffsets[match[1].toUpperCase()];
    var accidental = match[2] === "#" ? 1 : (match[2] === "b" ? -1 : 0);
    return 12 * (parseInt(match[3], 10) + 1) + offset + accidental;
}

function nameOf(midi) {
    var value = Number(midi);
    if (!isFinite(value))
        return null;

    var rounded = Math.round(value);
    // The remainder of a negative dividend is negative in JavaScript, so the
    // pitch class is folded back into range before it indexes the table.
    var pitchClass = ((rounded % 12) + 12) % 12;
    return noteNames[pitchClass] + (Math.floor(rounded / 12) - 1);
}

function hzOf(name) {
    var midi = midiOf(name);
    if (midi === null)
        return null;

    return CONCERT_A_HZ * Math.pow(2, (midi - 69) / 12);
}

// -- lookup -----------------------------------------------------------------

// Falls back to the chromatic entry so a stored id from an older version, or
// from a typo, can never leave the panel without a tuning to show.
function byId(id) {
    var wanted = String(id === null || id === undefined ? "" : id);
    for (var index = 0; index < list.length; index++) {
        if (list[index].id === wanted)
            return list[index];

    }
    return list[0];
}

// -- resolution -------------------------------------------------------------

// What the panel calls once per reading. Returns the name the big readout
// shows, the signed cents deviation from it, and which target of the tuning it
// belongs to, or null when there is no pitch to resolve.
//
// Cents are left unrounded. The readout rounds for display, and the needle
// wants the fraction.
function resolve(hz, tuning) {
    var value = Number(hz);
    if (!isFinite(value) || value <= 0)
        return null;

    var detected = midiFromHz(value);
    var targets = tuning && tuning.targets ? tuning.targets : [];
    var bestIndex = -1;
    var bestCents = 0;
    for (var index = 0; index < targets.length; index++) {
        var midi = midiOf(targets[index]);
        // An unparseable target degrades to the rest of the preset rather
        // than taking the whole reading down with it.
        if (midi === null)
            continue;

        var cents = (detected - midi) * 100;
        if (bestIndex === -1 || Math.abs(cents) < Math.abs(bestCents)) {
            bestIndex = index;
            bestCents = cents;
        }
    }

    // The nearest target rather than the nearest semitone, which is the point
    // of choosing a tuning: a string a whole tone flat still reports the
    // string the player meant, so the direction to turn the peg is never
    // ambiguous.
    if (bestIndex !== -1)
        return {
            name: nameOf(midiOf(targets[bestIndex])),
            cents: bestCents,
            targetIndex: bestIndex
        };

    var nearest = Math.round(detected);
    return {
        name: nameOf(nearest),
        cents: (detected - nearest) * 100,
        targetIndex: -1
    };
}

// QML puts every top-level declaration on the import namespace, so
// `Tunings.list` and `Tunings.resolve(...)` already work there. Node needs a
// single object, which is all this aggregate is.
var Tunings = {
    list: list,
    byId: byId,
    midiOf: midiOf,
    nameOf: nameOf,
    hzOf: hzOf,
    resolve: resolve
};

if (typeof module !== "undefined")
    module.exports = Tunings;
