release:
	cz bump --increment patch
	pip install --force-reinstall .
	python -m build
	twine upload dist/*
