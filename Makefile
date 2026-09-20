.PHONY: test test-verbose test-one benchmark run run-debug run-gemini-required run-no-llm clean show-results

test:
	pytest -q

test-verbose:
	pytest -v -s

test-one:
	pytest -v -s $(FILE)

benchmark:
	python3 scripts/benchmark.py

run:
	python src/app.py -config config.yaml

run-debug:
	python src/app.py -config config.yaml --debug

run-gemini-required:
	python src/app.py -config config.yaml --debug --require-llm

run-no-llm:
	python src/app.py --no-llm --debug

report:
	pdflatex implementation_report.tex
	pdflatex implementation_report.tex  # Run twice for references

show-results:
	ls -la results && \
	echo '\n--- latest_planner_meta.json ---' && cat results/latest_planner_meta.json && \
	echo '\n--- latest_validated_tool.json ---' && cat results/latest_validated_tool.json && \
	echo '\n--- latest_tool_output_summary.txt ---' && cat results/latest_tool_output_summary.txt

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.log" -delete
	rm -rf benchmarks/results

run-ui:
	python -m uvicorn ui_server:app --reload --port 8000
