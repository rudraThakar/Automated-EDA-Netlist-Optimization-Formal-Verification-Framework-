from config import load_config, load_dotenv, make_planner_from_config
from planners.heuristic import HeuristicBootstrapPlanner
from planners.nvidia import NvidiaPlanner


def test_load_simple_yaml_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        'provider: "gemini"\nverification_policy: "strict"\ngemini:\n  api_key: "abc"\n  model: "gemini-1.5-flash"\ngeneration:\n  temperature: 0.2\n  max_output_tokens: 100\n',
        encoding="utf-8",
    )
    data = load_config(str(cfg))
    assert data["provider"] == "gemini"
    assert data["verification_policy"] == "strict"
    assert data["gemini"]["model"] == "gemini-1.5-flash"
    assert data["generation"]["max_output_tokens"] == 100


def test_no_llm_uses_heuristic():
    planner = make_planner_from_config({"provider": "gemini"}, no_llm=True)
    assert isinstance(planner, HeuristicBootstrapPlanner)


def test_heuristic_handles_external_tool_check():
    planner = HeuristicBootstrapPlanner()
    assert planner.plan("Check external tools.") == '{"arguments":{},"tool":"check_external_tools"}'


def test_heuristic_handles_clean_dangling_workflow():
    planner = HeuristicBootstrapPlanner()
    assert planner.plan(
        'remove dangling logic from the design top.v and create a new design named "better_top.v"'
    ) == '{"arguments":{"input_path":"top.v","output_path":"better_top.v"},"tool":"clean_dangling_and_write"}'


def test_nvidia_provider_uses_nemotron_config(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    planner = make_planner_from_config(
        {
            "provider": "nvidia",
            "nvidia": {
                "model": "nvidia/nemotron-3-super-120b-a12b",
                "base_url": "https://integrate.api.nvidia.com/v1",
            },
        }
    )

    assert isinstance(planner, NvidiaPlanner)
    assert planner.model == "nvidia/nemotron-3-super-120b-a12b"
    assert planner.base_url == "https://integrate.api.nvidia.com/v1"


def test_load_dotenv_sets_missing_values_without_overriding(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("NVIDIA_API_KEY=from-file\nEXISTING=value-from-file\n", encoding="utf-8")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("EXISTING", "from-shell")

    load_dotenv(str(env_path))

    assert __import__("os").environ["NVIDIA_API_KEY"] == "from-file"
    assert __import__("os").environ["EXISTING"] == "from-shell"
