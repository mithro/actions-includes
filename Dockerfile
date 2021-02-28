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

FROM python:slim-buster

# Update and install the python3-yaml package.
RUN \
	apt update -qq \
	&& apt-get -y install git

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


ENTRYPOINT ["python3", "-m", "actions_includes.check"]
CMD ["--help"]
