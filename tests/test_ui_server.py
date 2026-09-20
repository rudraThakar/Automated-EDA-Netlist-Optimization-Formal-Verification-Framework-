import os
from pathlib import Path

from ui_server import UISession


SIMPLE_NETLIST = """
module top(a, b, y);
  input a, b;
  output y;
  wire n1;
  and u1(n1, a, b);
  buf u2(y, n1);
endmodule
"""


def test_ui_state_exposes_metrics_and_graph(tmp_path):
    old = Path.cwd()
    try:
        os.chdir(tmp_path)
        Path("config.yaml").write_text('provider: "heuristic"\n', encoding="utf-8")
        Path("top.v").write_text(SIMPLE_NETLIST, encoding="utf-8")

        session = UISession()
        session.configure("config.yaml", no_llm=True, require_llm=False, debug=True, verification_policy="strict")
        session.run_request("This is the beginning of testcase ui_case. Please output a copy of the log into ui_case.log.")
        session.run_request("Read in design from top.v.")
        state = session.get_state()

        assert state["verification_policy"] == "strict"
        assert state["metrics"]["module"] == "top"
        assert state["metrics"]["instances"] == 2
        assert state["graph"]["status"] == "ok"
        assert state["graph"]["nodes"]
        assert state["graph"]["edges"]
    finally:
        os.chdir(old)


def test_ui_auto_initializes_case_before_first_request(tmp_path):
    old = Path.cwd()
    try:
        os.chdir(tmp_path)
        Path("config.yaml").write_text('provider: "heuristic"\n', encoding="utf-8")
        Path("top.v").write_text(SIMPLE_NETLIST, encoding="utf-8")

        session = UISession()
        session.configure("config.yaml", no_llm=True, require_llm=False, debug=True, verification_policy="permissive")
        item = session.run_request("Read in design from top.v.")

        assert session.iccad_app is not None
        assert session.iccad_app.case_name == "ui_session"
        assert Path("ui_session.log").exists()
        assert "Loaded gate-level Verilog" in item.response
    finally:
        os.chdir(old)
