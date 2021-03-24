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


import os
import sys
import urllib.request
import pathlib
import difflib
import argparse


import actions_includes


USER, REPO = (None, None)
SHA = None


# Download the workflow's yaml data
def get_file(filename):
    workflow_url = f"https://raw.githubusercontent.com/{USER}/{REPO}/{SHA}/{filename}"
    print("Downloading:", workflow_url)
    return urllib.request.urlopen(workflow_url).read().decode('utf-8')


def main():
    ap = argparse.ArgumentParser(
        prog="check",
        description="Assert a workflow produced by actions-includes is up to date")
    ap.add_argument("workflow", type=str,
        help="Path to workflow file to check, relative to repo root")
    args = ap.parse_args()

    global USER, REPO
    global SHA
    USER, REPO = os.environ['GITHUB_REPOSITORY'].split('/', 1)
    SHA = os.environ['GITHUB_SHA']

    workflow_file = args.workflow
    workflow_data = get_file(workflow_file)

    # Workout what the source workflow file name was
    startpos = workflow_data.find(actions_includes.MARKER)
    endpos = workflow_data.find('\n', startpos)
    if startpos == -1 or endpos == -1:
        print()
        print('Unable to find generation marker in', workflow_file)
        print('-'*75)
        print(workflow_data)
        print('-'*75)
        sys.exit(1)

    workflow_srcfile = workflow_data[startpos+len(actions_includes.MARKER):endpos]
    workflow_srcpath = (pathlib.Path('/'+workflow_file).parent / workflow_srcfile).resolve()
    workflow_src = actions_includes.RemoteFilePath(USER, REPO, SHA, str(workflow_srcpath)[1:])
    print()
    print('Source of', workflow_file, 'is', workflow_srcfile, 'found at', workflow_src)
    print()
    new_workflow_data = actions_includes.expand_workflow(workflow_src, workflow_file, True)
    print()
    print('Workflow file at', workflow_file, 'should be:')
    print('-'*75)
    print(new_workflow_data)
    print('-'*75)
    print()


    diff = list(difflib.unified_diff(
        workflow_data.splitlines(True),
        new_workflow_data.splitlines(True),
        fromfile='a/'+workflow_file,
        tofile='b/'+workflow_file,
    ))
    if diff:
        print("Found the following differences:")
        print('-'*75)
        sys.stdout.writelines(diff)
        print('-'*75)

    return len(diff)


if __name__ == "__main__":
    sys.exit(main())
