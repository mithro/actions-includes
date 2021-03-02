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
import pprint
import subprocess
import sys
import tempfile
import urllib
import urllib.request
import yaml

from collections import namedtuple


def printerr(*args, **kw):
    print(*args, file=sys.stderr, **kw)


DEBUG = bool(os.environ.get('DEBUG', False))


def printdbg(*args, **kw):
    if DEBUG:
        print(*args, file=sys.stderr, **kw)


MARKER = "It is generated from: "
INCLUDE_ACTION_NAME = 'mithro/actions-includes@main'


LocalFilePath = namedtuple('LocalFilePath', 'repo_root path')
RemoteFilePath = namedtuple('RemoteFilePath', 'user repo ref path')


def parse_remote_path(action_name):
    assert not action_name.startswith('docker://'), action_name
    if '@' not in action_name:
        action_name = action_name + '@main'

    repo_plus_path, ref = action_name.split('@', 1)
    assert '@' not in ref, action_name
    if repo_plus_path.count('/') == 1:
        repo_plus_path += '/'

    user, repo, path = repo_plus_path.split('/', 2)
    return RemoteFilePath(user, repo, ref, path)


def get_filepath(current, filepath):

    """
    >>> localfile_current = LocalFilePath(pathlib.Path('/path'), 'abc.yaml')
    >>> remotefile_current = RemoteFilePath('user', 'repo', 'ref', 'abc.yaml')

    Local path on local current becomes a local path.
    >>> get_filepath(localfile_current, './.github/actions/blah')
    LocalFilePath(repo_root=PosixPath('/path'), path=PosixPath('.github/actions/blah'))

    >>> get_filepath(localfile_current, '/blah')
    LocalFilePath(repo_root=PosixPath('/path'), path=PosixPath('.github/actions/blah'))

    Local path on current remote gets converted to a remote path.
    >>> get_filepath(remotefile_current, './.github/actions/blah')
    RemoteFilePath(user='user', repo='repo', ref='ref', path='.github/actions/blah')

    >>> get_filepath(remotefile_current, '/blah')
    RemoteFilePath(user='user', repo='repo', ref='ref', path='.github/actions/blah')
    """

    # Resolve '/$XXX' to './.github/actions/$XXX'
    if filepath.startswith('/'):
        filepath = '/'.join(
            ['.', '.github', 'actions', filepath[1:]])

    if filepath.startswith('./'):
        assert '@' not in filepath, (
            "Local name {} shouldn't have an @ in it".format(filepath))

    # If new is local but current is remote, rewrite to a remote.
    if isinstance(current, RemoteFilePath) and filepath.startswith('./'):
        old_filepath = filepath
        new_action = current._replace(path=filepath[2:])
        filepath = '{user}/{repo}/{path}@{ref}'.format(**new_action._asdict())
        printerr('Rewrite local action {} in remote repo {} to: {}'.format(
            old_filepath, current, filepath))

    # Local file
    if filepath.startswith('./'):
        assert isinstance(current, LocalFilePath), (current, filepath)
        localpath = (current.repo_root / filepath[2:]).resolve()
        repopath = localpath.relative_to(current.repo_root)
        return current._replace(path=repopath)

    # Remote file
    else:
        return parse_remote_path(filepath)


DOWNLOAD_CACHE = {}


def get_filepath_data(filepath):
    # Get local data
    if isinstance(filepath, LocalFilePath):
        filename = filepath.repo_root / filepath.path
        if not filename.exists():
            return IOError('{} does not exist'.format(filename))
        with open(filename) as f:
            return f.read()

    # Download remote data
    elif isinstance(filepath, RemoteFilePath):
        if filepath not in DOWNLOAD_CACHE:
            url = 'https://raw.githubusercontent.com/{user}/{repo}/{ref}/{path}'.format(
                **filepath._asdict())

            printerr("Trying to download {} ..".format(url), end=' ')
            try:
                yaml_data = urllib.request.urlopen(url).read().decode('utf-8')
                printerr('Success!')
            except urllib.error.URLError as e:
                yaml_data = e
                printerr('Failed ({})!'.format(e))

            DOWNLOAD_CACHE[filepath] = yaml_data
        return DOWNLOAD_CACHE[filepath]
    else:
        assert False


