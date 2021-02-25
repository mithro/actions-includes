#!/usr/bin/env python3
#
# Copyright (C) 2017-2021  The SymbiFlow Authors.
#
# Use of this source code is governed by a ISC-style
# license that can be found in the LICENSE file or at
# https://opensource.org/licenses/ISC
#
# SPDX-License-Identifier: ISC


import os
import pathlib
import subprocess
import sys
import urllib
import urllib.request
import pprint
import yaml


_git_root_output = subprocess.check_output(
    ['git', 'rev-parse', '--show-toplevel'])

GIT_ROOT = pathlib.Path(_git_root_output.decode(
    'utf-8').strip()).resolve()


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
            printerr('Before:', repr(yaml_item))
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
            printerr('After:', repr(yaml_item))
    return yaml_item


def get_action_yaml(action_name):
    action_filename = None
    if action_name.startswith('./'):
        action_filename = GIT_ROOT.join(action_name).resolve()
    elif action_name.startswith('/'):
        action_dirname = (
            GIT_ROOT / '.github' / 'actions' / action_name[1:]).resolve()
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

    if not action_filename:
        assert not action_name.startswith('docker://'), action_name
        if '@' not in action_name:
            action_name = action_name + '@main'

        repo_plus_path, ref = action_name.split('@', 1)
        if repo_plus_path.count('/') == 1:
            repo_plus_path += '/'

        user, repo, path = repo_plus_path.split('/', 2)
        if path and not path.endswith('/'):
            path = path + '/'

        urlnames = [
            'https://raw.githubusercontent.com/{user}/{repo}/{ref}/{path}{f}'.format(
                user=user, repo=repo, ref=ref, path=path, f=f)
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
                '\n'.join(['Did not find {}, errors:'] + [
                    '  {}: {}'.format(k, str(v))
                    for k, v in sorted(errors.items())
                ]))
    else:
        with open(action_filename) as f:
            yaml_data = f.read()

    yaml_data = yaml_load_and_expand(yaml_data)
    assert 'runs' in yaml_data, pprint.pformat(yaml_data)
    assert yaml_data['runs'].get(
        'using', None) == 'includes', pprint.pformat(yaml_data)
    return yaml_data


def expand_steps_list(yaml_list):
    out_list = []
    for i, v in list(enumerate(yaml_list)):
        if 'includes' not in v:
            # Support the `/{name}` format on `uses` values.
            uses = v.get('uses', 'Run cmd')
            printerr('Uses:', uses)
            if uses.startswith('/'):
                v['uses'] = './.github/actions' + uses

            out_list.append(v)
            continue

        printerr('Including:', v['includes'])
        include_yamldata = get_action_yaml(v['includes'])

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

            out_list.append(step)

    return out_list


def expand_list(yaml_list):
    for i, v in list(enumerate(yaml_list)):
        yaml_list[i] = expand(v)
    return yaml_list


def expand_dict(yaml_dict):
    for k, v in list(yaml_dict.items()):
        if k == 'steps':
            yaml_dict[k] = expand_steps_list(v)
        else:
            yaml_dict[k] = expand(v)
    return yaml_dict


def expand(yaml_item):
    if isinstance(yaml_item, dict):
        return expand_dict(yaml_item)
    elif isinstance(yaml_item, list):
        return expand_list(yaml_item)
    else:
        return yaml_item


def yaml_load_and_expand(yaml_data):
    return expand(yaml.load(yaml_data, Loader=yaml.FullLoader))


def str_presenter(dumper, data):
    """Use the bar form for multiline strings."""
    if '\n' in data:
        return dumper.represent_scalar(
            'tag:yaml.org,2002:str', data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


yaml.add_representer(str, str_presenter)


def main(args):
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

    with open(from_filename) as f:
        input_data = f.read()

    while input_data[0] == '#':
        n = input_data.find('\n')
        assert n != '-1', repr(input_data)
        to_file.write(input_data[:n + 1])
        input_data = input_data[n + 1:]

    to_file.write("""
# !! WARNING !!
# Do not modify this file directly! It is generated from
# {}

""".format(str(src_path)))

    data = yaml_load_and_expand(input_data)
    yaml.dump(data, stream=to_file, allow_unicode=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
