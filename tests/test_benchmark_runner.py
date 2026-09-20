from scripts.benchmark import run_benchmarks


def test_benchmark_runner_writes_json_and_markdown(tmp_path):
    design_dir = tmp_path / "designs"
    out_dir = tmp_path / "results"
    design_dir.mkdir()
    (design_dir / "simple.v").write_text(
        """
module simple(a, b, y);
  input a, b;
  output y;
  and u0(y, a, b);
endmodule
""",
        encoding="utf-8",
    )

    payload = run_benchmarks(design_dir, out_dir, fanout_limit=2)

    assert payload["total_designs"] == 1
    assert payload["ok_designs"] == 1
    assert payload["results"][0]["instances"] == 1
    assert (out_dir / "summary.json").exists()
    assert (out_dir / "summary.md").exists()
