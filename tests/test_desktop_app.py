import os
import tempfile
import unittest
from unittest.mock import MagicMock
from pathlib import Path

import desktop_app


class DesktopAppConfigTests(unittest.TestCase):
    def test_normalize_remote_path_windows_style(self):
        self.assertEqual(
            desktop_app.normalize_remote_path(r"annotation_nas\ai_data_collection\test\images_yolo8", "annotation_nas"),
            "ai_data_collection/test/images_yolo8",
        )

    def test_validate_config_rejects_invalid_local_root(self):
        cfg = {
            "REMOTE": "annotation_nas",
            "DATASET": "ai_data_collection/test/images_yolo8",
            "ROOT": "/proc",
            "BATCH_SIZE": "200",
            "RCLONE_BIN": "rclone",
            "XANYLABELING": "xanylabeling",
        }
        self.assertFalse(desktop_app.validate_config(cfg)[0])

    def test_save_config_round_trip_preserves_unrelated_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.env"
            path.write_text(
                '# sample\nREMOTE="old"\nDATASET="example"\nROOT="/tmp/work"\nBATCH_SIZE=200\n',
                encoding="utf-8",
            )
            values = {
                "REMOTE": "annotation_nas",
                "DATASET": "ai_data_collection/test/images_yolo8",
                "ROOT": "/tmp/work",
                "BATCH_SIZE": "100",
            }
            desktop_app.save_config(path, values)
            content = path.read_text(encoding="utf-8")
            self.assertIn('REMOTE="annotation_nas"', content)
            self.assertIn('BATCH_SIZE=100', content)
            self.assertIn('# sample', content)

    def test_parse_status_ignores_plain_text_after_json(self):
        output = '''{
  "catalog": 670,
  "done": 0,
  "batch": 1,
  "state": "ANNOTATING"
}

Local root: /tmp/work
Current batch: 1 (ANNOTATING)
'''
        self.assertEqual(desktop_app.parse_status(output)["state"], "ANNOTATING")

    def test_build_xanylabeling_command_uses_working_directory(self):
        cmd = desktop_app.build_xanylabeling_command(
            "xanylabeling",
            "/tmp/local/batch_000001",
            "source ~/xanylabeling-venv-new/bin/activate",
        )
        self.assertEqual(cmd[0], "bash")
        self.assertEqual(cmd[1], "-lc")
        self.assertIn("/tmp/local/batch_000001", cmd[2])
        self.assertIn("QT_OPENGL=software xanylabeling --qt-platform xcb", cmd[2])

    def test_workflow_state_calculation_batched_progression(self):
        # Verify batched workflow labels and states
        app = desktop_app.AnnotationDesktopApp.__new__(desktop_app.AnnotationDesktopApp)
        # Mock minimal UI variables
        app.hero_tag_var = MagicMock()
        app.wf_next_title_var = MagicMock()
        app.wf_next_desc_var = MagicMock()
        app.wf_next_action_btn_text = MagicMock()
        app.wf_fetch_status_var = MagicMock()
        app.wf_annotate_status_var = MagicMock()
        app.wf_sync_status_var = MagicMock()
        app.wf_clean_status_var = MagicMock()
        app.btn_main_action = MagicMock()
        app.step_labels = [MagicMock() for _ in range(4)]
        app.step2_widget_frame = None
        app.action_card_outer = None
        app.agent = None
        app.C_PRIMARY = "#4F46E5"
        app.C_WARNING = "#D97706"
        app.C_SUCCESS = "#16A34A"
        app.C_TEXT_MUTED = "#64748B"
        app.C_SURFACE_ALT = "#F1F5F9"

        # Case 1: First batch download (0 completed out of 10,000)
        app._update_workflow_state(aid=1, count=10000, total_imgs=0, total_jsons=0, submitted_in_db=0)
        self.assertEqual(app.current_workflow_step, 1)
        app.wf_next_title_var.set.assert_called_with("Step 1: Download Assigned Images (2000 of 10000 Allocated)")

        # Case 2: Batch in progress (2,000 downloaded, 300 labeled)
        app._update_workflow_state(aid=1, count=10000, total_imgs=2000, total_jsons=300, submitted_in_db=0)
        self.assertEqual(app.current_workflow_step, 2)
        app.wf_next_title_var.set.assert_called_with("Step 2: Label in XAnyLabeling (300/2000 Labeled — 15%)")

        # Case 3: Batch 1 complete & cleaned, ready to download Batch 2 (2,000 submitted out of 10,000)
        app._update_workflow_state(aid=1, count=10000, total_imgs=0, total_jsons=0, submitted_in_db=2000)
        self.assertEqual(app.current_workflow_step, 1)
        app.wf_next_title_var.set.assert_called_with("Step 1: Download Next Batch (2000 of 8000 Remaining)")

        # Case 4: All batches finished (10,000 submitted out of 10,000)
        app._update_workflow_state(aid=1, count=10000, total_imgs=0, total_jsons=0, submitted_in_db=10000)
        self.assertEqual(app.current_workflow_step, 4)
        app.wf_next_title_var.set.assert_called_with("🎉 Assignment #1 100% Finished (10000/10000 Completed)")


if __name__ == "__main__":
    unittest.main()

