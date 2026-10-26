import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from ui.integrations import launch_max,preferred_max,preferred_session

class LaunchTests(unittest.TestCase):
    def test_launch_keeps_paths_as_separate_arguments(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'Max with spaces';root.mkdir()
            exe=root/'3dsmax.exe';exe.write_bytes(b'fixture')
            script=root/'连接脚本.ms';script.write_text('-- fixture','utf-8')
            with patch('ui.integrations.subprocess.Popen') as start:
                launch_max(exe,script)
                self.assertEqual(start.call_args.args,([str(exe.resolve()),'-U','MAXScript',str(script.resolve())],))
                self.assertEqual(start.call_args.kwargs['cwd'],str(root.resolve()))
                self.assertFalse(set(start.call_args.kwargs['env']) & {'QT_QPA_PLATFORM','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','PYTHONHOME','PYTHONPATH'})
    def test_missing_script_or_wrong_executable_does_not_launch(self):
        with tempfile.TemporaryDirectory() as temp,patch('ui.integrations.subprocess.Popen') as start:
            root=Path(temp);exe=root/'3dsmax.exe';exe.write_bytes(b'fixture')
            with self.assertRaises(ValueError):launch_max(exe,root/'missing.ms')
            wrong=root/'other.exe';wrong.write_bytes(b'fixture')
            with self.assertRaises(ValueError):launch_max(wrong,root/'missing.ms')
            start.assert_not_called()

    def test_saved_executable_wins_and_invalid_path_rescans(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'LOCALAPPDATA':temp}):
            exe=Path(temp)/'3dsmax.exe';exe.touch()
            with patch('ui.integrations.max_installations',return_value=[exe]) as scan:
                self.assertEqual(preferred_max(str(exe)),exe);scan.assert_not_called()
                self.assertEqual(preferred_max(str(Path(temp)/'missing.exe')),exe);scan.assert_called_once()
    def test_discovery_failure_returns_none_for_first_time_picker(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'LOCALAPPDATA':temp}),patch('ui.integrations.max_installations',return_value=[]):
            self.assertIsNone(preferred_max())
    def test_reuses_max_tools_saved_path(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'LOCALAPPDATA':temp}):
            exe=Path(temp)/'3dsmax.exe';exe.touch()
            saved=Path(temp)/'LXMaxTools/max-path.txt';saved.parent.mkdir();saved.write_text(str(exe),'utf-8')
            with patch('ui.integrations.max_installations') as scan:
                self.assertEqual(preferred_max(),exe);scan.assert_not_called()
    def test_remembered_session_wins_without_switching_ambiguous_instances(self):
        one={'protocol':2,'directory':'a','pid':1};two={'protocol':2,'directory':'b','pid':2}
        self.assertEqual(preferred_session([one,two],'b'),two)
        self.assertEqual(preferred_session([one]),one)
        self.assertIsNone(preferred_session([one,two]))
        self.assertIsNone(preferred_session([dict(one,protocol=1)]))
