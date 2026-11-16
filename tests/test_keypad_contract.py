from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from studio.keypad_contract import KeypadFrame, KeypadViewState, NavigationCapability, SlotData


class KeypadContractTests(unittest.TestCase):
    def test_preview_is_default_and_edit_is_explicit(self):
        capability = NavigationCapability("Loupedeck70", "ButtonArea", (1, 2), (0,))
        frame = KeypadFrame("ctx", "folder.main", "rev", capability, (
            SlotData(0, "sdk_navigation"),
            SlotData(1, "placement", "placement.one", "action.one", "parameter-A"),
        ))
        state = KeypadViewState(frame)
        self.assertFalse(state.editing_enabled)
        self.assertTrue(state.with_mode("edit").editing_enabled)
        self.assertEqual(frame.slots[1].action_parameter, "parameter-A")
        self.assertFalse(frame.slots[0].editable)

    def test_slots_are_driven_by_capability_not_nine_slot_assumption(self):
        capability = NavigationCapability("Custom", "None", (2, 7, 12))
        KeypadFrame("ctx", "folder", "rev", capability, (SlotData(12, "empty"),))
        with self.assertRaisesRegex(ValueError, "not reported"):
            KeypadFrame("ctx", "folder", "rev", capability, (SlotData(8, "empty"),))


if __name__ == "__main__":
    unittest.main()
