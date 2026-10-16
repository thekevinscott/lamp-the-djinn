.PHONY: help install test test-watch test-integration test-fast clean

help:  ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install development dependencies
	uv sync --all-extras

test:  ## Run all tests
	uv run pytest

test-watch:  ## Run tests in watch mode (auto-rerun on file changes)
	uv run ptw . --now

test-integration:  ## Run integration tests only
	uv run pytest -m integration

test-fast:  ## Run fast unit tests only
	uv run pytest -m unit

clean:  ## Clean up Python cache files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
