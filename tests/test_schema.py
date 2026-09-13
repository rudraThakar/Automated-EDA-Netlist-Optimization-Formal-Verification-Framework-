from schema import STRICT_TOOL_SCHEMA, ToolCallValidator


validator = ToolCallValidator(STRICT_TOOL_SCHEMA)


def test_valid_read_tool_call():
    result = validator.parse_llm_json('{"tool":"read_netlist","arguments":{"path":"top.v"}}')
    assert result.ok
    assert result.tool_call is not None
    assert result.tool_call.tool.value == "read_netlist"


def test_valid_write_tool_call():
    result = validator.parse_llm_json('{"tool":"write_netlist","arguments":{"path":"out.v"}}')
    assert result.ok
    assert result.tool_call is not None
    assert result.tool_call.tool.value == "write_netlist"


def test_invalid_tool_call_returns_clarification():
    result = validator.parse_llm_json('{"tool":"bad_tool","arguments":{}}')
    assert not result.ok
    assert result.clarification is not None
    assert "unsupported" in result.clarification.lower() or "invalid" in result.clarification.lower()


def test_extracts_json_from_markdown_fence():
    result = validator.parse_llm_json('```json\n{"tool":"remove_dangling_logic","arguments":{}}\n```')
    assert result.ok
    assert result.tool_call is not None
