"""Release regression tests. No game capture, discovery, or input."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import app_paths
from app_runtime import SingleInstance, countdown
from abyss_bot import ScreenshotWriter
from launcher import main as settings_main


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='DotAbyss-测试 ')
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'DOTABYSS_DATA_DIR': str(self.root)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_default_config_created_and_existing_edits_preserved(self):
        path = app_paths.ensure_config()
        config = app_paths.load_config(path)
        self.assertEqual(config['max_rounds'], 1)
        config['max_rounds'] = 3
        path.write_text(json.dumps(config), encoding='utf-8')
        self.assertEqual(app_paths.load_config(app_paths.ensure_config())['max_rounds'], 3)

    def test_reject_invalid_schema_budgets_and_account_paths(self):
        base = json.loads((app_paths.RESOURCE_ROOT/'config.default.json').read_text(encoding='utf-8'))
        cases = [('schema_version', 999), ('poll_seconds', 0), ('max_minutes', float('nan')),
                 ('max_rounds', True), ('account_id', '../other'), ('account_id', 'a/b'),
                 ('max_screenshots_per_run', -1)]
        path = self.root/'config.json'
        for key, value in cases:
            with self.subTest(key=key, value=value):
                path.write_text(json.dumps(dict(base, **{key: value})), encoding='utf-8')
                with self.assertRaises(ValueError):
                    app_paths.load_config(path)

    def test_mutex_excludes_second_instance_and_releases(self):
        with SingleInstance():
            with self.assertRaises(RuntimeError):
                with SingleInstance():
                    self.fail('Duplicate run entered')
        with SingleInstance():
            pass

    def test_countdown_cancellable_without_game(self):
        with patch('app_runtime.stop_requested', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'F12'):
                countdown(8)

    def test_screenshot_queue_does_not_grow_on_slow_disk(self):
        import cv2
        import numpy as np
        entered, release = threading.Event(), threading.Event()
        original = cv2.imencode

        def slow_encode(*args):
            entered.set()
            release.wait(5)
            return original(*args)

        with patch('abyss_bot.cv2.imencode', side_effect=slow_encode):
            writer = ScreenshotWriter(max_pending=2, max_files=4)
            try:
                image = np.zeros((8, 8, 3), dtype=np.uint8)
                writer.save(self.root/'first.jpg', image)
                self.assertTrue(entered.wait(2))
                for index in range(20):
                    writer.save(self.root/f'{index}.jpg', image)
                self.assertLessEqual(writer.jobs.qsize(), 2)
                self.assertGreater(writer.dropped, 0)
            finally:
                release.set()
                writer.close()

    def test_screenshot_limit_zero_and_disk_error_are_handled(self):
        import numpy as np
        writer = ScreenshotWriter(max_files=0)
        writer.save(self.root/'no.jpg', np.zeros((8, 8, 3), dtype=np.uint8))
        writer.close()
        self.assertFalse((self.root/'no.jpg').exists())
        with patch('abyss_bot.cv2.imencode', side_effect=OSError('disk full')):
            writer = ScreenshotWriter()
            writer.save(self.root/'full.jpg', np.zeros((8, 8, 3), dtype=np.uint8))
            writer.close()
        self.assertFalse((self.root/'full.jpg').exists())

    def test_settings_save_hands_off_in_process_without_game(self):
        import tkinter as tk
        from tkinter import ttk
        path = app_paths.ensure_config()
        original_tk, original_button = tk.Tk, ttk.Button
        windows = []

        def hidden_root(*args, **kwargs):
            root = original_tk(*args, **kwargs)
            root.withdraw()
            root.after(5000, root.destroy)
            windows.append(root)
            return root

        def button(*args, **kwargs):
            result = original_button(*args, **kwargs)
            if kwargs.get('text') == '保存并开始刷取':
                windows[-1].after(50, kwargs['command'])
            return result

        with patch('launcher.tk.Tk', side_effect=hidden_root), patch('launcher.ttk.Button', side_effect=button), patch('abyss_bot.main', return_value=0) as run:
            self.assertEqual(settings_main(['--config', str(path)]), 0)
            run.assert_called_once_with(['--config', str(path), '--run', '--delay', '8'])
        self.assertEqual(app_paths.load_config(path)['max_rounds'], 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
