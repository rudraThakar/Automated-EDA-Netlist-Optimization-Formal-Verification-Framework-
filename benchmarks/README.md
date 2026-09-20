# VeriFlow Benchmarks

This directory contains small benchmark circuits used to exercise the parser, IR metrics, and verification-oriented EDA backend.

The benchmark runner emits:

- `summary.json` - structured metrics for each design
- `summary.md` - resume/demo-friendly Markdown table

Run from the project root:

```bash
make benchmark
```

The current benchmark set includes:

- `simple_chain.v` - basic combinational depth
- `fanout_stress.v` - high fanout measurement
- `dangling_logic.v` - unused logic detection baseline
- `rtl_expression.v` - RTL expression that requires the Yosys JSON frontend fallback
