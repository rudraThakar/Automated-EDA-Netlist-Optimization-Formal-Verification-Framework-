from unittest.mock import Mock, patch

from external_tools import ABCBridge, ToolRunResult, YosysBridge


def test_external_tool_bridges_can_check_availability():
    assert isinstance(YosysBridge().available(), bool)
    assert isinstance(ABCBridge().available(), bool)


def test_yosys_version():
    yosys = YosysBridge()
    if yosys.available():
        version = yosys.version()
        assert version is not None
        assert isinstance(version, str)
    else:
        assert yosys.version() is None


def test_abc_version():
    abc = ABCBridge()
    if abc.available():
        version = abc.version()
        assert version is not None
        assert isinstance(version, str)
    else:
        assert abc.version() is None


def test_yosys_normalize_verilog(tmp_path):
    yosys = YosysBridge()
    if not yosys.available():
        return  # Skip if Yosys not available

    # Create a simple test netlist
    input_v = tmp_path / "input.v"
    output_v = tmp_path / "output.v"
    input_v.write_text("""
module test(a, b, y);
  input a, b;
  output y;
  wire n1;
  and u1(n1, a, b);
  buf u2(y, n1);
endmodule
""")

    result = yosys.normalize_verilog(str(input_v), str(output_v))
    assert result.ok
    assert output_v.exists()

    # Check that output contains valid Verilog
    content = output_v.read_text()
    assert "module test" in content
    assert "endmodule" in content


def test_abc_run_script():
    abc = ABCBridge()
    if not abc.available():
        return  # Skip if ABC not available

    # Run a simple ABC command
    result = abc.run_script("read_blif; print_stats", timeout_sec=10)
    # This might fail if no BLIF is loaded, but should return a result
    assert isinstance(result, ToolRunResult)
    assert isinstance(result.ok, bool)


def test_mock_yosys_unavailable():
    """Test behavior when Yosys is not available."""
    with patch('shutil.which', return_value=None):
        yosys = YosysBridge()
        assert not yosys.available()
        assert yosys.version() is None

        # Test normalize_verilog
        result = yosys.normalize_verilog("dummy.v", "output.v")
        assert not result.ok
        assert "yosys" in result.command[0]


def test_mock_abc_unavailable():
    """Test behavior when ABC is not available."""
    abc = ABCBridge()
    with patch.object(abc, 'available', return_value=False), \
         patch.object(abc.runner, 'run') as mock_run:
        mock_run.return_value = ToolRunResult(
            command=["abc", "-c", "print_stats"],
            returncode=127,
            stdout="",
            stderr="abc: command not found"
        )

        assert not abc.available()
        assert abc.version() is None

        # Test run_script - should return the mocked failed result
        result = abc.run_script("print_stats")
        assert isinstance(result, ToolRunResult)
        assert not result.ok
        assert result.command == ["abc", "-c", "print_stats"]
        mock_run.assert_called_once()


def test_tool_run_result():
    """Test ToolRunResult properties."""
    result = ToolRunResult(
        command=["test", "cmd"],
        returncode=0,
        stdout="success",
        stderr="warning"
    )
    assert result.ok
    assert result.command == ["test", "cmd"]
    assert result.stdout == "success"
    assert result.stderr == "warning"

    failed_result = ToolRunResult(
        command=["test", "cmd"],
        returncode=1,
        stdout="",
        stderr="error"
    )
    assert not failed_result.ok
