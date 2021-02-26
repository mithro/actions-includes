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

import setuptools


def get_version():
    from setuptools_scm.version import get_local_node_and_date
    def clean_scheme(version):
        return get_local_node_and_date(version) if version.dirty else ''

    return {
        'write_to': 'actions_includes/version.py',
        'version_scheme': 'post-release',
        'local_scheme': clean_scheme,
    }


with open("README.md", "r") as fh:
    long_description = fh.read()


setuptools.setup(
    name="actions-includes",
    use_scm_version = get_version,
    author="Tim 'mithro' Ansell",
    author_email="tansell@google.com",
    description="""\
Tool for flattening include statements in GitHub actions workflow.yml files.""",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/mithro/actions-includes",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: ISC License (ISCL)",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.8', # Needs ordered dictionaries
    install_requires = [
        "pyyaml",
    ],
    setup_requires = [
        "setuptools>=42",
        "wheel",
        "setuptools_scm[toml]>=3.4",
    ],
    entry_points={
        'console_scripts': ['fasm=fasm.tool:main'],
    },
    zip_safe=True,
    packages=setuptools.find_packages(),
    project_urls={
        "Bug Tracker": "https://github.com/mithro/actions-includes/issues",
        "Source Code": "https://github.com/mithro/actions-includes",
    },
)
