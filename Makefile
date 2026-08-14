# The repo venv, not a bare `python` — macOS ships no `python` on PATH, only `python3`,
# and the venv is where `build` is actually installed.
PYTHON ?= venv/bin/python

.PHONY: clean build upload upload-test

clean:
	rm -rf dist/ build/ *.egg-info

build: clean
	$(PYTHON) -m build

upload: build
	twine upload dist/*

upload-test: build
	twine upload --repository testpypi dist/*
