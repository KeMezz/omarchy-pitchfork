import QtQuick
import Quickshell
import Quickshell.Io
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

        if (root.detectedHz > 0)
            return "";

        return root.hasSignal ? "Listening for a steady pitch." : "No signal. Play a note.";
    }
    readonly property string barReadout: root.detectedHz > 0 ? root.noteLabel : "Tuner"
    // Process wants a filesystem path, not the file:// URL resolvedUrl returns.
    readonly property string detectorPath: Qt.resolvedUrl("scripts/pitch-detect.py").toString().replace(/^file:\/\//, "")

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
        } catch (parseError) {
            root.detectorError = "unreadable detector output";
        }
    }

    function clearReading() {
        root.detectedHz = 0;
        root.confidence = 0;
        root.level = 0;
        root.detectorSource = "";
        root.detectorError = "";
    }

    moduleName: "dev.hyeongjin.tuner"
    manageIpc: false

    // The detector only runs while the panel is open. A tuner that keeps a
    // capture stream alive in the background is a microphone nobody asked for.
    Process {
        id: detector

        running: root.opened
        command: ["python3", root.detectorPath]
        onExited: root.clearReading()

        stdout: SplitParser {
            onRead: function(line) {
                root.applyReading(line);
            }
        }

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

            }

        }

    }

}