ACTION_YAML_NAMES = [
    '/action.yml',
    '/action.yaml',
]


def get_action_data(current_action, action_name):
    action_dirpath = get_filepath(current_action, action_name)
    printerr("get_action_data:", current_action, action_name, action_dirpath)

    errors = {}
    for f in ACTION_YAML_NAMES:
        action_filepath = action_dirpath._replace(path=str(action_dirpath.path)+f)

        data = get_filepath_data(action_filepath)

        errors[action_filepath] = data
        if isinstance(data, str):
            break
    else:
        raise IOError(
            '\n'.join([
                    'Did not find {} (in {}), errors:'.format(
                        action_name, current_action),
                ] + [
                    '  {}: {}'.format(k, str(v))
                    for k, v in sorted(errors.items())
                ]))

    printerr("Including:", action_filepath)
    yaml_data = yaml_load_and_expand(current_action, data)
    assert 'runs' in yaml_data, pprint.pformat(yaml_data)
    assert yaml_data['runs'].get(
        'using', None) == 'includes', pprint.pformat(yaml_data)
    return yaml_data


def to_eval_literal(v):
    """
    >>> to_eval_literal(None)
    'null'
    >>> to_eval_literal(True)
    'true'
    >>> to_eval_literal(False)
    'false'
    >>> to_eval_literal(711)
    '711'
    >>> to_eval_literal(2.0)
    '2.0'
    >>> to_eval_literal('Mona the Octocat')
    "'Mona the Octocat'"
    >>> to_eval_literal("It's open source")
    "'It''s open source'"
    """
    if isinstance(v, Value):
        return v
    # myNull: ${{ null }}
    elif v is None:
        return 'null'
    # myBoolean: ${{ false }}
    elif v is True:
        return 'true'
    elif v is False:
        return 'false'
    # myIntegerNumber: ${{ 711 }}
    # myFloatNumber: ${{ -9.2 }}
    # myExponentialNumber: ${{ -2.99-e2 }}
    elif isinstance(v, (int, float)):
        return str(v)
    # myString: ${{ 'Mona the Octocat' }}
    # myEscapedString: ${{ 'It''s open source!' }}
    elif isinstance(v, str):
        if "'" in v:
            v = v.replace("'", "''")
        return "'{}'".format(v)
    # myHexNumber: ${{ 0xff }}


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
                yaml_item = yaml_item.replace('inputs.' + f, to_eval_literal(t))
    return yaml_item


class Value(str):
    pass


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

        condition = None
        if 'if' in v:
            vs = v['if'].strip()
            if vs.startswith('${{'):
                assert vs.endswith('}}'), vs
                condition = Value(vs[3:-2].strip())
            else:
                condition = Value(vs)

        include_yamldata = get_action_data(current_action, v['includes'])

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

            v = inputs[in_name]
            if isinstance(v, str):
                vs = v.strip()
                if vs.startswith('${{'):
                    assert vs.endswith('}}'), vs
                    inputs[in_name] = Value(vs[3:-2].strip())

        assert 'runs' in include_yamldata, include_yamldata
        assert 'steps' in include_yamldata['runs'], include_yamldata['steps']

        steps = include_yamldata['runs']['steps']
        while len(steps) > 0:
            step = steps.pop(0)
            if 'if' in step:
                vs = step['if']
                assert isinstance(vs, str), vs
                vs = vs.strip()
                if not vs.startswith('${{'):
                    step['if'] = '${{ '+step['if']+' }}'

            printdbg('Inputs:', inputs)
            printdbg('Before:', step)
            replace_inputs(step, inputs)
            printdbg('After1:', step)
            if 'if' in step:
                vs = step['if']
                assert isinstance(vs, str), vs
                vs = vs.strip()
                assert vs.startswith('${{'), vs
                assert vs.endswith('}}'), vs
                step['if'] = vs[3:-2].strip()
            printdbg('After2:', step)

            if 'if' in step:
                if step['if'] == 'false':
                    continue
                if step['if'] == 'true':
                    del step['if']
            printdbg('After3:', step)

            if condition is not None:
                if 'if' in step:
                    step['if'] = '{} && ({})'.format(to_eval_literal(condition), step['if'])
                else:
                    step['if'] = to_eval_literal(condition)

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


