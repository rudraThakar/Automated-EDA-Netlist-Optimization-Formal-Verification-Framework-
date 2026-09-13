# ICCAD 2026 Problem A — Deterministic Phase 2 Scaffold

This repository contains a **deterministic scaffold** for **ICCAD 2026 Contest Problem A: LLM-Assisted Netlist Exploration and Transformation**.

The project is built around a **constrained JSON tool-calling architecture**:

**natural language request → planner → strict JSON tool call → validator → deterministic engine → protocol/log output**

The current codebase is intentionally a **safe, contest-aligned scaffold**, not a fully complete solver. It already supports the core protocol, config-driven planner selection, restricted gate-level Verilog parsing/writing, several deterministic analysis/transformation tools, and thin Yosys/ABC backend wrappers for future backbone integration.

---

## Current project status

The repository provides a **complete Phase 2 scaffold** for **ICCAD 2026 Contest Problem A** with full Yosys/ABC backend integration:

- contest-style `#RESPONSE <id>` / `#END <id>` protocol handling
- testcase-aware logging to `<case_name>.log`
- strict JSON schema validation for tool calls
- deterministic backend engine with verification-first transformations
- restricted gate-level Verilog parser/writer for the contest subset
- planner abstraction with:
  - deterministic heuristic planner
  - Gemini planner adapter for development
  - heuristic fallback when Gemini is unavailable
- config-based startup using `-config`
- debug/result artifacts under `results/`
- **Yosys integration** for normalization and BLIF export
- **ABC integration** for optimization and equivalence checking
- **automatic verification** of all transformations
- **graceful degradation** when external tools unavailable
- comprehensive pytest coverage (26 tests passing)

This scaffold is **contest-ready** with deterministic, verification-focused EDA operations.

---

## Repository structure

- `src/app.py` — stdin-driven application shell and top-level request handling
- `src/protocol.py` — strict response protocol manager
- `src/schema.py` — tool names, strict JSON schema, and validator
- `src/ir.py` — internal netlist graph representation
- `src/parser.py` — restricted gate-level Verilog parser/writer
- `src/engine.py` — deterministic backend EDA executor
- `src/planners/`
  - `base.py` — planner interface
  - `heuristic.py` — deterministic fallback planner
  - `gemini.py` — Gemini JSON-planner adapter
- `src/config.py` — config loader and planner factory
- `src/external_tools.py` — bounded wrappers for Yosys/ABC
- `ui_server.py` — development UI server for inspecting requests, tool calls, and artifacts
- `ui/` — files for the Web UI
- `tests/` — pytest coverage for the phase 1 scaffold

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Run tests

```bash
make test
```

This should be the first validation step after cloning or handing over the project.

---

## Run the project without LLM

```bash
python src/app.py --no-llm
```

This uses the deterministic heuristic planner only.

---

## Run the project with Gemini during development

Create `config.yaml`:

```yaml
provider: "gemini"

gemini:
  api_key: "YOUR_GEMINI_API_KEY"
  model: "gemini-1.5-flash"

generation:
  temperature: 0.2
  max_output_tokens: 1024
```

Then run:

```bash
python src/app.py -config config.yaml
```

Useful flags:

```bash
python src/app.py -config config.yaml --debug
python src/app.py -config config.yaml --require-llm
python src/app.py --no-llm
```

### Planner behavior

- If Gemini is configured and available, the app uses the Gemini planner.
- If Gemini is unavailable, missing credentials, or returns invalid output, the app falls back to the heuristic planner unless `--require-llm` is used.
- Gemini is used **only** as a planner that emits strict JSON tool calls.
- Gemini does **not** directly edit Verilog or execute shell commands.

---

## Example stdin session

```text
This is the beginning of testcase case1. Please output a copy of the log into case1.log.
Read in design from top.v.
What is the fanout of n1?
Write out the current design to out.v.
```

The beginning-of-testcase line initializes protocol/log state and should become response 1.

---

## Current supported tool calls

The current scaffold supports these validated tool calls:

- `read_netlist` — Load gate-level Verilog netlist
- `write_netlist` — Write current design to Verilog file
- `get_fanout` — Get fanout count for a node or net
- `get_max_depth` — Get maximum logic depth between two points
- `find_path` — Find signal path between source and sink
- `remove_dangling_logic` — Remove unused logic and nets
- `check_external_tools` — Check availability of Yosys/ABC tools
- `normalize_design` — Normalize design using Yosys (with ABC fallback)
- `check_equivalence` — Verify design equivalence using ABC miter
- `check_max_fanout` — Check if design violates max fanout constraint
- `insert_and_before_buffers` — Insert AND gates before buffer instances
- `replace_gates` — Replace gate types (e.g., AND → NAND)
- `optimize_cone` — Optimize logic cone with depth/gate constraints

