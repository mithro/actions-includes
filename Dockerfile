FROM python:slim-buster

# Update and install the python3-yaml package.
RUN \
	python --version \
	&& pip --version

# Install the actions-includes tool
COPY . /action-includes
RUN \
	cd /action-includes \
	&& pip install . --progress-bar off

# Check the installed actions-includes tool
RUN \
	cd /action-includes \
	&& python -m actions_includes tests/workflows/local.yml -

ENTRYPOINT ["/action-includes/check_workflow.py"]
