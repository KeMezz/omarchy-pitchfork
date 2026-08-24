// The tuning model for the panel: which instruments exist, which tuning
// references apply to each, the pitch-notation arithmetic, and the note the
// readout should show for a detected frequency.
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

// How far a drop tuning lowers the bottom string: a whole tone, which is what
// "drop" means on every instrument that has the tuning.
var DROP_SEMITONES = -2;

// -- the two axes -----------------------------------------------------------
//
// A family is what is in the player's hands, an instrument is a set of
// strings, and a tuning reference is what is done to that set. Splitting the
// last two is what keeps the menus short: a flat list would need one entry per
// instrument-and-reference pair, and adding half-step down to five instruments
// would mean five new rows rather than one.
//
// The chromatic family is the case with nothing below it: no instrument, so no
// reference, so no string set -- and a readout that names whichever semitone
// is nearest.

var families = [
    {
        id: "chromatic",
        label: "Chromatic"
    },
    {
        id: "guitar",
        label: "Guitar"
    },
    {
        id: "bass",
        label: "Bass"
    }
];

// Strings are stored low to high as note names rather than frequencies.
// Frequencies would be a table of magic numbers that no reader can check
// against a fretboard, and they would hide the octave -- the single likeliest
// thing to get wrong here, and the thing the tests assert hardest.
//
// Chromatic is not in this table. It is a family with no instruments, because
// naming the nearest semitone needs no string set to compare against -- so the
// panel has nothing to ask about and hides both rows.
var instruments = [
    {
        id: "guitar6",
        label: "6-string guitar",
        family: "guitar",
        strings: ["E2", "A2", "D3", "G3", "B3", "E4"]
    },
    {
        id: "guitar7",
        label: "7-string guitar",
        family: "guitar",
        strings: ["B1", "E2", "A2", "D3", "G3", "B3", "E4"]
    },
    {
        id: "bass4",
        label: "4-string bass",
        family: "bass",
        strings: ["E1", "A1", "D2", "G2"]
    },
    {
        id: "bass5",
        label: "5-string bass",
        family: "bass",
        strings: ["B0", "E1", "A1", "D2", "G2"]
    },
    {
        id: "bass6",
        label: "6-string bass",
        family: "bass",
        strings: ["B0", "E1", "A1", "D2", "G2", "C3"]
    }
];

// A tuning reference is a transform over the instrument's strings, not a
// second table of note names. `shift` moves every string; `drop` moves only
// the bottom one; `voicing` replaces the set outright, for the named
// alternates that are not a transposition of anything.
var tunings = [
    {
        id: "standard",
        label: "Standard"
    },
    {
        id: "drop",
        // Filled in per instrument: dropping a 6-string guitar gives Drop D
        // and a 7-string gives Drop A, and naming the resulting note is the
        // only way the row says which.
        label: "Drop",
        drop: true
    },
    {
        id: "half-down",
        label: "Half-step down",
        shift: -1
    },
    {
        id: "full-down",
        label: "Full-step down",
        shift: -2
    },
    {
        id: "dadgad",
        label: "DADGAD",
        voicing: ["D2", "A2", "D3", "G3", "A3", "D4"],
        only: ["guitar6"]
    }
];

// Stored settings from before the instrument and reference axes were split.
// The panel used one flat preset id, and dropping these would silently reset a
// player's choice on upgrade.
var legacyTunings = {
    "chromatic": {
        family: "chromatic",
        instrument: "",
        tuning: ""
    },
    "guitar": {
        family: "guitar",
        instrument: "guitar6",
        tuning: "standard"
    },
    "drop-d": {
        family: "guitar",
        instrument: "guitar6",
        tuning: "drop"
    },
    "dadgad": {
        family: "guitar",
        instrument: "guitar6",
        tuning: "dadgad"
    },
    "half-down": {
        family: "guitar",
        instrument: "guitar6",
        tuning: "half-down"
    },
    "bass4": {
        family: "bass",
        instrument: "bass4",
        tuning: "standard"
    },
    "bass5": {
        family: "bass",
        instrument: "bass5",
        tuning: "standard"
    }
};

// Chromatic was briefly an instrument inside every family rather than a family
// of its own. Only a stored record can still say so.
var CHROMATIC_AS_INSTRUMENT = "chromatic";

// Chromatic asks nothing, so it is what a first run lands on -- and it is what
// the panel has always opened with. DEFAULT_TUNING is the reference an
// instrument falls back to, not part of the default triple: chromatic has no
// instrument for a reference to act on.
var DEFAULT_FAMILY = "chromatic";
var DEFAULT_TUNING = "standard";

// -- helpers ----------------------------------------------------------------

// Fractional MIDI number, which is the space the rest of the module measures
// in: a semitone is one unit and a cent is a hundredth of one.
function midiFromHz(hz) {
    return 69 + 12 * Math.log(hz / CONCERT_A_HZ) / Math.LN2;
}

function asString(value) {
    return String(value === null || value === undefined ? "" : value);
}

