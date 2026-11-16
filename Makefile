.PHONY: install dev test lint cover dry-run eval ablations benchmark clean

install:
	pip install -e .

dev:
	pip install -e ".[dev,mining]"

test:
	pytest

lint:
	ruff check prlens tests

cover:
	pytest --cov=prlens --cov-report=term-missing

dry-run:
	python -m prlens.cli --fixture tests/fixtures/pr_injected_bug.json --dry-run --simulate --repo-root tests/fixtures

# Phase 8 — produces the ablation table and charts in evaluation/results/.
eval:
	python -m evaluation.ablations --benchmark evaluation/benchmark/prs.jsonl --out evaluation/results

ablations: eval

benchmark:
	python -m mining.build_benchmark --help

clean:
	rm -rf .prlens_cache .pytest_cache .ruff_cache **/__pycache__ *.egg-info
