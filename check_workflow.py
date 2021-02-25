#!/usr/bin/env python3

import sys
import urllib.request

repo = os.environ['GITHUB_REPOSITORY']
sha = os.environ['GITHUB_SHA']
assert len(sys.argv) == 2
workflow = sys.argv[1]

# Download the workflow's yaml data
workflow_url = f"https://raw.githubusercontent.com/{repo}/{sha}/{workflow}"
data = urllib.request.urlopen(workflow_url).read().decode('utf-8')

# Workout what the source workflow file name was
startpos = data.find("# It is generated from: ")
endpos = data.find('\n', startpos)
if startpos == -1 or endpos == -1:
    print('Unable to find generation marker in', workflow_url)
    print('-'*75)
    print(data)
    print('-'*75)
    sys.exit(1)

workflow_src = data[startpos:endpos]
if not os.path.exists(workflow_src):
    print('Missing source file: '+workflow_src)
    sys.exit(1)

__dir__ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, __dir__)
import actions_include
retcode = actions_include.main(['', src_file, workflow])
if retcode != 0:
    sys.exit(retcode)

import subprocess
output = subprocess.check_output(['git', 'diff', workflow_file])
if output:
    print(output)
    sys.exit(1)
else:
    print(worflow_file, 'is up to date!')
    sys.exit(0)
