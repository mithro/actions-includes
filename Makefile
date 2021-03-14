#!/usr/bin/env python3
#
# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0

ACTIVATE=[[ -e venv/bin/activate ]] && source venv/bin/activate;

SHELL := /bin/bash

clean:
	rm -rf build dist actions_includes.egg-info

.PHONY: clean

venv-clean:
	rm -rf venv

.PHONY: venv-clean

venv: $(wildcard requirements*.txt)
	virtualenv --python=python3 venv
	${ACTIVATE} pip install -r requirements.txt
	${ACTIVATE} pip install -e .

.PHONY: venv

enter:
	${ACTIVATE} bash

.PHONY: enter


build: clean
	${ACTIVATE} python setup.py sdist bdist_wheel

.PHONY: build

# Run Python test suite
test:
	${ACTIVATE} pytest --verbose

.PHONY: test

# PYPI_TEST = --repository-url https://test.pypi.org/legacy/
PYPI_TEST = --repository testpypi

upload-test: build
	${ACTIVATE} twine upload ${PYPI_TEST}  dist/*

.PHONY: upload-test

upload: build
	${ACTIVATE} twine upload --verbose dist/*

.PHONY: upload

help:
	${ACTIVATE} python setup.py --help-commands

.PHONY: help

# Docker image building
image: build
	rm -f ./docker/*.tar.gz
	cp dist/*.tar.gz ./docker/
	docker build -t actions-includes docker

.PHONY: image

# Example GitHub action container launch command;
#  --name ghcriomithroactionsincludes_1d5649
#  --label 5588e4
#  --workdir /github/workspace
#  --rm
#  -e INPUT_WORKFLOW
#  -e HOME
#  -e GITHUB_JOB
#  -e GITHUB_REF
#  -e GITHUB_SHA
#  -e GITHUB_REPOSITORY
#  -e GITHUB_REPOSITORY_OWNER
#  -e GITHUB_RUN_ID
#  -e GITHUB_RUN_NUMBER
#  -e GITHUB_RETENTION_DAYS
#  -e GITHUB_ACTOR
#  -e GITHUB_WORKFLOW
#  -e GITHUB_HEAD_REF
#  -e GITHUB_BASE_REF
#  -e GITHUB_EVENT_NAME
#  -e GITHUB_SERVER_URL
#  -e GITHUB_API_URL
#  -e GITHUB_GRAPHQL_URL
#  -e GITHUB_WORKSPACE
#  -e GITHUB_ACTION
#  -e GITHUB_EVENT_PATH
#  -e GITHUB_ACTION_REPOSITORY
#  -e GITHUB_ACTION_REF
#  -e GITHUB_PATH
#  -e GITHUB_ENV
#  -e RUNNER_OS
#  -e RUNNER_TOOL_CACHE
#  -e RUNNER_TEMP
#  -e RUNNER_WORKSPACE
#  -e ACTIONS_RUNTIME_URL
#  -e ACTIONS_RUNTIME_TOKEN
#  -e ACTIONS_CACHE_URL
#  -e GITHUB_ACTIONS=true
#  -e CI=true
#  -v "/var/run/docker.sock":"/var/run/docker.sock"
#  -v "/home/runner/work/_temp/_github_home":"/github/home"
#  -v "/home/runner/work/_temp/_github_workflow":"/github/workflow"
#  -v "/home/runner/work/_temp/_runner_file_commands":"/github/file_commands"
#  -v "/home/runner/work/actions-includes/actions-includes":"/github/workspace"
#  ghcr.io/mithro/actions-includes
#  "action.yml"

image-test: image
	GITHUB_REPOSITORY=mithro/actions-includes \
	GITHUB_SHA=$$(git rev-parse HEAD) \
	docker run \
		--workdir /github/workspace \
		--rm \
		-e GITHUB_SHA \
		-e GITHUB_REPOSITORY \
		-v "$$PWD":"/github/workspace" \
		actions-includes \
		.github/workflows/local.yml

.PHONY: image


# Update the GitHub action workflows
WORKFLOWS = $(addprefix .github/workflows/test.,$(notdir $(wildcard ./tests/workflows/*.yml)))

.github/workflows/test.%.yml: tests/workflows/%.yml actions_includes/__init__.py
	@echo
	@echo "Updating $@"
	@echo "--------------------------------------"
	${ACTIVATE} cd tests && python -m actions_includes ../$< ../$@
	@echo "--------------------------------------"

update-workflows: $(WORKFLOWS)
	@true

.PHONY: update-workflows

# Redirect anything else to setup.py
%:
	${ACTIVATE} python setup.py $@
