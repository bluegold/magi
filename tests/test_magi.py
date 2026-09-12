import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import magi


class MagiTest(unittest.TestCase):
    def test_decision_status_extracts_supported_decisions(self):
        self.assertEqual(magi.decision_status("推奨案: 採用"), "承認")
        self.assertEqual(magi.decision_status("結論: **条件付き採用**"), "条件付き")
        self.assertEqual(magi.decision_status("推奨: 見送り"), "否決")
        self.assertEqual(magi.decision_status("根拠だけで結論なし"), "完了")

    def test_load_request_requires_subject_and_criteria(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps({"subject": "判断"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                magi.load_request(str(path))

    def test_load_request_accepts_valid_request(self):
        request = {"subject": "判断", "criteria": [{"name": "安全性", "weight": 1}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(request), encoding="utf-8")
            self.assertEqual(magi.load_request(str(path)), request)

    def test_install_and_uninstall_skill_use_resolved_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(magi.Path, "home", return_value=Path(directory)):
                target = magi.install_skill("user")
                installed = (target / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn(str(Path(magi.__file__).resolve()), installed)
                self.assertNotIn("{{MAGI_EXECUTABLE}}", installed)
                self.assertTrue((target / "SKILL.md").exists())

                magi.uninstall_skill("user")
                self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
