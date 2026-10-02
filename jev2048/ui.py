"""The "Jev is running" indicator: a small floating widget plus a menu
bar status item. Both only ever reflect state; all the decisions happen
elsewhere. Every call here is safe to make from a background thread -
updates are marshalled onto the main run loop via `AppHelper.callAfter`.
"""

from __future__ import annotations

from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSImage,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSPanel,
    NSScreen,
    NSStatusBar,
    NSTextField,
    NSVariableStatusItemLength,
    NSViewWidthSizable,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
)
from PyObjCTools import AppHelper

# Not exposed as a Python-friendly constant in every PyObjC version; this
# is AppKit's NSWindowStyleMaskNonactivatingPanel value.
_NONACTIVATING_PANEL_MASK = 1 << 7
_BORDERLESS_MASK = 0

WIDGET_WIDTH = 260
WIDGET_HEIGHT = 58
MARGIN = 14


def _make_label(frame, text, size, bold=False, color=None):
    label = NSTextField.alloc().initWithFrame_(frame)
    label.setStringValue_(text)
    label.setEditable_(False)
    label.setSelectable_(False)
    label.setBezeled_(False)
    label.setDrawsBackground_(False)
    label.setFont_(
        NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
    )
    label.setTextColor_(color or NSColor.labelColor())
    label.setAutoresizingMask_(NSViewWidthSizable)
    return label


class StatusWidget:
    """Owns the floating panel and the menu bar item. Must be constructed
    on the main thread, after NSApplication is set up."""

    def __init__(self, on_quit=None):
        self._on_quit = on_quit
        self._build_panel()
        self._build_status_item()

    # -- construction ---------------------------------------------------------

    def _build_panel(self):
        screen = NSScreen.mainScreen()
        visible = screen.visibleFrame() if screen else NSMakeRect(0, 0, 1440, 900)
        x = visible.origin.x + visible.size.width - WIDGET_WIDTH - MARGIN
        y = visible.origin.y + visible.size.height - WIDGET_HEIGHT - MARGIN
        frame = NSMakeRect(x, y, WIDGET_WIDTH, WIDGET_HEIGHT)

        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            _BORDERLESS_MASK | _NONACTIVATING_PANEL_MASK,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(NSFloatingWindowLevel)
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(True)  # purely informational, never steals clicks
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
        )

        content = NSVisualEffectView.alloc().initWithFrame_(
            NSMakeRect(0, 0, WIDGET_WIDTH, WIDGET_HEIGHT)
        )
        content.setMaterial_(NSVisualEffectMaterialHUDWindow)
        content.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        content.setState_(NSVisualEffectStateActive)
        content.setWantsLayer_(True)
        content.layer().setCornerRadius_(12.0)
        content.layer().setMasksToBounds_(True)

        title = _make_label(
            NSMakeRect(16, 30, WIDGET_WIDTH - 32, 20),
            "\U0001F7E2 Jev is playing",
            13,
            bold=True,
        )
        subtitle = _make_label(
            NSMakeRect(16, 10, WIDGET_WIDTH - 32, 16),
            "Starting...",
            11,
            color=NSColor.secondaryLabelColor(),
        )
        content.addSubview_(title)
        content.addSubview_(subtitle)

        panel.setContentView_(content)

        self._panel = panel
        self._title_label = title
        self._subtitle_label = subtitle

    def _build_status_item(self):
        self._status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        button = self._status_item.button()
        self._status_button = button
        self._apply_icon(False)

        menu = NSMenu.alloc().init()
        hint_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Toggle: Ctrl+Option+J", None, ""
        )
        hint_item.setEnabled_(False)
        menu.addItem_(hint_item)
        menu.addItem_(NSMenuItem.separatorItem())
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit Jev 2048", "quitClicked:", "q"
        )
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)
        self._status_item.setMenu_(menu)

    def quitClicked_(self, sender):
        if self._on_quit:
            self._on_quit()
        else:
            NSApp.terminate_(self)

    def _apply_icon(self, running: bool):
        symbol = "play.circle.fill" if running else "pause.circle"
        description = "Jev is playing" if running else "Jev is idle"
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            symbol, description
        )
        if image is not None:
            image.setTemplate_(True)
            self._status_button.setImage_(image)
        self._status_button.setTitle_(" Jev" if running else " Jev")

    # -- thread-safe public API ------------------------------------------------

    def set_running(self, running: bool):
        def _apply():
            self._apply_icon(running)
            if running:
                self._subtitle_label.setStringValue_("Starting...")
                self._panel.orderFrontRegardless()
            else:
                self._panel.orderOut_(None)

        AppHelper.callAfter(_apply)

    def update_status(
        self, move_count: int, direction: str, confidence: float, source: str
    ):
        if source == "jev":
            text = f"Move {move_count} \u2022 {direction} ({confidence * 100:.0f}%)"
        elif source == "search":
            text = f"Move {move_count} \u2022 {direction} (search)"
        elif source == "fallback":
            text = f"Move {move_count} \u2022 {direction} (fallback)"
        else:
            text = f"Move {move_count} \u2022 {direction}"

        def _apply():
            self._subtitle_label.setStringValue_(text)

        AppHelper.callAfter(_apply)

    def show_message(self, message: str):
        def _apply():
            self._subtitle_label.setStringValue_(message)

        AppHelper.callAfter(_apply)


if __name__ == "__main__":
    # Quick manual check: shows the widget for a few seconds, then quits.
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
    from Foundation import NSTimer

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    widget = StatusWidget()
    widget.set_running(True)
    widget.update_status(3, "right", 0.84, "jev")

    def _stop(timer):
        AppHelper.stopEventLoop()

    NSTimer.scheduledTimerWithTimeInterval_repeats_block_(4.0, False, _stop)
    AppHelper.runEventLoop()
