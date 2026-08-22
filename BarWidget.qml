import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

BarWidget {
    id: root

    readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
    readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false
    readonly property bool inTune: panelLoader.item ? panelLoader.item.inTune === true : false
    readonly property string readout: panelLoader.item ? panelLoader.item.barReadout : ""
    // Bound directly rather than through WidgetButton's active/activeColor,
    // which is the urgent colour: being in tune is the opposite of urgent.
    readonly property color iconColor: root.inTune ? Color.accent : (root.bar ? root.bar.barForeground : Color.foreground)

    function open() {
        if (panelLoader.item)
            panelLoader.item.open();

    }

    function close() {
        if (panelLoader.item)
            panelLoader.item.close();

    }

    function toggle() {
        if (panelLoader.item)
            panelLoader.item.toggle();

    }

    function closeForPopoutSwitch() {
        if (panelLoader.item)
            panelLoader.item.closeForPopoutSwitch();

    }

    function injectPanel() {
        if (!panelLoader.item)
            return ;

        panelLoader.item.bar = root.bar;
        panelLoader.item.anchorItem = button;
        panelLoader.item.hostWidget = root;
    }

    moduleName: "dev.hyeongjin.tuner"
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight
    onBarChanged: injectPanel()

    Loader {
        id: panelLoader

        active: true
        source: Qt.resolvedUrl("Panel.qml")
        visible: false
        onLoaded: {
            root.injectPanel();
            Qt.callLater(root.injectPanel);
        }
    }

    // A tuning fork, drawn rather than borrowed from a font. Every dimension
    // is a fraction of the icon slot, so it stays proportional at any bar size
    // and does not depend on a particular Nerd Font revision carrying a
    // suitable glyph.
    Component {
        id: tuningFork

        Item {
            id: fork

            readonly property real unit: Math.min(width, height)
            readonly property real prong: Math.max(1, fork.unit * 0.115)
            readonly property real spread: fork.unit * 0.175
            // The prongs stop exactly where the bridge starts. Letting them
            // overshoot it reads as a plug rather than a fork.
            readonly property real bridgeTop: fork.height / 2 + fork.unit * 0.06
            readonly property real crownTop: fork.height / 2 - fork.unit * 0.40

            Rectangle {
                x: fork.width / 2 - fork.spread - fork.prong / 2
                y: fork.crownTop
                width: fork.prong
                height: fork.bridgeTop + fork.prong - fork.crownTop
                radius: fork.prong / 2
                color: root.iconColor
            }

            Rectangle {
                x: fork.width / 2 + fork.spread - fork.prong / 2
                y: fork.crownTop
                width: fork.prong
                height: fork.bridgeTop + fork.prong - fork.crownTop
                radius: fork.prong / 2
                color: root.iconColor
            }

            // Bridges the prongs into the stem, so the three bars read as one
            // fork instead of three strokes.
            Rectangle {
                x: fork.width / 2 - fork.spread - fork.prong / 2
                y: fork.bridgeTop
                width: fork.spread * 2 + fork.prong
                height: fork.prong
                radius: fork.prong / 2
                color: root.iconColor
            }

            Rectangle {
                x: fork.width / 2 - fork.prong / 2
                y: fork.bridgeTop
                width: fork.prong
                height: fork.height / 2 + fork.unit * 0.40 - fork.bridgeTop
                radius: fork.prong / 2
                color: root.iconColor
            }

        }

    }

    BarIconButton {
        id: button

        anchors.fill: parent
        bar: root.bar
        iconComponent: tuningFork
        tooltipText: root.readout.length > 0 ? "Tuner · " + root.readout : "Tuner"
        onPressed: function(buttonCode) {
            if (buttonCode === Qt.LeftButton)
                root.toggle();

        }
    }

}
