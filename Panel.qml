import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Pipewire
import qs.Commons
import qs.Ui

Panel {
    id: root

    // Twelve-tone names indexed by pitch class, sharps only. A tuner never
    // needs the flat spelling: the target is a string, not a key signature.
    readonly property var noteNames: ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
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
    readonly property real midiNote: root.detectedHz > 0 ? 69 + 12 * Math.log(root.detectedHz / 440) / Math.LN2 : 0
    readonly property int nearestMidi: root.detectedHz > 0 ? Math.round(root.midiNote) : 0
    readonly property int cents: root.detectedHz > 0 ? Math.round((root.midiNote - root.nearestMidi) * 100) : 0
    readonly property string noteLabel: root.detectedHz > 0 ? root.noteNames[((root.nearestMidi % 12) + 12) % 12] + (Math.floor(root.nearestMidi / 12) - 1) : "--"
    // 5 cents is the band where a guitar or bass reads as in tune by ear.
    readonly property bool inTune: root.detectedHz > 0 && Math.abs(root.cents) <= 5
    readonly property bool hasSignal: root.level >= 0.004
    readonly property string statusText: {
        if (root.detectorError.length > 0)
            return root.detectorError;

        // A detector that exited stays exited while the panel is open, so say
        // so rather than showing a silence that looks like a quiet room.
        if (root.detectorStopped)
            return "Detector stopped. Close and reopen to retry.";

        if (root.detectedHz > 0)
            return "";

        return root.hasSignal ? "Listening for a steady pitch." : "No signal. Play a note.";
    }
    // Empty when there is nothing to report, so the bar widget can decide what
    // an idle tuner says rather than being handed a label.
    readonly property string barReadout: root.detectedHz > 0 ? root.noteLabel + " " + (root.cents > 0 ? "+" : "") + root.cents + "\u00a2" : ""
    // Process wants a filesystem path, not the file:// URL resolvedUrl returns.
    readonly property string detectorPath: Qt.resolvedUrl("scripts/pitch-detect.py").toString().replace(/^file:\/\//, "")

    // -- input selection ----------------------------------------------------

    // Empty means the PipeWire default source, which is what the detector does
    // with no --target.
    property string selectedTarget: ""
    property bool detectorArmed: true
    readonly property string statePath: Quickshell.env("HOME") + "/.config/omarchy-tuner/input.json"
    readonly property var nodes: Pipewire.nodes ? Pipewire.nodes.values : []
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
    readonly property var detectorCommand: root.selectedTarget.length > 0
        ? ["python3", root.detectorPath, "--target", root.selectedTarget]
        : ["python3", root.detectorPath]
    // The default entry is first and always present, so there is a way back
    // from a device that has been unplugged.
    readonly property var inputOptions: {
        var options = [{
            "value": "",
            "label": "System default"
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

        var label = root.friendlyLabel(node.nickname || node.description || node.name || "Unknown");
        // A monitor records what a sink is playing. Legitimate to tune from,
        // but not what someone reaching for "my microphone" means.
        if (String(node.name || "").indexOf(".monitor") !== -1)
            label += " (monitor)";

        return label;
    }

    function selectTarget(name) {
        var next = String(name || "");
        if (next === root.selectedTarget)
            return ;

        root.selectedTarget = next;
        root.persistSelection();
        root.restartDetector();
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

    function persistSelection() {
        stateFile.setText(JSON.stringify({
            "target": root.selectedTarget
        }, null, 2) + "\n");
    }

    function loadSelection(raw) {
        try {
            var stored = JSON.parse(String(raw || "{}"));
            root.selectedTarget = String(stored.target || "");
        } catch (parseError) {
            root.selectedTarget = "";
        }
    }

    function clearSignal() {
        root.detectedHz = 0;
        root.confidence = 0;
        root.level = 0;
    }

    function resetDetector() {
        root.clearSignal();
        root.detectorSource = "";
        root.detectorError = "";
        root.detectorStopped = false;
    }

    moduleName: "dev.hyeongjin.tuner"
    manageIpc: false
    // Opening the panel is the retry: it restarts the detector, so a stale
    // error from the previous run must not survive into the new one.
    onOpenedChanged: {
        if (root.opened)
            root.resetDetector();
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

    // FileView will not create the parent directory, so this runs once.
    Process {
        id: ensureStateDir

        running: true
        command: ["mkdir", "-p", Quickshell.env("HOME") + "/.config/omarchy-tuner"]
    }

    FileView {
        id: stateFile

        path: root.statePath
        atomicWrites: true
        printErrors: false
        onLoaded: root.loadSelection(text())
        // Absent on first run, which is not a failure: no stored choice means
        // the PipeWire default.
        onLoadFailed: root.loadSelection("{}")
    }

    KeyboardPanel {
        id: panel

        anchorItem: root.anchorItem
        owner: root.hostWidget || root
        bar: root.bar
        open: root.opened
        focusTarget: keyCatcher
        contentWidth: panel.fittedContentWidth(Style.space(320))
        contentHeight: panel.fittedContentHeight(content.implicitHeight)

        PanelKeyCatcher {
            id: keyCatcher

            anchors.fill: parent
            blocked: inputDropdown.popupOpen
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
                    text: "Tuner"
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
                    color: root.inTune ? Color.accent : root.barForeground
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
                        visible: root.detectedHz > 0
                        color: root.inTune ? Color.accent : Color.urgent
                        x: Math.max(0, Math.min(meter.width - width, (meter.width - width) * (Math.max(-50, Math.min(50, root.cents)) + 50) / 100))

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
                    text: root.detectedHz > 0 ? (root.cents > 0 ? "+" : "") + root.cents + " cents  ·  " + root.detectedHz.toFixed(2) + " Hz" : "No pitch detected"
                    color: root.barForeground
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
