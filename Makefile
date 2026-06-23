.PHONY: install playground run

install:
	uv sync

playground:
	agents-cli playground --port 8085

run:
	uv run python expense_agent/agent_runtime_app.py

