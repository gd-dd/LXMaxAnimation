"""Exercise the production function without starting the Max bridge service."""
import ast
import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace


class PoseFailureTests(unittest.TestCase):
    def run_pose(self, fail):
        source = Path(__file__).resolve().parents[1] / 'max/bridge.py'
        function = next(n for n in ast.parse(source.read_text('utf-8')).body
                        if isinstance(n, ast.FunctionDef) and n.name == 'apply_pose')
        nodes = [SimpleNamespace(name=name, parent=None, controller=object(), transform=0)
                 for name in ('root', 'control')]
        events = []

        class MaxUndo:
            def __enter__(self):
                return self
            def __exit__(self, kind, error, tb):
                if error:
                    events.append(('rollback', nodes[0].transform))
                    for node in nodes:
                        node.transform = 0
                return True  # Real pymxs.undo suppresses Python errors.

        calls = []
        def matrix(value):
            calls.append(value)
            if fail and len(calls) == 4:
                raise RuntimeError('injected second-node failure')
            return value

        env = dict(json=json, Path=Path, matrix=matrix,
                   rt=SimpleNamespace(objects=nodes, classOf=lambda n: 'Dummy',
                                      isProperty=lambda *a: False, sliderTime=7,
                                      addNewKey=lambda *a: None),
                   pymxs=SimpleNamespace(undo=lambda *a: MaxUndo(), animate=lambda *a: nullcontext()))
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), env)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'pose.json'
            path.write_text(json.dumps({'schema': 1, 'nodes': [
                {'name': n.name, 'parent': None, 'local': 9} for n in nodes]}), encoding='utf-8')
            if fail:
                with self.assertRaisesRegex(RuntimeError, 'second-node failure'):
                    env['apply_pose'](path)
                self.assertEqual(events, [('rollback', 9)])
                self.assertEqual([n.transform for n in nodes], [0, 0])
            else:
                self.assertTrue(env['apply_pose'](path)['ok'])
                self.assertEqual([n.transform for n in nodes], [9, 9])

    def test_failure_rolls_back_and_reaches_caller(self):
        self.run_pose(True)

    def test_success_still_applies_pose(self):
        self.run_pose(False)
