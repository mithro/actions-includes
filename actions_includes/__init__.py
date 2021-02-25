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
import pathlib
import subprocess
import sys
import urllib
import urllib.request
import pprint
import yaml

from collections import namedtuple


INCLUDE_ACTION_NAME = 'mithro/actions-includes@main'


LocalAction = namedtuple('LocalAction', 'repo_root filename')
RemoteAction = namedtuple('RemoteAction', 'user repo ref path')


def parse_remote_action(action_name):
    assert not action_name.startswith('docker://'), action_name
    if '@' not in action_name:
        action_name = action_name + '@main'

    repo_plus_path, ref = action_name.split('@', 1)
    assert '@' not in ref, action_name
    if repo_plus_path.count('/') == 1:
        repo_plus_path += '/'

    user, repo, path = repo_plus_path.split('/', 2)
    if path and not path.endswith('/'):
        path = path + '/'

    return RemoteAction(user, repo, ref, path)


ACTION_YAML_NAMES = [
    'action.yml',
    'action.yaml',
]


def printerr(*args, **kw):
    print(*args, file=sys.stderr, **kw)


def replace_inputs(yaml_item, inputs):
    if isinstance(yaml_item, dict):
        for k in list(yaml_item.keys()):
            yaml_item[k] = replace_inputs(yaml_item[k], inputs)
    elif isinstance(yaml_item, list):
        for i in range(0, len(yaml_item)):
            yaml_item[i] = replace_inputs(yaml_item[i], inputs)
    elif yaml_item in inputs:
        return inputs[yaml_item]
    elif isinstance(yaml_item, str):
        if 'inputs.' in yaml_item:
            for f, t in inputs.items():
                if isinstance(t, str):
                    yt = t
                else:
                    yt = yaml.dump(t)
                    if yt.endswith('\n...\n'):
                        yt = yt[:-5]
                    if yt.endswith('\n'):
                        yt = yt[:-1]
                yaml_item = yaml_item.replace('inputs.' + f, yt)
            yaml_item = yaml.safe_load(yaml_item)
    return yaml_item



DOWNLOAD_CACHE = {}


def get_remote_action_yaml(remote_action):
    assert isinstance(remote_action, RemoteAction), remote_action
    if remote_action not in DOWNLOAD_CACHE:
        urlnames = [
            'https://raw.githubusercontent.com/{user}/{repo}/{ref}/{path}{f}'.format(
                f=f, **remote_action._asdict())
            for f in ACTION_YAML_NAMES
        ]
        errors = {}
        for u in urlnames:
            try:
                printerr("Trying to download {}..".format(u), end=' ')
                yaml_data = urllib.request.urlopen(u).read().decode('utf-8')
                printerr('Success!')
            except urllib.error.URLError as e:
                printerr('Failed!', e)
                errors[u] = str(e)
                continue
            break
        else:
            raise IOError(
                '\n'.join(['Did not find {}, errors:'.format(remote_action)] + [
                    '  {}: {}'.format(k, str(v))
                    for k, v in sorted(errors.items())
                ]))
        DOWNLOAD_CACHE[remote_action] = yaml_data
    return DOWNLOAD_CACHE[remote_action]



def get_action_yaml(current_action, action_name):
    # Resolve '/$XXX' to './.github/actions/$XXX'
    if action_name.startswith('/'):
        action_name = str(
            pathlib.Path('.') / '.github' / 'actions' / action_name[1:])

    if action_name.startswith('./'):
        assert '@' not in action_name, (
            "Local name {} shouldn't have an @ in it".format(action_name))

    # If action is local but current_action is remote, rewrite to a remote action.
    if isinstance(current_action, RemoteAction) and action_name.startswith('./'):
        old_action_name = action_name
        new_action = current_action._replace(path=action_name[2:])
        action_name = '{user}/{repo}/{path}@{ref}'.format(**new_action._asdict())
        printerr('Rewrite local action {} in remote repo {} to: {}'.format(
            old_action_name, current_action, action_name))

    # Local actions can just be read directly from disk.
    if action_name.startswith('./'):
        printerr('Including local:', action_name)
        assert isinstance(current_action, LocalAction), (current_action, action_name)
        action_dirname = (current_action.repo_root / action_name[2:]).resolve()
        if not action_dirname.exists():
            raise IOError('Directory {} not found for action {}'.format(
                action_dirname, action_name))
        action_files = [action_dirname / f for f in ACTION_YAML_NAMES]
        for f in action_files:
            if f.exists():
                action_filename = f.resolve()
                break
        else:
            raise IOError("No action.yml or action.yaml file in {}".format(
                action_dirname))

        with open(action_filename) as f:
            yaml_data = f.read()

    # Remove actions have to be downloaded
    else:
        printerr('Including remote:', action_name)
        current_action = parse_remote_action(action_name)
        yaml_data = get_remote_action_yaml(current_action)

    yaml_data = yaml_load_and_expand(current_action, yaml_data)
    assert 'runs' in yaml_data, pprint.pformat(yaml_data)
    assert yaml_data['runs'].get(
        'using', None) == 'includes', pprint.pformat(yaml_data)
    return yaml_data


