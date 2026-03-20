release:
	cz bump --increment patch
    git push
	pip install --force-reinstall .
	python -m build
	twine upload dist/*