def none_presenter(dumper, data):
    """Make empty values appear as nothing rather than 'null'"""
    assert data is None, data
    return dumper.represent_scalar('tag:yaml.org,2002:null', '')


class On:
    """`on` == `true`, so enable forcing it back to `on`"""

    @staticmethod
    def presenter(dumper, data):
        return dumper.represent_scalar('tag:yaml.org,2002:bool', 'on')


yaml.add_representer(str, str_presenter)
yaml.add_representer(None.__class__, none_presenter)
yaml.add_representer(On, On.presenter)


def expand_workflow(current_workflow, to_path):
    src_path = os.path.relpath('/'+str(current_workflow.path), start='/'+str(os.path.dirname(to_path)))
    if isinstance(current_workflow, LocalFilePath):
        dst_path = current_workflow.repo_root / to_path
    else:
        dst_path = to_path

    workflow_filepath = get_filepath(current_workflow, './'+str(current_workflow.path))
    printerr('Expanding workflow file from:', workflow_filepath)
    printerr('                          to:', to_path)
    workflow_data = get_filepath_data(workflow_filepath)
    if not isinstance(workflow_data, str):
        raise workflow_data
    workflow_data = workflow_data.splitlines()
    output = []
    while workflow_data[0] and workflow_data[0][0] == '#':
        output.append(workflow_data.pop(0))

    output.append("""
# !! WARNING !!
# Do not modify this file directly!
# !! WARNING !!
#
# {}
# using the script from https://github.com/{}
""".format(MARKER+str(src_path), INCLUDE_ACTION_NAME))

    data = yaml_load_and_expand(current_workflow, '\n'.join(workflow_data))
    new_data = {}
    new_data[On()] = data.pop(True)
    for k, v in data.items():
        new_data[k] = v
    data = new_data

    for j in data['jobs'].values():
        assert 'steps' in j, pprint.pformat(j)
        steps = j['steps']
        assert isinstance(steps, list), pprint.pformat(j)

        steps.insert(0, {
            'uses': INCLUDE_ACTION_NAME,
            # FIXME: This check should run on all platforms.
            'if': "runner.os == 'Linux'",
            'continue-on-error': False,
            'with': {
                'workflow': str(to_path),
            },
        })

    printdbg('')
    printdbg('Final yaml data:')
    printdbg('-'*75)
    printdbg(pprint.pformat(data))
    printdbg('-'*75)

    output.append(yaml.dump(data, allow_unicode=True, sort_keys=False, width=1000))

    return '\n'.join(output)


def main(args):
    tfile = None
    try:
        git_root_output = subprocess.check_output(
            ['git', 'rev-parse', '--show-toplevel'])

        repo_root = pathlib.Path(git_root_output.decode(
            'utf-8').strip()).resolve()

        _, from_filename, to_filename = args

        from_path = pathlib.Path(from_filename).resolve().relative_to(repo_root)
        if to_filename == '-':
            printerr("Expanding", from_filename, "to stdout")

            outdir = repo_root / '.github' / 'workflows'
            outdir.mkdir(parents=True, exist_ok=True)
            outfile = os.path.basename(from_filename)
            outpath = outdir / outfile
            i = 0
            while outpath.exists():
                printerr("File", outpath, "exists")
                outpath = outdir / f'{i}.{outfile}'
                i += 1

            tfile = outpath
            to_path = outpath
            to_abspath = outpath.resolve()
        else:
            printerr("Expanding", from_filename, "into", to_filename)
            to_abspath = pathlib.Path(to_filename).resolve()
            to_path = to_abspath.relative_to(repo_root)

        current_action = LocalFilePath(repo_root, str(from_path))
        out_data = expand_workflow(current_action, to_path)

        with open(to_abspath, 'w') as f:
            f.write(out_data)

        return 0
    finally:
        if tfile is not None:
            with open(tfile) as f:
                print(f.read())

            os.unlink(tfile)
            tfile = None
