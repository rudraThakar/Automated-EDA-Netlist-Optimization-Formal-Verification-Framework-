from engine import DeterministicEDAEngine


SIMPLE_NETLIST = """
module top(a, b, y);
  input a, b;
  output y;
  wire n1;
  and u1(n1, a, b);
  buf u2(y, n1);
endmodule
"""

BUFFER_NETLIST = """
module top(a, b, _gc_ctrl, y);
  input a, b, _gc_ctrl;
  output y;
  wire n1, n2;
  and u1(n1, a, b);
  buf u2_gc__(n2, n1);
  buf u3(y, n2);
endmodule
"""


def test_read_and_query(tmp_path):
    netlist_path = tmp_path / "top.v"
    netlist_path.write_text(SIMPLE_NETLIST, encoding="utf-8")

    engine = DeterministicEDAEngine()
    result = engine.read_netlist(str(netlist_path))
    assert "Loaded gate-level Verilog" in result.summary

    fanout = engine.get_fanout("n1")
    assert fanout.data["fanout"] == 1

    depth = engine.get_max_depth("a", "y")
    assert depth.data["depth"] == 2


def test_normalize_design(tmp_path):
    netlist_path = tmp_path / "top.v"
    netlist_path.write_text(SIMPLE_NETLIST, encoding="utf-8")

    engine = DeterministicEDAEngine()
    engine.read_netlist(str(netlist_path))

    # Test normalization
    result = engine.normalize_design()
    assert result.data["normalized"] is True
    assert "Design normalized successfully" in result.summary


def test_check_max_fanout(tmp_path):
    netlist_path = tmp_path / "top.v"
    netlist_path.write_text(SIMPLE_NETLIST, encoding="utf-8")

    engine = DeterministicEDAEngine()
    engine.read_netlist(str(netlist_path))

    # Test fanout checking
    result = engine.check_max_fanout(8)
    assert result.data["valid"] is True
    assert result.data["max_fanout"] == 8
    assert len(result.data["violations"]) == 0


def test_insert_and_before_buffers(tmp_path):
    netlist_path = tmp_path / "top.v"
    netlist_path.write_text(BUFFER_NETLIST, encoding="utf-8")

    engine = DeterministicEDAEngine()
    engine.read_netlist(str(netlist_path))

    # Test buffer insertion
    result = engine.insert_and_before_buffers("_gc__", "_gc_ctrl")
    assert result.data["success"] is True
    assert result.data["modified_buffers"] == 1
    assert "Inserted AND gates before 1 matching buffers" in result.summary


def test_replace_gates(tmp_path):
    netlist_path = tmp_path / "top.v"
    netlist_path.write_text(SIMPLE_NETLIST, encoding="utf-8")

    engine = DeterministicEDAEngine()
    engine.read_netlist(str(netlist_path))

    # Test gate replacement
    result = engine.replace_gates("buf", "not")
    assert result.data["success"] is True
    assert result.data["replaced_gates"] == 1
    assert "Replaced 1 buf gates with not" in result.summary


def test_optimize_cone(tmp_path):
    netlist_path = tmp_path / "top.v"
    netlist_path.write_text(SIMPLE_NETLIST, encoding="utf-8")

    engine = DeterministicEDAEngine()
    engine.read_netlist(str(netlist_path))

    # Test cone optimization
    result = engine.optimize_cone("y", max_depth=5, minimize_gates=True)
    assert result.data["output_signal"] == "y"
    assert result.data["cone_gates"] == 2
    assert result.data["max_depth"] == 2
    assert "Logic cone analysis" in result.summary


def test_remove_dangling_logic(tmp_path):
    # Create a netlist with dangling logic
    dangling_netlist = """
module top(a, b, y);
  input a, b;
  output y;
  wire n1, n2, n3;
  and u1(n1, a, b);
  buf u2(n2, n1);  // This becomes dangling
  not u3(n3, a);   // This becomes dangling
  buf u4(y, n1);   // This is used
endmodule
"""
    netlist_path = tmp_path / "top.v"
    netlist_path.write_text(dangling_netlist, encoding="utf-8")

    engine = DeterministicEDAEngine()
    engine.read_netlist(str(netlist_path))

    # Test dangling logic removal
    result = engine.remove_dangling_logic()
    assert len(result.data["removed_nodes"]) >= 2  # Should remove u2 and u3
    assert "Removed dangling logic successfully" in result.summary


def test_check_equivalence_without_reference():
    engine = DeterministicEDAEngine()

    # Test equivalence check without reference
    result = engine.check_equivalence()
    assert result.data["equivalent"] is None
    assert "No reference design available" in result.summary


def test_error_handling_tool_unavailable():
    engine = DeterministicEDAEngine()

    # Test normalize without Yosys
    # Mock Yosys as unavailable by setting executable to non-existent
    engine.yosys.executable = "nonexistent_yosys"
    result = engine.normalize_design()
    assert result.data["normalized"] is False
    assert "Yosys not available" in result.summary

    # Test equivalence without ABC
    engine.reference_ir = engine.ir  # Set reference
    result = engine.check_equivalence()
    assert result.data["equivalent"] is None
    assert "ABC not available" in result.summary


def test_invalid_inputs():
    engine = DeterministicEDAEngine()

    # Test invalid gate type
    result = engine.replace_gates("invalid_gate", "and")
    assert result.data["success"] is False
    assert "Unsupported gate type" in result.summary

    # Test buffer insertion with non-existent signal
    result = engine.insert_and_before_buffers("_gc__", "nonexistent_signal")
    assert result.data["success"] is False
    assert "not found in the netlist" in result.summary

    # Test optimize cone with invalid output
    result = engine.optimize_cone("invalid_output")
    assert result.data["success"] is False
    assert "not found in the netlist" in result.summary
