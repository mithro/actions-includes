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


ENTRYPOINT ["/action-includes/check_workflow.py"]
