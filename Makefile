release:
	cz bump
	pip install --force-reinstall .
	python -m build
	twine upload dist/*