// -- notation ---------------------------------------------------------------

// Flats are accepted on input only so a hand-written preset or a stored value
// still resolves; everything this module produces is spelled with sharps.
function midiOf(name) {
    var match = /^([A-Ga-g])([#b]?)(-?\d+)$/.exec(asString(name).trim());
    if (!match)
        return null;

    var offset = letterOffsets[match[1].toUpperCase()];
    var accidental = match[2] === "#" ? 1 : (match[2] === "b" ? -1 : 0);
    return 12 * (parseInt(match[3], 10) + 1) + offset + accidental;
}

// Numbers only. Coercing would make nameOf(null) answer "C-1", because
// Number(null) is 0 -- a note name for the absence of one, which every caller
// that chains off midiOf would then propagate instead of failing.
function nameOf(midi) {
    if (typeof midi !== "number" || !isFinite(midi))
        return null;

    var rounded = Math.round(midi);
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

// The pitch class alone, which is how a drop tuning names itself: "Drop D",
// never "Drop D2".
function pitchClassOf(name) {
    var spelled = nameOf(midiOf(name));
    return spelled === null ? "" : spelled.replace(/-?\d+$/, "");
}

// A note name moved by whole semitones, or null if the input was not a note.
function transpose(name, semitones) {
    var midi = midiOf(name);
    if (midi === null)
        return null;

    return nameOf(midi + semitones);
}

// -- lookup -----------------------------------------------------------------

function familyById(id) {
    var wanted = asString(id);
    for (var index = 0; index < families.length; index++) {
        if (families[index].id === wanted)
            return families[index];

    }
    return null;
}

function instrumentById(id) {
    var wanted = asString(id);
    for (var index = 0; index < instruments.length; index++) {
        if (instruments[index].id === wanted)
            return instruments[index];

    }
    return null;
}

function tuningById(id) {
    var wanted = asString(id);
    for (var index = 0; index < tunings.length; index++) {
        if (tunings[index].id === wanted)
            return tunings[index];

    }
    return null;
}

// -- applicability ----------------------------------------------------------

// A reference needs strings to act on, and a voicing lists the instruments it
// was written for.
function tuningApplies(instrument, tuning) {
    if (!instrument || !tuning || instrument.strings.length === 0)
        return false;

    if (tuning.only)
        return tuning.only.indexOf(instrument.id) !== -1;

    return true;
}

// What the reference row should say for this instrument. Only drop varies.
function tuningLabel(instrumentId, tuningId) {
    var instrument = instrumentById(instrumentId);
    var tuning = tuningById(tuningId);
    if (!tuning)
        return "";

    if (tuning.drop !== true || !instrument || instrument.strings.length === 0)
        return tuning.label;

    var dropped = transpose(instrument.strings[0], DROP_SEMITONES);
    var letter = dropped === null ? "" : pitchClassOf(dropped);
    return letter.length > 0 ? tuning.label + " " + letter : tuning.label;
}

// -- menus ------------------------------------------------------------------

// Both of these return { value, label } rows, which is the shape the kit's
// dropdown and button group both consume, so the panel never reshapes a list.

// Empty for chromatic, which the panel reads as "there is nothing to choose"
// and hides the row entirely.
function instrumentOptions(familyId) {
    var wanted = asString(familyId);
    var rows = [];
    for (var index = 0; index < instruments.length; index++) {
        if (instruments[index].family !== wanted)
            continue;

        rows.push({
            value: instruments[index].id,
            label: instruments[index].label
        });
    }
    return rows;
}

// Empty when there is no instrument, or when nothing applies to it. A dropdown
// with nothing in it is worse than no dropdown, so the panel hides the row.
function tuningOptions(instrumentId) {
    var instrument = instrumentById(instrumentId);
    var rows = [];
    for (var index = 0; index < tunings.length; index++) {
        if (!tuningApplies(instrument, tunings[index]))
            continue;

        rows.push({
            value: tunings[index].id,
            label: tuningLabel(instrumentId, tunings[index].id)
        });
    }
    return rows;
}

function familyOptions() {
    var rows = [];
    for (var index = 0; index < families.length; index++)
        rows.push({
            value: families[index].id,
            label: families[index].label
        });
    return rows;
}

// -- string sets ------------------------------------------------------------

// The notes the strip shows and the readout snaps to, low string first. Empty
// when there is no instrument, which is the chromatic family and is what makes
// the readout name the nearest semitone instead. A reference that does not
// apply yields the instrument's own strings rather than an error, so a stale
// combination degrades to something tunable.
function stringsFor(instrumentId, tuningId) {
    var instrument = instrumentById(instrumentId);
    if (!instrument || instrument.strings.length === 0)
        return [];

    var tuning = tuningById(tuningId);
    if (!tuningApplies(instrument, tuning))
        return instrument.strings.slice();

    if (tuning.voicing)
        return tuning.voicing.slice();

    var moved = [];
    for (var index = 0; index < instrument.strings.length; index++) {
        var semitones = 0;
        if (tuning.shift)
            semitones = tuning.shift;

        if (tuning.drop === true && index === 0)
            semitones = DROP_SEMITONES;

        var note = transpose(instrument.strings[index], semitones);
        // An unparseable string degrades to the rest of the set rather than
        // taking the whole instrument down with it.
        if (note !== null)
            moved.push(note);

    }
    return moved;
}

// -- stored settings --------------------------------------------------------

// Turns anything that was on disk into a triple the panel can use. Every
// branch lands on a valid combination, so no stored value -- an id from an
// older version, a hand-edited file, a half-written object -- can leave the
// panel in a state it cannot tune.
//
// The family leads, because it is the one choice the panel always shows: the
// instrument and the reference are only asked about when the family has them.
// The sole exception is the historical `instrument: "chromatic"` sentinel,
// which was itself the old spelling of the family choice.
function normalize(stored) {
    var raw = (stored && typeof stored === "object") ? stored : {};
    var instrument = instrumentById(raw.instrument);
    var family = familyById(raw.family);

    // Chromatic was briefly stored as an instrument. That sentinel describes
    // the whole mode and must win before a neighbouring pre-split tuning id is
    // considered; otherwise a stale `bass5` or `dadgad` can migrate the record
    // back into an instrument family.
    if (asString(raw.instrument) === CHROMATIC_AS_INSTRUMENT)
        family = familyById("chromatic");

    if (!family) {
        // The pre-split schema kept one flat preset id under `tuning`.
        // Do not let Object.prototype names masquerade as entries. JSON can
        // quite legitimately contain "__proto__", "constructor", or
        // "toString", and indexing the ordinary object directly would return
        // an inherited object/function instead of an absent preset.
        var legacyKey = asString(raw.tuning);
        var legacy = Object.prototype.hasOwnProperty.call(legacyTunings, legacyKey) ? legacyTunings[legacyKey] : null;
        if (legacy && !instrument)
            return {
                family: legacy.family,
                instrument: legacy.instrument,
                tuning: legacy.tuning
            };

        family = instrument ? familyById(instrument.family) : familyById(DEFAULT_FAMILY);
    }

    var rows = instrumentOptions(family.id);
    if (rows.length === 0)
        return {
            family: family.id,
            instrument: "",
            tuning: ""
        };

    var keeping = instrument && instrument.family === family.id;
    var instrumentId = keeping ? instrument.id : rows[0].value;
    var tuningId = tuningApplies(instrumentById(instrumentId), tuningById(raw.tuning)) ? asString(raw.tuning) : DEFAULT_TUNING;
    return {
        family: family.id,
        instrument: instrumentId,
        tuning: tuningId
    };
}

// -- resolution -------------------------------------------------------------

// What the panel calls once per reading. Returns the name the big readout
// shows, the signed cents deviation from it, and which string of the set it
// belongs to, or null when there is no pitch to resolve.
//
// Cents are left unrounded. The readout rounds for display, and the needle
// wants the fraction.
function resolve(hz, targets) {
    var value = Number(hz);
    if (!isFinite(value) || value <= 0)
        return null;

    var detected = midiFromHz(value);
    var notes = targets && targets.length ? targets : [];
    var bestIndex = -1;
    var bestCents = 0;
    for (var index = 0; index < notes.length; index++) {
        var midi = midiOf(notes[index]);
        // An unparseable target degrades to the rest of the set rather than
        // taking the whole reading down with it.
        if (midi === null)
            continue;

        var cents = (detected - midi) * 100;
        if (bestIndex === -1 || Math.abs(cents) < Math.abs(bestCents)) {
            bestIndex = index;
            bestCents = cents;
        }
    }

    // The nearest string rather than the nearest semitone, which is the point
    // of choosing an instrument: a string a whole tone flat still reports the
    // string the player meant, so the direction to turn the peg is never
    // ambiguous.
    if (bestIndex !== -1)
        return {
            name: nameOf(midiOf(notes[bestIndex])),
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
// `Tunings.instruments` and `Tunings.resolve(...)` already work there. Node
// needs a single object, which is all this aggregate is.
var Tunings = {
    CONCERT_A_HZ: CONCERT_A_HZ,
    DROP_SEMITONES: DROP_SEMITONES,
    DEFAULT_FAMILY: DEFAULT_FAMILY,
    DEFAULT_TUNING: DEFAULT_TUNING,
    families: families,
    instruments: instruments,
    tunings: tunings,
    familyById: familyById,
    instrumentById: instrumentById,
    tuningById: tuningById,
    tuningApplies: tuningApplies,
    tuningLabel: tuningLabel,
    familyOptions: familyOptions,
    instrumentOptions: instrumentOptions,
    tuningOptions: tuningOptions,
    stringsFor: stringsFor,
    normalize: normalize,
    midiOf: midiOf,
    nameOf: nameOf,
    hzOf: hzOf,
    pitchClassOf: pitchClassOf,
    transpose: transpose,
    resolve: resolve
};

if (typeof module !== "undefined")
    module.exports = Tunings;
