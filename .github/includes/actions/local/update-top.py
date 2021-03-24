#!/usr/bin/env python3

import pathlib
import os

__dir__ = pathlib.Path(__file__).parent.resolve()

local_action_yml = __dir__ / 'action.yml'
top_action_yml = (__dir__ / '..' / '..' / '..' / '..' / 'action.yml').resolve()

print('Local action.yml file at:', local_action_yml)
print(  'Top action.yml file at:', top_action_yml)

with open(local_action_yml) as f:
    action_data = f.read()

action_data = action_data.replace(
    '../../../../docker/Dockerfile',
    'docker://ghcr.io/mithro/actions-includes/image:main',
)

action_data = action_data.replace(
    'name: actions-includes',
    """\
# WARNING! Don't modify this file, modify
#  ./.github/includes/actions/local/action.yml
# and then run `make action.yml`.

name: actions-includes""")

with open(top_action_yml, 'w') as f:
    f.write(action_data)
