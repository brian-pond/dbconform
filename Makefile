# Requires: uv, git. Install dev tools with: uv sync --extra dev

.PHONY: check-clean clean-dist build publish release

check-clean:
	@test -z "$$(git status --porcelain)" || (echo "Working tree not clean"; exit 1)

clean-dist:
	rm -rf dist build *.egg-info

build: clean-dist
	uv run python -m build

publish:
	uv run twine upload dist/*

release: check-clean
	uv run cz bump --increment patch
	git push --follow-tags
	$(MAKE) build
	$(MAKE) publish