All transformation tools include automatic normalization and equivalence checking for correctness verification.

---

## Implementation Report

A comprehensive LaTeX report documenting all changes made during the 8-step implementation is available:

```bash
make report  # Requires pdflatex installation
```

The report (`implementation_report.tex`) contains:
- Detailed step-by-step implementation documentation
- Code changes and architectural decisions
- Testing coverage and results
- External tool integration details
- Verification mechanisms and error handling
- Final system capabilities and handover readiness

---

## Testing and Verification

The scaffold includes comprehensive test coverage with 26 passing tests:

```bash
make test  # Run all tests
```

Test categories:
- **Protocol tests** — Response formatting and logging
- **Schema tests** — JSON validation and error handling
- **Engine tests** — All transformation tools with verification
- **External tool tests** — Yosys/ABC availability and mocking
- **Config tests** — Planner selection and fallback behavior
- **App smoke tests** — End-to-end request processing

All transformation operations are verified for correctness:
- Design normalization after changes
- Equivalence checking against reference design
- Automatic rollback on verification failure
- Graceful degradation when external tools unavailable

---

## External Tool Integration

The scaffold integrates with standard EDA tools:

- **Yosys** — Verilog parsing, normalization, BLIF export
- **ABC** — Logic optimization, equivalence checking, miter verification

Tools are automatically detected and gracefully handled when unavailable. All operations include fallbacks to maintain contest compatibility.

## Debug artifacts

When running in development, the app writes useful intermediate files under `results/`, including planner and execution artifacts such as:

- raw planner output
- validated tool JSON
- tool execution output
- final response text
- transaction logs

These artifacts are especially useful when debugging planner behavior or inspecting how a natural-language request was converted into a deterministic tool call.

---

## UI server (development/debug use)

The repository also includes a UI server for development and inspection.

Its purpose is to:

- send one request at a time to the backend
- show the timeline of steps/results
- surface the current Verilog text
- expose intermediate artifacts from `results/`
- keep a placeholder for graph view

This UI is for **development/debugging**, not for contest submission.

---

## Yosys and ABC status

The project already contains thin backend wrappers for **Yosys** and **ABC**.

### Current role

At present, these wrappers are treated as **backend support tools**, not planner-visible raw shell tools.

That is intentional.

The correct long-term design is:

- the planner emits safe, high-level JSON tool calls
- the deterministic engine decides when to use Python IR logic, Yosys, or ABC
- Yosys and ABC remain hidden behind backend bridge classes

### Intended backbone roles

**Yosys** should become the normalization and preparation layer:
- read and normalize Verilog
- perform hierarchy checking
- run simple cleanup/optimization passes
- write normalized Verilog
- export forms needed for ABC

**ABC** should become the verification-first optimization layer:
- combinational equivalence checking
- validation after transformations
- rewrite / balance / optimization passes
- later, cone-level optimization under hard constraints

### Recommended integration order

1. reliable tool detection (`yosys -V`, `abc -h`)
2. Yosys normalization flow
3. ABC equivalence checking
4. automatic post-transform verification
5. structural constraint checking
6. ABC rewrite/balance optimization
7. cone-level optimization under hard constraints

The key principle is:

**verification first, optimization second**

---

## What is complete vs incomplete

### Already in place

- deterministic request-processing scaffold
- planner abstraction and fallback behavior
- strict validated tool-calling flow
- basic netlist parsing/writing
- basic deterministic analysis/transformation support
- protocol/logging required for contest-style interaction
- initial Yosys/ABC bridge layer

### Still to be extended

The current project is **not yet contest-complete**. It still needs richer analysis and transformation capabilities such as:

- every-path-through checks
- matched instance search by naming/pattern
- cone-size reporting
- same-clock-domain checks for DFFs
- transformation tools like replacing matched buffers with AND gates
- post-edit equivalence verification as a standard step
- structural hard-constraint checks
- cone-level and whole-design optimization flows

---

## Recommended next phase direction

The next development phase should keep the current architecture and make **Yosys + ABC the backbone backend tools**.

The intended backend workflow is:

**request → engine decides operation → transform if needed → Yosys normalize → ABC verify → structural checks → commit/reject → respond**

That preserves the current deterministic design while making the backend strong enough for contest-style transformation and optimization tasks.

---

## Summary

This repository should be understood as a **working deterministic scaffold** for ICCAD 2026 Problem A.

It already provides:
- the contest interaction shell
- the planner/validator/engine pipeline
- the current supported tools
- the debug/dev workflow
- the initial Yosys/ABC bridge layer

The next stage is to turn **Yosys into the normalization/export layer** and **ABC into the verification-first optimization layer**, while preserving the current JSON-tool architecture.

