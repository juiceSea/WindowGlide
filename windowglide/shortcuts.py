"""Configurable exact-chord matching; no OS calls or repeated key-down actions."""

MODIFIERS = {0x10: "Shift", 0xA0: "Shift", 0xA1: "Shift", 0x11: "Ctrl", 0xA2: "Ctrl", 0xA3: "Ctrl",
             0x12: "Alt", 0xA4: "Alt", 0xA5: "Alt", 0x5B: "Win", 0x5C: "Win"}
NAMES = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}


def parse_shortcut(value):
    if not isinstance(value, str):
        raise ValueError("Shortcut must be a string such as Ctrl+Win+Alt+J")
    tokens = [token.strip().lower() for token in value.split("+")]
    if len(tokens) < 2 or len(set(tokens)) != len(tokens):
        raise ValueError(f"Invalid shortcut: {value!r}")
    if any(token not in NAMES for token in tokens[:-1]):
        raise ValueError(f"Unknown shortcut modifier: {value!r}")
    modifiers = frozenset(NAMES[token] for token in tokens[:-1])
    if not modifiers.intersection(("Ctrl", "Alt", "Win")):
        raise ValueError("Shortcut needs Ctrl, Alt or Win, not Shift alone")
    key = tokens[-1]
    if len(key) == 1 and key.isascii() and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x6F + int(key[1:])
    else:
        raise ValueError("Shortcut main key must be A-Z, 0-9 or F1-F24")
    return modifiers, vk


def bindings_for(settings):
    bindings = {}
    for action in ("minimize", "restore", "maximize"):
        chord = parse_shortcut(getattr(settings, "shortcut_" + action))
        if chord in bindings or chord == parse_shortcut("Ctrl+Win+Alt+Q"):
            raise ValueError("Window shortcuts must differ from one another and the exit shortcut")
        bindings[chord] = action
    return bindings if settings.enable_window_shortcuts else {}


class ShortcutMatcher:
    def __init__(self, bindings):
        self.bindings = bindings
        self.down = set()
        self.consumed = set()

    def feed(self, vk, up):
        was_down = vk in self.down
        if up:
            self.down.discard(vk)
            if vk in self.consumed:
                self.consumed.remove(vk)
                return True, None
            return False, None
        self.down.add(vk)
        if vk in self.consumed:
            return True, None
        if vk in MODIFIERS or was_down:
            return False, None
        modifiers = frozenset(MODIFIERS[key] for key in self.down if key in MODIFIERS)
        action = self.bindings.get((modifiers, vk))
        if action:
            self.consumed.add(vk)
            return True, action
        return False, None
