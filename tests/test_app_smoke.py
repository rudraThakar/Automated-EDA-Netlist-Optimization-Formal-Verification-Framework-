import os
from pathlib import Path

from app import ICCADApp


SIMPLE_NETLIST = """
module top(a, b, y);
  input a, b;
  output y;
  wire n1;
  and u1(n1, a, b);
  buf u2(y, n1);
endmodule
"""


def test_app_flow(tmp_path):
    old = Path.cwd()
    try:
        os.chdir(tmp_path)
        Path("top.v").write_text(SIMPLE_NETLIST, encoding="utf-8")

        app = ICCADApp()
        app.handle_line("This is the beginning of testcase case9. Please output a copy of the log into case9.log.\n")
        app.handle_line("Read in design from top.v.\n")
        app.handle_line("What is the fanout of n1?\n")
        app.handle_line("Write out the current design to out.v.\n")

        log_text = Path("case9.log").read_text(encoding="utf-8")
        assert "#RESPONSE 1" in log_text
        assert "#RESPONSE 2" in log_text
        assert "#RESPONSE 3" in log_text
        assert "#RESPONSE 4" in log_text
        assert Path("out.v").exists()
    finally:
        os.chdir(old)
