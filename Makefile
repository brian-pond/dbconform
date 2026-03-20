# Requires: uv, git. Install dev tools with: uv sync --extra dev
release:
	uv run cz bump --increment patch
	git push
	uv pip install --force-reinstall .
	uv run python -m build
	uv run twine upload dist/*
