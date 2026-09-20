from planners.nvidia import NvidiaPlanner


def test_nvidia_extract_text_from_chat_completion():
    data = {
        "choices": [
            {
                "message": {
                    "content": '{"tool":"check_external_tools","arguments":{}}'
                }
            }
        ]
    }

    assert NvidiaPlanner._extract_text(data) == '{"tool":"check_external_tools","arguments":{}}'


def test_nvidia_planner_falls_back_without_api_key():
    class Fallback:
        def plan(self, user_request):
            return '{"tool":"check_external_tools","arguments":{}}'

    planner = NvidiaPlanner(
        api_key="",
        model="nvidia/nemotron-3-super-120b-a12b",
        schema={"tool_specs": {}, "properties": {"tool": {"enum": []}}},
        fallback=Fallback(),
    )

    assert planner.plan("check tools") == '{"tool":"check_external_tools","arguments":{}}'
    assert planner.last_used == "heuristic_fallback_no_api_key"
