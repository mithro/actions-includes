#!/usr/bin/env python3

import os
import sys
import tempfile
import urllib.request
import pathlib
import difflib

__dir__ = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, __dir__)
import actions_includes

USER, REPO = os.environ['GITHUB_REPOSITORY'].split('/', 1)
SHA = os.environ['GITHUB_SHA']

assert len(sys.argv) == 2
workflow_file = sys.argv[1]

# Download the workflow's yaml data
def get_file(filename):
    workflow_url = f"https://raw.githubusercontent.com/{USER}/{REPO}/{SHA}/{filename}"
    print("Downloading:", workflow_url)
    return urllib.request.urlopen(workflow_url).read().decode('utf-8')

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
new_workflow_data = actions_includes.expand_workflow(workflow_src, workflow_file)
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

sys.exit(len(diff))
