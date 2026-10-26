import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ui.integrations import launch_max

class LaunchTests(unittest.TestCase):
    def test_launch_keeps_paths_as_separate_arguments(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'Max with spaces';root.mkdir()
            exe=root/'3dsmax.exe';exe.write_bytes(b'fixture')
            script=root/'连接脚本.ms';script.write_text('-- fixture','utf-8')
            with patch('ui.integrations.subprocess.Popen') as start:
                launch_max(exe,script)
                start.assert_called_once_with([str(exe.resolve()),'-U','MAXScript',str(script.resolve())],cwd=str(root.resolve()))
    def test_missing_script_or_wrong_executable_does_not_launch(self):
        with tempfile.TemporaryDirectory() as temp,patch('ui.integrations.subprocess.Popen') as start:
            root=Path(temp);exe=root/'3dsmax.exe';exe.write_bytes(b'fixture')
            with self.assertRaises(ValueError):launch_max(exe,root/'missing.ms')
            wrong=root/'other.exe';wrong.write_bytes(b'fixture')
            with self.assertRaises(ValueError):launch_max(wrong,root/'missing.ms')
            start.assert_not_called()
