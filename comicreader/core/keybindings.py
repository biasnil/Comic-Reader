"""Named actions and the (rebindable) keys that trigger them."""
from collections import OrderedDict, namedtuple

from ..utils.helpers import key_string, pretty_key

Action = namedtuple("Action", "label callback keys")


class KeyBindings:
    """Registry mapping action names -> callbacks, plus the key -> action lookup table.

    Only the keys the user has changed are stored (in Store.key_overrides); everything else
    falls back to the defaults given at registration.
    """

    def __init__(self, store):
        self.store = store
        self.actions: "OrderedDict[str, Action]" = OrderedDict()
        self._keymap: dict[str, str] = {}
        self.on_change = None  # called after any change so menus can refresh their accelerators

    # ---- registration / lookup ----------------------------------------------- #
    def register(self, name: str, label: str, callback, default_keys):
        self.actions[name] = Action(label, callback, list(default_keys))

    def keys_for(self, name: str) -> list[str]:
        return self.store.key_overrides.get(name, self.actions[name].keys)

    def accelerator(self, name: str) -> str:
        keys = self.keys_for(name)
        return pretty_key(keys[0]) if keys else ""

    def rebuild(self):
        self._keymap = {}
        for name in self.actions:
            for k in self.keys_for(name):
                self._keymap[k] = name

    def lookup(self, key: str):
        return self._keymap.get(key)

    def dispatch(self, event) -> bool:
        """Run the action bound to this key event. Returns True if there was one."""
        if event.keysym.endswith(("_L", "_R")) or event.keysym in ("Caps_Lock", "Num_Lock"):
            return False
        name = self._keymap.get(key_string(event))
        if not name:
            return False
        self.actions[name].callback()
        return True

    # ---- editing ------------------------------------------------------------------ #
    def set_key(self, name: str, key: str, add: bool):
        overrides = self.store.key_overrides
        for other in self.actions:  # a key can only belong to one action
            if other != name and key in self.keys_for(other):
                overrides[other] = [k for k in self.keys_for(other) if k != key]
        current = self.keys_for(name) if add else []
        overrides[name] = current + [key] if key not in current else current
        self._changed()

    def clear(self, name: str):
        self.store.key_overrides[name] = []
        self._changed()

    def reset(self):
        self.store.key_overrides.clear()
        self._changed()

    def _changed(self):
        self.rebuild()
        self.store.save()
        if self.on_change:
            self.on_change()
