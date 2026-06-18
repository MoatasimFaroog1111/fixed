"""Unit tests for logging_rotating.py — Rotating logger setup."""
import logging
import os
import tempfile

import pytest

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logging_rotating import setup_rotating_logger, cleanup_old_logs


class TestSetupRotatingLogger:
    def test_creates_logger(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        logger = setup_rotating_logger("TestBot", log_file)
        assert logger.name == "TestBot"
        assert logger.level == logging.INFO
        assert len(logger.handlers) == 2  # file + stream

    def test_logger_writes_to_file(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        logger = setup_rotating_logger("WriteBot", log_file)
        logger.info("Hello World")
        with open(log_file) as f:
            content = f.read()
        assert "Hello World" in content

    def test_no_duplicate_handlers(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        logger1 = setup_rotating_logger("DupBot", log_file)
        logger2 = setup_rotating_logger("DupBot", log_file)
        assert logger1 is logger2
        assert len(logger1.handlers) == 2

    def test_custom_level(self, tmp_path):
        log_file = str(tmp_path / "debug.log")
        logger = setup_rotating_logger("DebugBot", log_file, level=logging.DEBUG)
        assert logger.level == logging.DEBUG

    def test_propagate_disabled(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        logger = setup_rotating_logger("NoPropBot", log_file)
        assert logger.propagate is False


class TestCleanupOldLogs:
    def test_no_cleanup_needed(self, tmp_path, capsys):
        # Create small file
        f = tmp_path / "test.log"
        f.write_text("small")
        cleanup_old_logs(str(tmp_path), pattern=".log", keep_mb=1)
        captured = capsys.readouterr()
        assert "no cleanup needed" in captured.out

    def test_cleanup_removes_old_files(self, tmp_path, capsys):
        # Create files totaling > keep_mb
        for i in range(5):
            f = tmp_path / f"bot_{i}.log"
            f.write_bytes(b"x" * (1024 * 1024))  # 1MB each
        # keep_mb=3 means we need to remove 2 oldest
        cleanup_old_logs(str(tmp_path), pattern=".log", keep_mb=3)
        captured = capsys.readouterr()
        assert "Removed" in captured.out
        remaining = list(tmp_path.glob("*.log"))
        assert len(remaining) == 3

    def test_cleanup_empty_dir(self, tmp_path, capsys):
        cleanup_old_logs(str(tmp_path), pattern=".log", keep_mb=1)
        captured = capsys.readouterr()
        assert "no cleanup needed" in captured.out
