import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Pipewire
import "Tunings.js" as Tunings
import qs.Commons
import qs.Ui

Panel {
    id: root

    // Everything the panel shows derives from these three. The helper is the
    // only writer; the UI never guesses a value the detector did not send.
    property real detectedHz: 0
    property real confidence: 0
    property real level: 0
    property string detectorSource: ""
    property string detectorError: ""
    property bool detectorStopped: false
    property var anchorItem: null
    property var hostWidget: null
    readonly property bool hasSignal: root.level >= 0.004
    // Process wants a filesystem path, not the file:// URL resolvedUrl returns.
    readonly property string detectorPath: Qt.resolvedUrl("scripts/pitch-detect.py").toString().replace(/^file:\/\//, "")
    // The last pitch the detector reported. A plucked string dies while the
    // player is still looking at the fretboard, and a readout that blanks the
    // instant the note decays is one they never get to read.
    property real heldHz: 0
    readonly property bool holding: root.detectedHz <= 0 && root.heldHz > 0 && hold.running
    // A live pitch always wins, so the hold can only ever extend a stale
    // reading and never delays a fresh one by so much as a frame.
    readonly property real displayHz: root.detectedHz > 0 ? root.detectedHz : (root.holding ? root.heldHz : 0)
    // Opacity is the only thing that separates a held reading from a live one,
    // so everything the reading drives carries it.
    readonly property real readingOpacity: root.holding ? 0.45 : 1
    property string selectedTuning: "chromatic"
    // Which of the current tuning's targets have been played in tune since the
    // panel opened. Assigned rather than mutated in place, because QML only
    // notifies a var property on assignment.
    property var checkedTargets: []
    readonly property var tuning: Tunings.byId(root.selectedTuning)
    // Chromatic is first in Tunings.list and stays first here, so the tuning
    // that checks nothing off is the one a reader lands on.
    readonly property var tuningOptions: {
        var options = [];
        for (var index = 0; index < Tunings.list.length; index++) {
            options.push({
                "value": Tunings.list[index].id,
                "label": Tunings.list[index].label
            });
        }
        return options;
    }
    // Tunings.js owns every pitch calculation the panel makes. One
    // implementation is the point: a readout and a target list that derive the
    // same note two different ways will eventually disagree about it.
    readonly property var reading: Tunings.resolve(root.displayHz, root.tuning)
    readonly property string noteLabel: root.reading ? root.reading.name : "--"
    // Left unrounded for the needle, which wants the fraction; only the text
    // beneath it rounds.
    readonly property real centsExact: root.reading ? root.reading.cents : 0
    readonly property int cents: Math.round(root.centsExact)
    readonly property int targetIndex: root.reading ? root.reading.targetIndex : -1
    // 5 cents is the band where a guitar or bass reads as in tune by ear.
    // This one covers a held reading too, because the panel dims what it is
    // holding and the colour is read together with that opacity.
    readonly property bool readingInTune: root.displayHz > 0 && Math.abs(root.centsExact) <= 5
    // What the bar widget consumes, and live-only on purpose: the fork has no
    // opacity to dim, so an accent held after the note died would claim a
    // string is in tune when nothing is sounding.
    readonly property bool inTune: root.detectedHz > 0 && root.readingInTune
    // The target the settle timer is counting for, or -1 when nothing is being
    // held steady. inTune excludes a held reading, so the strip records that a
    // string was played in tune rather than that its last value is still up.
    readonly property int settlingIndex: root.inTune && root.targetIndex >= 0 ? root.targetIndex : -1
    readonly property string statusText: {
        if (root.detectorError.length > 0)
            return root.detectorError;

        // A detector that exited stays exited while the panel is open, so say
        // so rather than showing a silence that looks like a quiet room.
        if (root.detectorStopped)
            return "Detector stopped. Close and reopen to retry.";

        if (root.displayHz > 0)
            return "";

        return root.hasSignal ? "Listening for a steady pitch." : "No signal. Play a note.";
    }
    // Empty when there is nothing to report, so the bar widget can decide what
    // an idle tuner says rather than being handed a label.
    readonly property string barReadout: root.detectedHz > 0 ? root.noteLabel + " " + (root.cents > 0 ? "+" : "") + root.cents + "¢" : ""
    // -- input selection ----------------------------------------------------
    // Empty means the PipeWire default source, which is what the detector does
    // with no --target.
    property string selectedTarget: ""
    property bool detectorArmed: true
    readonly property string statePath: Quickshell.env("HOME") + "/.config/omarchy-pitchfork/settings.json"
    readonly property var nodes: Pipewire.nodes ? Pipewire.nodes.values : []
    readonly property var defaultSource: Pipewire.defaultAudioSource
    // Naming what "System default" currently resolves to, so the safe choice
    // is not also the opaque one.
    readonly property string defaultSourceLabel: root.defaultSource ? root.friendlyLabel(root.defaultSource.nickname || root.defaultSource.description || root.defaultSource.name || "") : ""
    // Deliberately never reads node.properties. That is invalid until a node
    // is bound, and the audio panel documents that reading it while capture
    // streams appear can destabilise Quickshell's Pipewire service -- and this
    // plugin creates a capture stream every time the panel opens.
    readonly property var captureSources: {
        var found = [];
        for (var index = 0; index < root.nodes.length; index++) {
            var node = root.nodes[index];
            if (!node || node.isSink || node.isStream)
                continue;

            if (!node.audio && String(node.type || "").indexOf("Source") === -1)
                continue;

            if (String(node.name || "") === "quickshell")
                continue;

            found.push(node);
        }
        return found;
    }
    readonly property bool selectionAvailable: {
        if (root.selectedTarget.length === 0)
            return true;

        for (var index = 0; index < root.captureSources.length; index++) {
            if (String(root.captureSources[index].name || "") === root.selectedTarget)
                return true;

        }
        return false;
    }
    readonly property var detectorCommand: root.selectedTarget.length > 0 ? ["python3", root.detectorPath, "--target", root.selectedTarget] : ["python3", root.detectorPath]
    // The default entry is first and always present, so there is a way back
    // from a device that has been unplugged.
    readonly property var inputOptions: {
        var options = [{
            "value": "",
            "label": root.defaultSourceLabel.length > 0 ? "System default (" + root.defaultSourceLabel + ")" : "System default"
        }];
        for (var index = 0; index < root.captureSources.length; index++) {
            var node = root.captureSources[index];
            options.push({
                "value": String(node.name || ""),
                "label": root.sourceLabel(node)
            });
        }
        return options;
    }

    function open() {
        root.controller.show();
    }

    function close() {
        root.controller.hide();
    }

    function toggle() {
        if (root.opened)
            root.close();
        else
            root.open();
    }

    function switchPanel(direction) {
        if (root.bar && typeof root.bar.switchPanelFrom === "function")
            return root.bar.switchPanelFrom(root.hostWidget || root, direction);

        return false;
    }

    function applyReading(line) {
        var text = String(line || "").trim();
        if (text.length === 0)
            return ;

        try {
            var reading = JSON.parse(text);
            root.detectedHz = Number(reading.hz) || 0;
            root.confidence = Number(reading.confidence) || 0;
            root.level = Number(reading.level) || 0;
            root.detectorSource = String(reading.source || "");
            root.detectorError = String(reading.error || "");
            root.detectorStopped = false;
            // Restarting the hold here rather than on a binding keeps the
            // window measured from the last real reading, which is the only
            // moment that says anything about the instrument.
            if (root.detectedHz > 0) {
                root.heldHz = root.detectedHz;
                hold.restart();
            }
        } catch (parseError) {
            root.detectorError = "unreadable detector output";
        }
    }

    // ALSA descriptions front-load the controller and leave the part that
    // actually distinguishes two inputs -- "Digital Microphone" versus
    // "Stereo Microphone" -- at the very end, where a narrow panel elides it.
    function friendlyLabel(raw) {
        var label = String(raw || "").trim();
        var tail = label.replace(/^.*\)\s*/, "");
        if (tail.length > 0)
            label = tail;

        return label.replace(/^Built-?in Audio\s+/i, "");
    }

    function sourceLabel(node) {
        if (!node)
            return "Unknown";

        // No monitor case to handle: PipeWire publishes no monitor nodes, so
        // this list is capture devices only. The `<sink>.monitor` names that
        // pactl reports -- and that pitch-detect.py --list-inputs therefore
        // shows -- are a PulseAudio compatibility invention, not nodes
        // Pipewire.nodes can return.
        return root.friendlyLabel(node.nickname || node.description || node.name || "Unknown");
    }

    function selectTarget(name) {
        var next = String(name || "");
        if (next === root.selectedTarget)
            return ;

        root.selectedTarget = next;
        root.persistSettings();
        root.restartDetector();
    }

    // Neither the tuning nor the reference reaches the detector: pitch is
    // measured in hertz and only interpreted here, so changing either one
    // must not interrupt capture.
    function selectTuning(id) {
        var next = Tunings.byId(id).id;
        if (next === root.selectedTuning)
            return ;

        root.selectedTuning = next;
        root.beginFreshPass();
        root.persistSettings();
    }

    // Dropping running and raising it again in one block coalesces into no
    // change, and Quickshell does not restart a Process that exited while
    // running still evaluates true. So disarm now and re-arm on a later tick.
    function restartDetector() {
        root.clearSignal();
        root.detectorError = "";
        root.detectorStopped = false;
        root.detectorArmed = false;
        rearm.restart();
    }

    function persistSettings() {
        stateFile.setText(JSON.stringify({
            "target": root.selectedTarget,
            "tuning": root.selectedTuning
        }, null, 2) + "\n");
    }

    // Writes the properties directly rather than going through the select
    // helpers, which would persist the file back and restart the detector
    // while it is still being read.
    function loadSettings(raw) {
        try {
            var stored = JSON.parse(String(raw || "{}"));
            root.selectedTarget = String(stored.target || "");
            // Tunings.byId falls back to chromatic, so an id from an older
            // version cannot leave the panel without a tuning.
            root.selectedTuning = Tunings.byId(stored.tuning).id;
        } catch (parseError) {
            root.selectedTarget = "";
            root.selectedTuning = "chromatic";
        }
    }

    function markTarget(index) {
        if (index < 0 || root.checkedTargets.indexOf(index) !== -1)
            return ;

        root.checkedTargets = root.checkedTargets.concat([index]);
    }

    function clearTargets() {
        root.checkedTargets = [];
    }

    // A fresh pass over the strings. Clearing the marks alone is not enough:
    // the settle timer may already be part-way toward crediting a string, and
    // onSettlingIndexChanged cannot see an event that leaves the index
    // numerically unchanged -- switching Guitar standard to Drop D keeps
    // index 1 on A2. Restarting here makes the dwell start over, so a string
    // is only ever credited for time held under the tuning and reference now
    // in force.
    function beginFreshPass() {
        root.clearTargets();
        if (root.settlingIndex >= 0)
            settle.restart();
        else
            settle.stop();
    }

    function clearSignal() {
        root.detectedHz = 0;
        root.confidence = 0;
        root.level = 0;
        root.heldHz = 0;
        hold.stop();
    }

    function resetDetector() {
        root.clearSignal();
        root.detectorSource = "";
        root.detectorError = "";
        root.detectorStopped = false;
    }

    moduleName: "dev.hyeongjin.pitchfork"
    manageIpc: false
    // Opening the panel is the retry: it restarts the detector, so a stale
    // error from the previous run must not survive into the new one. The
    // strip starts empty for the same reason -- a fresh session is a fresh
    // pass over the strings.
    onOpenedChanged: {
        if (root.opened) {
            root.resetDetector();
            root.beginFreshPass();
        }
    }
    // Restart rather than let the timer coast. Moving to the next string
    // mid-count must not credit it with the previous string's dwell.
    onSettlingIndexChanged: {
        if (root.settlingIndex >= 0)
            settle.restart();
        else
            settle.stop();
    }

    PwObjectTracker {
        objects: root.captureSources
    }

    // The detector only runs while the panel is open. A tuner that keeps a
    // capture stream alive in the background is a microphone nobody asked for.
    Process {
        id: detector

        running: root.opened && root.detectorArmed
        command: root.detectorCommand
        // Keep whatever error the detector reported on its way out; it exits
        // immediately after emitting one, and it is the only diagnostic the
        // panel can show.
        onExited: {
            root.clearSignal();
            root.detectorStopped = true;
        }

        stdout: SplitParser {
            onRead: function(line) {
                root.applyReading(line);
            }
        }

    }

    Timer {
        id: rearm

        interval: 120
        onTriggered: root.detectorArmed = true
    }

    // How long a dead note stays on screen. Long enough to look down at the
    // fretboard and back, short enough that it cannot be mistaken for a note
    // still sounding.
    Timer {
        id: hold

        interval: 1500
    }

    // Half a second in tune is a stop the player made, not a value the peg
    // swept through on the way somewhere else.
    Timer {
        id: settle

        interval: 500
        onTriggered: root.markTarget(root.settlingIndex)
    }

    // FileView will not create the parent directory, so this runs once.
    Process {
        id: ensureStateDir

        running: true
        command: ["mkdir", "-p", Quickshell.env("HOME") + "/.config/omarchy-pitchfork"]
    }

    FileView {
        id: stateFile

        path: root.statePath
        atomicWrites: true
        printErrors: false
        onLoaded: root.loadSettings(text())
        // Absent on first run, which is not a failure: no stored settings mean
        // the PipeWire default input and chromatic.
        onLoadFailed: root.loadSettings("{}")
    }

    KeyboardPanel {
        id: panel

        anchorItem: root.anchorItem
        owner: root.hostWidget || root
        bar: root.bar
        open: root.opened
        focusTarget: keyCatcher
        // Wide enough for "System default (<device>)" to sit on one line. The
        // resolved name is the point of that row; eliding it defeats it.
        contentWidth: panel.fittedContentWidth(Style.space(380))
        contentHeight: panel.fittedContentHeight(content.implicitHeight)

        PanelKeyCatcher {
            id: keyCatcher

            anchors.fill: parent
            // Three controls can own the keyboard, and any of them would have
            // j/k and the digits double-driving the panel cursor.
            blocked: inputDropdown.popupOpen || tuningDropdown.popupOpen
            onCloseRequested: root.close()
            onTabRequested: function(direction) {
                root.switchPanel(direction);
            }

            Column {
                id: content

                width: parent.width
                spacing: Style.space(8)

                Text {
                    width: parent.width
                    text: "Pitchfork"
                    color: root.barForeground
                    font.family: root.bar ? root.bar.fontFamily : Style.font.family
                    font.pixelSize: Style.font.subtitle
                    font.bold: true
                    wrapMode: Text.WordWrap
                }

                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: root.noteLabel
                    color: root.readingInTune ? Color.accent : root.barForeground
                    opacity: root.readingOpacity
                    font.family: root.bar ? root.bar.fontFamily : Style.font.family
                    font.pixelSize: Style.font.subtitle * 2
                    font.bold: true
                }

                // Cents meter. The needle spans -50..+50 cents, which is the
                // full distance to the neighbouring semitone in either
                // direction, so a reading can never leave the track.
                Rectangle {
                    id: meter

                    width: parent.width
                    height: Style.space(18)
                    radius: Style.cornerRadius
                    color: Util.alpha(root.barForeground, 0.08)

                    Rectangle {
                        width: 1
                        height: parent.height
                        anchors.horizontalCenter: parent.horizontalCenter
                        color: Util.alpha(root.barForeground, 0.5)
                    }

                    Rectangle {
                        width: Style.space(3)
                        height: parent.height
                        radius: width / 2
                        visible: root.displayHz > 0
                        color: root.readingInTune ? Color.accent : Color.urgent
                        opacity: root.readingOpacity
                        x: Math.max(0, Math.min(meter.width - width, (meter.width - width) * (Math.max(-50, Math.min(50, root.centsExact)) + 50) / 100))

                        Behavior on x {
                            NumberAnimation {
                                duration: 90
                            }

                        }

                    }

                }

                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: root.displayHz > 0 ? (root.cents > 0 ? "+" : "") + root.cents + " cents  ·  " + root.displayHz.toFixed(2) + " Hz" : "No pitch detected"
                    color: root.barForeground
                    opacity: root.readingOpacity
                    font.family: root.bar ? root.bar.fontFamily : Style.font.family
                    font.pixelSize: Style.font.body
                    wrapMode: Text.WordWrap
                }

                // Input level. Without it, a silent panel is ambiguous: no
                // cable, wrong input, or just nothing being played.
                Rectangle {
                    width: parent.width
                    height: Style.space(4)
                    radius: height / 2
                    color: Util.alpha(root.barForeground, 0.08)

                    Rectangle {
                        height: parent.height
                        radius: parent.radius
                        // Level is linear RMS, which crowds an instrument
                        // signal into the bottom of the bar. A square root
                        // spreads the useful range out.
                        width: parent.width * Math.min(1, Math.sqrt(root.level * 4))
                        color: root.hasSignal ? Util.alpha(root.barForeground, 0.55) : Util.alpha(root.barForeground, 0.2)

                        Behavior on width {
                            NumberAnimation {
                                duration: 60
                            }

                        }

                    }

                }

                Text {
                    width: parent.width
                    visible: root.statusText.length > 0
                    horizontalAlignment: Text.AlignHCenter
                    text: root.statusText
                    color: root.detectorError.length > 0 ? Color.urgent : root.barForeground
                    opacity: root.detectorError.length > 0 ? 1 : 0.7
                    font.family: root.bar ? root.bar.fontFamily : Style.font.family
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap
                }

                Rectangle {
                    width: parent.width
                    height: 1
                    color: Util.alpha(root.barForeground, 0.15)
                }

                Text {
                    width: parent.width
                    visible: !root.selectionAvailable
                    text: "The chosen input is not connected. Capture falls back to the system default without warning."
                    color: Color.urgent
                    font.family: root.bar ? root.bar.fontFamily : Style.font.family
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap
                }

                Dropdown {
                    id: tuningDropdown

                    width: parent.width
                    label: "Tuning"
                    fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
                    options: root.tuningOptions
                    value: root.selectedTuning
                    onChanged: function(selected) {
                        root.selectTuning(selected);
                    }
                }

                // The tuning's strings in order, checked off as each is played
                // in tune. Absent for chromatic, which has no strings to work
                // through and so nothing to report progress against.
                Row {
                    id: targetStrip

                    width: parent.width
                    visible: root.tuning.targets.length > 0

                    Repeater {
                        model: root.tuning.targets

                        Text {
                            id: target

                            required property int index
                            required property var modelData
                            readonly property bool checked: root.checkedTargets.indexOf(target.index) !== -1

                            width: targetStrip.width / Math.max(1, root.tuning.targets.length)
                            horizontalAlignment: Text.AlignHCenter
                            text: String(target.modelData)
                            color: target.checked ? Color.accent : root.barForeground
                            opacity: target.checked ? 1 : 0.45
                            font.family: root.bar ? root.bar.fontFamily : Style.font.family
                            font.pixelSize: Style.font.body
                        }

                    }

                }

                Dropdown {
                    id: inputDropdown

                    width: parent.width
                    label: "Input"
                    fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
                    options: root.inputOptions
                    value: root.selectedTarget
                    onChanged: function(selected) {
                        root.selectTarget(selected);
                    }
                }

            }

        }

    }

}