def expand_steps_list(current_action, yaml_list):
    out_list = []
    for i, v in list(enumerate(yaml_list)):
        if 'includes' not in v:
            # Support the `/{name}` format on `uses` values.
            uses = v.get('uses', 'Run cmd')
            if uses.startswith('/'):
                v['uses'] = './.github/actions' + uses

            out_list.append(v)
            continue

        condition = v.get('if', True)
        if condition is False:
            continue

        if isinstance(current_action, LocalAction):
            if not out_list or out_list[0].get('uses', '') != INCLUDE_ACTION_NAME:
                out_list.insert(0, {
                    'uses': INCLUDE_ACTION_NAME,
                    'continue-on-error': False,
                    'with': {
                        'workflow': str(os.path.relpath(
                            current_action.filename, current_action.repo_root)),
                    },
                })

        include_yamldata = get_action_yaml(current_action, v['includes'])

        if 'inputs' not in include_yamldata:
            include_yamldata['inputs'] = {}

        with_data = v.get('with', {})

        inputs = {}
        for in_name, in_info in include_yamldata['inputs'].items():
            if 'default' in in_info:
                inputs[in_name] = in_info['default']
            if in_name in with_data:
                inputs[in_name] = with_data[in_name]

            if in_info.get('required', False):
                assert in_name in inputs, (in_name, in_info, with_data)

        assert 'runs' in include_yamldata, include_yamldata
        assert 'steps' in include_yamldata['runs'], include_yamldata['steps']

        steps = include_yamldata['runs']['steps']
        while len(steps) > 0:
            step = steps.pop(0)
            replace_inputs(step, inputs)

            if 'if' in step:
                if step['if'] is False:
                    continue
                if step['if'] is True:
                    del step['if']

            if condition is not True:
                if 'if' in step:
                    step['if'] = '{} && ({})'.format(condition, step['if'])
                else:
                    step['if'] = condition

            out_list.append(step)

    return out_list


def expand_list(current_action, yaml_list):
    for i, v in list(enumerate(yaml_list)):
        yaml_list[i] = expand(current_action, v)
    return yaml_list


def expand_dict(current_action, yaml_dict):
    for k, v in list(yaml_dict.items()):
        if k == 'steps':
            yaml_dict[k] = expand_steps_list(current_action, v)
        else:
            yaml_dict[k] = expand(current_action, v)
    return yaml_dict


def expand(current_action, yaml_item):
    if isinstance(yaml_item, dict):
        return expand_dict(current_action, yaml_item)
    elif isinstance(yaml_item, list):
        return expand_list(current_action, yaml_item)
    else:
        return yaml_item


def yaml_load_and_expand(current_action, yaml_data):
    return expand(current_action, yaml.load(
        yaml_data, Loader=yaml.FullLoader))


def str_presenter(dumper, data):
    """Use the bar form for multiline strings."""
    if '\n' in data:
        return dumper.represent_scalar(
            'tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


yaml.add_representer(str, str_presenter)


def main(args):
    git_root_output = subprocess.check_output(
        ['git', 'rev-parse', '--show-toplevel'])

    repo_root = pathlib.Path(git_root_output.decode(
        'utf-8').strip()).resolve()

    _, from_filename, to_filename = args

    from_filename = pathlib.Path(from_filename).resolve()
    if to_filename == '-':
        printerr("Expanding", from_filename, "to stdout")
        src_path = str(from_filename)
        to_file = sys.stdout
    else:
        to_filename = pathlib.Path(to_filename).resolve()
        printerr("Expanding", from_filename, "into", to_filename)
        src_path = os.path.relpath(from_filename, start=to_filename.parent)
        to_file = open(to_filename, 'w')

    current_action = LocalAction(repo_root, to_filename)

    with open(from_filename) as f:
        input_data = f.read()

    while input_data[0] == '#':
        n = input_data.find('\n')
        assert n != '-1', repr(input_data)
        to_file.write(input_data[:n + 1])
        input_data = input_data[n + 1:]

    to_file.write("""
# !! WARNING !!
# Do not modify this file directly!
# !! WARNING !!
#
# It is generated from: {}
# using the script from https://github.com/mithro/actions-includes

""".format(str(src_path)))

    data = yaml_load_and_expand(current_action, input_data)
    yaml.dump(data, stream=to_file, allow_unicode=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
