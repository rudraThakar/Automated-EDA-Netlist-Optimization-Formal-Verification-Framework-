import io
import os
from pathlib import Path

from protocol import CaseLogger, ProtocolManager


def test_protocol_writes_stdout_and_log(tmp_path):
    old = Path.cwd()
    try:
        os.chdir(tmp_path)

        stdout = io.StringIO()
        case_logger = CaseLogger()
        case_logger.initialize("case1")
        protocol = ProtocolManager(case_logger, stdout=stdout)
        protocol.emit_response("hello")

        out = stdout.getvalue()
        assert "#RESPONSE 1" in out
        assert "hello" in out
        assert "#END 1" in out

        log_text = Path("case1.log").read_text(encoding="utf-8")
        assert out == log_text
    finally:
        os.chdir(old)
