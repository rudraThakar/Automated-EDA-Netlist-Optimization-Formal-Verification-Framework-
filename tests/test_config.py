from config import load_config, make_planner_from_config
from planners.heuristic import HeuristicBootstrapPlanner


def test_load_simple_yaml_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text('provider: "gemini"\ngemini:\n  api_key: "abc"\n  model: "gemini-1.5-flash"\ngeneration:\n  temperature: 0.2\n  max_output_tokens: 100\n', encoding="utf-8")
    data = load_config(str(cfg))
    assert data["provider"] == "gemini"
    assert data["gemini"]["model"] == "gemini-1.5-flash"
    assert data["generation"]["max_output_tokens"] == 100


def test_no_llm_uses_heuristic():
    planner = make_planner_from_config({"provider": "gemini"}, no_llm=True)
    assert isinstance(planner, HeuristicBootstrapPlanner)
