import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
	id: window
	width: 1440
	height: 900
	minimumWidth: 900
	minimumHeight: 560
	visible: true
	title: "Photoroom"
	color: theme.background

	palette.window: theme.panel
	palette.windowText: theme.text
	palette.base: theme.panelRaised
	palette.text: theme.text
	palette.button: theme.panelRaised
	palette.buttonText: theme.text
	palette.highlight: theme.accent
	palette.highlightedText: "#101722"
	palette.mid: theme.border

	Connections {
		target: app
		function onMessage(text) { toast.show(text) }
	}

	// A thumbnail: click marks / unmarks, double-click (or the eye) opens the preview.
	component Thumb: Item {
		id: thumb
		property var item: ({})
		property int size: 180
		readonly property bool marked: { app.rev; return app.isMarked(item.key || "") }
		width: size
		height: size

		Rectangle {
			anchors.fill: parent
			radius: 6
			color: theme.panelRaised
			clip: true
			Image {
				anchors.fill: parent
				anchors.margins: 2
				source: thumb.item.thumb || ""
				fillMode: Image.PreserveAspectCrop
				asynchronous: true
				sourceSize.width: 320
				opacity: thumb.marked ? 0.35 : 1
			}
		}
		Rectangle {
			anchors.fill: parent
			radius: 6
			color: "transparent"
			border.width: thumb.marked ? 3 : (thumb.item.keep ? 2 : 0)
			border.color: thumb.marked ? theme.error : theme.ok
		}
		Label {
			visible: thumb.marked
			anchors.centerIn: parent
			text: "Delete"
			color: theme.error
			font.bold: true
			font.pixelSize: 15
		}
		Row {
			x: 6
			y: 6
			spacing: 4
			Badge { visible: !!thumb.item.keep; text: "keep"; tint: theme.ok }
			Badge { visible: !!thumb.item.favorite; text: "★"; tint: theme.warn }
			Badge { visible: thumb.item.kind === "video"; text: "▶ " + (thumb.item.duration || ""); tint: theme.accent }
		}
		Badge {
			x: thumb.width - width - 6
			y: thumb.height - height - 6
			text: thumb.item.size || ""
			tint: theme.muted
		}
		MouseArea {
			anchors.fill: parent
			acceptedButtons: Qt.LeftButton | Qt.RightButton
			onClicked: (m) => {
				if (m.button === Qt.RightButton) app.showPreview(thumb.item.key)
				else app.toggle(thumb.item.key)
			}
			onDoubleClicked: app.showPreview(thumb.item.key)
		}
		ToolTip.visible: hover.hovered
		ToolTip.delay: 600
		ToolTip.text: (thumb.item.date || "") + "  " + (thumb.item.title || "") + "\nClick: mark · Right-click: preview"
		HoverHandler { id: hover }
	}

	component Badge: Rectangle {
		property alias text: badgeLabel.text
		property color tint: theme.muted
		height: 20
		width: badgeLabel.implicitWidth + 10
		radius: 4
		color: "#cc15171b"
		Label { id: badgeLabel; anchors.centerIn: parent; color: parent.tint; font.pixelSize: 11 }
	}

	RowLayout {
		anchors.fill: parent
		spacing: 0

		// Sidebar: categories
		Rectangle {
			Layout.fillHeight: true
			Layout.preferredWidth: 260
			color: theme.panel
			Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: theme.border }

			ColumnLayout {
				anchors.fill: parent
				anchors.margins: 14
				spacing: 4

				Label { text: "Photoroom"; color: theme.text; font.pixelSize: 20; font.bold: true }
				Label { text: app.librarySummary; color: theme.muted; font.pixelSize: 12; Layout.bottomMargin: 12 }

				Repeater {
					model: app.categories
					delegate: CategoryButton {
						required property var modelData
						catId: modelData.id
						title: modelData.title
						sub: modelData.count + (modelData.unit ? (modelData.count === 1 ? " group" : " groups") : "") + " · " + modelData.size
						enabled: modelData.count > 0
					}
				}
				Item { Layout.fillHeight: true }
				Rectangle { Layout.fillWidth: true; height: 1; color: theme.border }
				CategoryButton {
					catId: "marked"
					title: "Marked to delete"
					sub: app.markedCount + " · " + app.markedSize
					tint: theme.error
				}
			}
		}

		// Main area
		ColumnLayout {
			Layout.fillWidth: true
			Layout.fillHeight: true
			spacing: 0

			Rectangle {
				Layout.fillWidth: true
				Layout.preferredHeight: 64
				color: theme.panel
				Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: theme.border }
				RowLayout {
					anchors.fill: parent
					anchors.leftMargin: 18
					anchors.rightMargin: 18
					spacing: 10
					Label {
						Layout.fillWidth: true
						text: app.hint
						color: theme.muted
						wrapMode: Text.WordWrap
					}
					Button {
						visible: app.category !== "marked"
						text: app.isGroups ? "Mark extras (keep best)" : "Mark all"
						onClicked: app.markSuggested()
					}
					Button { text: "Unmark all"; onClicked: app.unmarkAll() }
					Button {
						visible: app.category === "marked"
						text: "Save links"
						onClicked: app.exportLinks()
					}
					Button {
						visible: app.category === "marked" && app.markedCount > 0
						text: "Delete in Google Photos…"
						highlighted: true
						onClicked: app.startDeleting()
					}
				}
			}

			// Lists: a grid
			GridView {
				id: grid
				visible: !app.isGroups
				Layout.fillWidth: true
				Layout.fillHeight: true
				Layout.margins: 12
				clip: true
				cellWidth: 192
				cellHeight: 192
				model: app.isGroups ? null : app.model
				delegate: Thumb {
					required property var model
					item: model
				}
				ScrollBar.vertical: ScrollBar {}
			}

			// Groups: one row per group
			ListView {
				visible: app.isGroups
				Layout.fillWidth: true
				Layout.fillHeight: true
				Layout.margins: 12
				clip: true
				spacing: 10
				model: app.isGroups ? app.model : null
				delegate: Rectangle {
					id: groupRow
					required property var model
					width: ListView.view.width - 14
					height: groupCol.implicitHeight + 20
					radius: 8
					color: theme.panel
					border.color: theme.border
					Column {
						id: groupCol
						x: 10; y: 10
						width: parent.width - 20
						spacing: 8
						Label {
							text: groupRow.model.items ? groupRow.model.date + " · " + groupRow.model.items.length + " shots · " + groupRow.model.extra + " extra" : ""
							color: theme.muted
							font.pixelSize: 12
						}
						Flow {
							width: parent.width
							spacing: 8
							Repeater {
								model: groupRow.model.items || []
								delegate: Thumb {
									required property var modelData
									item: modelData
									size: 160
								}
							}
						}
					}
				}
				ScrollBar.vertical: ScrollBar {}
			}

			// Bottom bar
			Rectangle {
				Layout.fillWidth: true
				Layout.preferredHeight: 44
				color: theme.panel
				Rectangle { width: parent.width; height: 1; color: theme.border }
				Label {
					anchors.verticalCenter: parent.verticalCenter
					x: 18
					text: "Marked to delete: " + app.markedCount + " items · " + app.markedSize
						+ "    Click a picture to mark it, right-click to look at it closely."
					color: theme.muted
				}
			}
		}
	}

	component CategoryButton: Rectangle {
		id: cb
		property string catId
		property string title
		property string sub
		property color tint: theme.text
		Layout.fillWidth: true
		height: 52
		radius: 6
		color: app.category === catId ? theme.panelRaised : (cbHover.hovered ? "#262a31" : "transparent")
		opacity: enabled ? 1 : 0.45
		Column {
			anchors.verticalCenter: parent.verticalCenter
			x: 12
			Label { text: cb.title; color: cb.tint; font.pixelSize: 14 }
			Label { text: cb.sub; color: theme.muted; font.pixelSize: 12 }
		}
		HoverHandler { id: cbHover }
		MouseArea { anchors.fill: parent; onClicked: app.select(cb.catId) }
	}

	// Preview
	Rectangle {
		id: preview
		anchors.fill: parent
		visible: app.preview !== ""
		color: "#ee0e0f12"
		focus: visible
		readonly property var d: app.preview ? app.details(app.preview) : ({})
		readonly property bool marked: { app.rev; return app.isMarked(app.preview) }
		Keys.onEscapePressed: app.showPreview("")
		Keys.onSpacePressed: app.toggle(app.preview)
		MouseArea { anchors.fill: parent; onClicked: app.showPreview("") }

		Image {
			anchors.fill: parent
			anchors.margins: 40
			anchors.bottomMargin: 110
			source: preview.d.image || ""
			fillMode: Image.PreserveAspectFit
			asynchronous: true
		}
		Rectangle {
			anchors.bottom: parent.bottom
			width: parent.width
			height: 90
			color: theme.panel
			MouseArea { anchors.fill: parent }
			RowLayout {
				anchors.fill: parent
				anchors.margins: 18
				spacing: 12
				Column {
					Layout.fillWidth: true
					Label { text: (preview.d.title || "") + (preview.d.favorite ? "  ★" : ""); color: theme.text; font.pixelSize: 15 }
					Label {
						color: theme.muted
						text: [preview.d.date, preview.d.size, preview.d.dims, preview.d.duration,
							preview.d.camera, preview.d.folder ? "from " + preview.d.folder : "",
							preview.d.sharpness ? "sharpness " + preview.d.sharpness : ""]
							.filter(s => s).join(" · ")
					}
				}
				Button {
					text: preview.marked ? "Unmark (Space)" : "Mark to delete (Space)"
					onClicked: app.toggle(app.preview)
				}
				Button { text: "Open file"; onClicked: app.openFile(app.preview) }
				Button {
					text: "Google Photos"
					enabled: !!preview.d.url
					onClicked: app.openInGoogle(app.preview)
				}
				Button { text: "Close (Esc)"; onClicked: app.showPreview("") }
			}
		}
	}

	// Delete mode: one marked item at a time, opened in Google Photos in the browser
	Rectangle {
		id: deleter
		anchors.fill: parent
		visible: app.deleting
		color: "#f20e0f12"
		focus: visible
		readonly property var d: app.deleteCurrent
		Keys.onReturnPressed: app.deleteDone()
		Keys.onEnterPressed: app.deleteDone()
		Keys.onRightPressed: app.deleteSkip()
		Keys.onEscapePressed: app.stopDeleting()
		MouseArea { anchors.fill: parent }

		ColumnLayout {
			anchors.centerIn: parent
			width: Math.min(parent.width - 80, 720)
			spacing: 14
			Label {
				text: "Deleting in Google Photos · " + app.deleteProgress
				color: theme.text
				font.pixelSize: 20
				font.bold: true
			}
			Label {
				Layout.fillWidth: true
				wrapMode: Text.WordWrap
				color: theme.muted
				text: "This photo is open in your browser. Delete it there (trash icon → Move to trash), "
					+ "then come back and press Enter: the next one opens by itself."
			}
			Image {
				Layout.alignment: Qt.AlignHCenter
				Layout.preferredWidth: 320
				Layout.preferredHeight: 320
				source: deleter.d.thumb || ""
				fillMode: Image.PreserveAspectFit
			}
			Label {
				Layout.alignment: Qt.AlignHCenter
				color: theme.muted
				text: [deleter.d.date, deleter.d.size, deleter.d.title].filter(s => s).join(" · ")
			}
			RowLayout {
				Layout.alignment: Qt.AlignHCenter
				spacing: 10
				Button { text: "Open again"; onClicked: app.deleteOpen() }
				Button { text: "Skip (→)"; onClicked: app.deleteSkip() }
				Button { text: "Deleted, next (Enter)"; highlighted: true; onClicked: app.deleteDone() }
				Button { text: "Stop (Esc)"; onClicked: app.stopDeleting() }
			}
		}
	}

	// Toast
	Rectangle {
		id: toast
		anchors.horizontalCenter: parent.horizontalCenter
		anchors.bottom: parent.bottom
		anchors.bottomMargin: 60
		width: toastLabel.implicitWidth + 28
		height: 36
		radius: 6
		color: theme.panelRaised
		border.color: theme.border
		opacity: 0
		Label { id: toastLabel; anchors.centerIn: parent; color: theme.text }
		function show(text) { toastLabel.text = text; opacity = 1; toastTimer.restart() }
		Behavior on opacity { NumberAnimation { duration: 180 } }
		Timer { id: toastTimer; interval: 2600; onTriggered: toast.opacity = 0 }
	}
}
