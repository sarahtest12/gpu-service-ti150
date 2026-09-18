from pathlib import Path
import sys
import unittest


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "gateway"))
from configuration import load
import service


class TtsProjectSelectionTest(unittest.TestCase):
    def test_managed_tts_uses_the_selected_sft_project(self):
        cfg = load(REPO / "gateway/config/server.json")
        command, _, cwd = service.command_for("tts", cfg)
        project = REPO / "tts_300m_sft_service"
        self.assertEqual(cfg["tts"]["project"], project.name)
        self.assertEqual(cwd, project)
        self.assertEqual(command[0], str(project / ".venv/bin/python"))
        self.assertEqual(cfg["tts"]["api_key_file"], project / "runtime/api_key")

    def test_managed_tts_rejects_an_unlisted_project(self):
        cfg = load(REPO / "gateway/config/server.json")
        cfg["tts"]["project"] = "../outside"
        with self.assertRaisesRegex(ValueError, "supported local TTS service"):
            service.command_for("tts", cfg)


if __name__ == "__main__":
    unittest.main()
