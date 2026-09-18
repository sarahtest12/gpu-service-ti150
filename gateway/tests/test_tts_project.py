from pathlib import Path
import sys
import unittest


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "gateway"))
from configuration import load
import service


class TtsProjectSelectionTest(unittest.TestCase):
    def test_managed_tts_uses_the_dedicated_300m_project(self):
        cfg = load(REPO / "gateway/config/server.json")
        command, _, cwd = service.command_for("tts", cfg)
        project = REPO / "tts_300m_service"
        self.assertEqual(cwd, project)
        self.assertEqual(command[0], str(project / ".venv/bin/python"))
        self.assertEqual(cfg["tts"]["api_key_file"], project / "runtime/api_key")


if __name__ == "__main__":
    unittest.main()
