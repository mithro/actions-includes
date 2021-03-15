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


import copy
import hashlib
import os
import pathlib
import pprint
import re
import subprocess
import tempfile
import yaml

from collections import defaultdict

from yaml.constructor import FullConstructor

from pprint import pprint as p

from . import expressions as exp
from .files import LocalFilePath, RemoteFilePath
from .files import get_filepath
from .files import get_filepath_data
from .output import printerr, printdbg


MARKER = "It is generated from: "
INCLUDE_ACTION_NAME = 'mithro/actions-includes@main'


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
    yaml_data = yaml_load_and_expand(action_filepath, data)
    assert 'runs' in yaml_data, (type(yaml_data), yaml_data)
    assert yaml_data['runs'].get(
        'using', None) == 'includes', pprint.pformat(yaml_data)
    return yaml_data


JOBS_YAML_NAMES = [
    '/workflow.yml',
    '/workflow.yaml',
]


def get_workflow_data(current_workflow, jobs_name):
    jobs_dirpath = get_filepath(current_workflow, jobs_name)
    printerr("get_workflow_data:", current_workflow, jobs_name, jobs_dirpath)

    errors = {}
    for f in JOBS_YAML_NAMES:
        jobs_filepath = jobs_dirpath._replace(path=str(jobs_dirpath.path)+f)

        data = get_filepath_data(jobs_filepath)

        errors[jobs_filepath] = data
        if isinstance(data, str):
            break
    else:
        raise IOError(
            '\n'.join([
                    'Did not find {} (in {}), errors:'.format(
                        jobs_name, current_workflow),
                ] + [
                    '  {}: {}'.format(k, str(v))
                    for k, v in sorted(errors.items())
                ]))

    printerr("Including:", jobs_filepath)
    yaml_data = yaml_load_and_expand(jobs_filepath, data)
    assert 'jobs' in yaml_data, pprint.pformat(yaml_data)
    return yaml_data


RE_EXP = re.compile('\\${{(.*?)}}', re.DOTALL)


def simplify_expressions(yaml_item, context):
    """

    >>> simplify_expressions('${{ hello }}', {'hello': 'world'})
    'world'
    >>> simplify_expressions(exp.Value('hello'), {'hello': 'world'})
    'world'

    >>> simplify_expressions('${{ hello }}-${{ world }}', {'hello': 'world'})
    'world-${{ world }}'

    >>> step = YamlMap({
    ...     'if': "startswith(inputs.os, 'ubuntu')",
    ...     'name': '🚧 Build distribution 📦',
    ...     'uses': 'RalfG/python-wheels-manylinux-build@v0.3.3-manylinux2010_x86_64',
    ...     'str': '${{ inputs.empty }}',
    ...     'with': YamlMap({
    ...         'build-requirements': 'cython',
    ...         'pre-build-command': 'bash ',
    ...         'python-versions': '${{ manylinux-versions[inputs.python-version] }}'
    ...     }.items()),
    ... }.items())
    >>> inputs = {
    ...     'os': exp.Lookup('matrix', 'os'),
    ...     'python-version': exp.Lookup('matrix', 'python-version'),
    ...     'root_branch': 'refs/heads/master',
    ...     'root_user': 'SymbiFlow',
    ...     'empty': '',
    ... }
    >>> p(simplify_expressions(step, {'inputs': inputs, 'manylinux-versions': {'blah'}}))
    {'if': "startswith(inputs.os, 'ubuntu')",
     'name': '🚧 Build distribution 📦',
     'uses': 'RalfG/python-wheels-manylinux-build@v0.3.3-manylinux2010_x86_64',
     'str': '',
     'with': {'build-requirements': 'cython',
              'pre-build-command': 'bash ',
              'python-versions': Lookup('manylinux-versions', Lookup('matrix', 'python-version'))}}

    """
    assert not isinstance(yaml_item, dict), (type(yaml_item), yaml_item)
    if isinstance(yaml_item, YamlMap):
        for k, v in list(yaml_item.items()):
            yaml_item.replace(k, simplify_expressions(v, context))
    elif isinstance(yaml_item, list):
        for i in range(0, len(yaml_item)):
            yaml_item[i] = simplify_expressions(yaml_item[i], context)
    elif isinstance(yaml_item, exp.Expression):
        yaml_item = exp.simplify(yaml_item, context)
    elif isinstance(yaml_item, str):
        yaml_item_stripped = yaml_item.strip()

        exp_bits = yaml_item_stripped[:3] + yaml_item_stripped[-2:]
        mid_bits = yaml_item_stripped[3:-2]

        if exp_bits == '${{}}' and '${{' not in mid_bits:
            yaml_item = exp.parse(yaml_item_stripped)
            yaml_item = exp.simplify(yaml_item, context)
        else:
            def replace_exp(m):
                e = m.group(1).strip()
                v = exp.simplify(e, context)
                if isinstance(v, exp.Expression):
                    return '${{ %s }}' % (v,)
                else:
                    return str(v)

            yaml_item = RE_EXP.sub(replace_exp, yaml_item)
    return yaml_item


def step_type(m):
    assert isinstance(m, YamlMap), m
    if 'run' in m:
        return 'run'
    elif 'uses' in m:
        return 'uses'
    elif 'includes' in m:
        return 'includes'
    elif 'includes-script' in m:
        return 'includes-script'
    else:
        raise ValueError('Unknown step type:\n' + pprint.pformat(m))


def pop_if_exp(d):
    if 'if' not in d:
        return True

    v = d['if']
    d.replace('if', None)
    if isinstance(v, exp.Expression):
        return v
    if not isinstance(v, str):
        return v
    v = v.strip()
    if not v.startswith('${{'):
        assert '${{' not in v, (v, d)
        assert not v.endswith('}}'), (v, d)
        v = "${{ %s }}" % v
    return exp.parse(v)


def expand_step_includes(current_action, out_list, include_step):
    assert step_type(include_step) == 'includes', (current_action, out_list, include_step)

    include_if = pop_if_exp(include_step)

    include_yamldata = get_action_data(current_action, include_step['includes'])

    # Calculate the inputs dictionary
    if 'inputs' not in include_yamldata:
        include_yamldata['inputs'] = {}

    with_data = include_step.get('with', {})

    inputs = {}
    for in_name, in_info in include_yamldata['inputs'].items():
        v = None
        if 'default' in in_info:
            v = in_info['default']
        if in_name in with_data:
            v = with_data[in_name]

        if in_info.get('required', False):
            assert v is not None, (in_name, in_info, with_data)

        inputs[in_name] = exp.parse(v)

    context = dict(include_yamldata)
    context['inputs'] = inputs
    printdbg('\nInclude Step:\n', pprint.pformat(include_step))
    printdbg('Inputs:\n', pprint.pformat(inputs))
    printdbg('Include If:', repr(include_if))
    printdbg('\n')

    assert 'runs' in include_yamldata, include_yamldata
    assert 'steps' in include_yamldata['runs'], include_yamldata['steps']

    steps = include_yamldata['runs']['steps']
    while len(steps) > 0:
        step = steps.pop(0)
        step_if = pop_if_exp(step)
        printdbg('\nStep:', include_step['includes']+'#'+str(len(out_list)))
        printdbg('Inputs:\n', pprint.pformat(inputs))
        printdbg('Before:\n', pprint.pformat(step))
        printdbg('Before Step If:', repr(step_if))
        step = simplify_expressions(step, context)
        printdbg('---')
        current_if = exp.AndF(include_if, exp.simplify(step_if, context))
        printdbg('After:\n', pprint.pformat(step))
        printdbg('After If:', repr(current_if))
        printdbg('\n', end='')

        if isinstance(current_if, exp.Expression):
            step.replace('if', current_if, allow_missing=True)
        elif current_if in (False, None, ''):
            continue
        else:
            assert current_if is True, (current_if, repr(current_if))
            if 'if' in step:
                del step['if']

        out_list.append(step)


def expand_step_includes_script(current_action, out_list, v):
    assert step_type(v) == 'includes-script', (current_action, out_list, v)

    script = v.pop('includes-script')
    script_file = str((pathlib.Path('/'+current_action.path).parent / script).resolve())[1:]
    printerr(f"Including script: {script} (relative to {current_action}) found at {script_file}")

    script_filepath = get_filepath(current_action, './'+script_file)
    script_data = get_filepath_data(script_filepath)

    v['run'] = script_data
    if 'shell' not in v:
        if script.endswith('.py'):
            # Standard shell, no `{0}` needed.
            v['shell'] = 'python'
        elif script.endswith('.ps1'):
            # Standard shell, no `{0}` needed.
            v['shell'] = 'pwsh'
        elif script.endswith('.cmd'):
            # Standard shell, no `{0}` needed.
            v['shell'] = 'cmd'
        elif script.endswith('.rb'):
            # Non-standard shell, `{0}` needed.
            v['shell'] = 'ruby {0}'
        elif script.endswith('.pl'):
            # Non-standard shell, `{0}` needed.
            v['shell'] = 'perl {0}'
        elif script.endswith('.cmake'):
            # Non-standard shell, `{0}` needed.
            v['shell'] = 'cmake -P {0}'
        elif script.endswith('.sh'):
            # Standard shell, no `{0}` needed.
            v['shell'] = 'bash'

    expand_step_run(current_action, out_list, v)


def expand_step_uses(current_action, out_list, v):
    assert step_type(v) == 'uses', (current_action, out_list, v)
    # Support the `/{name}` format on `uses` values.
    if v['uses'].startswith('/'):
        v['uses'] = './.github/actions' + v['uses']

    out_list.append(v)


def expand_step_run(current_action, out_list, v):
    assert step_type(v) == 'run', (current_action, out_list, v)
    out_list.append(v)


def expand_steps_list(current_action, yaml_list):
    out_list = []
    for i, v in list(enumerate(yaml_list)):
        {
            'run': expand_step_run,
            'uses': expand_step_uses,
            'includes': expand_step_includes,
            'includes-script': expand_step_includes_script,
        }[step_type(v)](current_action, out_list, v)
    return out_list


def expand_list(current_action, yaml_list):
    for i, v in list(enumerate(yaml_list)):
        yaml_list[i] = expand(current_action, v)
    return yaml_list


def expand_jobs_includes(current_workflow, ojobname, include_jobs):
    if not ojobname:
        ojobname = ''
    include_yamldata = get_workflow_data(current_workflow, include_jobs['includes'])
    assert 'jobs' in include_yamldata, pprint.pformat(include_yamldata)

    ojob_needs = include_jobs.get('needs', [])
    if not isinstance(ojob_needs, list):
        ojob_needs = [ojob_needs]

    # Calculate the inputs dictionary
    if 'inputs' not in include_yamldata:
        include_yamldata['inputs'] = {}

    with_data = include_jobs.get('with', {})

    inputs = {}
    for in_name, in_info in include_yamldata['inputs'].items():
        v = None
        if 'default' in in_info:
            v = in_info['default']
        if in_name in with_data:
            v = with_data[in_name]

        if in_info.get('required', False):
            assert v is not None, (in_name, in_info, with_data)

        inputs[in_name] = exp.parse(v)

    context = dict(include_yamldata)
    context['inputs'] = inputs
    printdbg('\nInclude Jobs:\n', pprint.pformat(include_jobs))
    printdbg('Inputs:\n', pprint.pformat(inputs))
    printdbg('\n')

    new_jobs = []
    for i, jobname in enumerate(include_yamldata['jobs']):
        jobs_map = include_yamldata['jobs'][jobname]
        jobs_if = pop_if_exp(jobs_map)

        printdbg('\nJob:', f'{ojobname}#{i} - {jobname}')
        printdbg('Inputs:\n', pprint.pformat(inputs))
        printdbg('Before:\n', pprint.pformat(jobs_map))
        printdbg('Before Job If:', repr(jobs_if))
        jobs_map_out = simplify_expressions(jobs_map, context)
        printdbg('---')
        current_if = exp.simplify(jobs_if, context)
        printdbg('After:\n', pprint.pformat(jobs_map_out))
        printdbg('After If:', repr(current_if))
        printdbg('\n', end='')

        new_needs = list(ojob_needs)
        if 'needs' in jobs_map:
            job_needs = jobs_map['needs']
            if isinstance(job_needs, list):
                for i in job_needs:
                    new_needs.append(ojobname+i)
            elif isinstance(job_needs, str):
                new_needs.append(ojobname+job_needs)
            else:
                assert False, (job_needs, jobs_map)

        if len(new_needs) > 1:
            jobs_map.replace('needs', new_needs, allow_missing=True)
        elif len(new_needs) == 1:
            jobs_map.replace('needs', new_needs[0], allow_missing=True)

        if isinstance(current_if, exp.Expression):
            jobs_map_out['if'] = current_if
        elif current_if in (False, None, ''):
            continue
        else:
            assert current_if is True, (current_if, repr(current_if))
            if 'if' in jobs_map_out:
                del jobs_map_out['if']

        new_jobs.append((ojobname+jobname, jobs_map_out))

    jobnames = [n for n, m in new_jobs]+ojob_needs
    for n, job_map in new_jobs:
        if 'needs' not in job_map:
            continue
        needs = job_map['needs']
        if isinstance(needs, str):
            needs = [needs]
        for j in needs:
            assert j in jobnames or j in ojob_needs, (j, jobnames)

    return new_jobs


def expand_jobs_map(current_workflow, yaml_map):
    yaml_map_out = YamlMap()
    for k, v in yaml_map.items():
        assert isinstance(v, YamlMap), pprint.pformat((k, v))
        if 'includes' in v:
            for jobname, jobinfo in expand_jobs_includes(current_workflow, k, v):
                yaml_map_out[jobname] = jobinfo
        else:
            yaml_map_out[k] = expand(current_workflow, v)
    return yaml_map_out


def expand_yamlmap(current_action, yaml_map):
    #print('expand_yamlmap', current_action, yaml_map)
    yaml_map_out = YamlMap()
    for k, v in yaml_map.items():
        if k == 'steps':
            yaml_map_out[k] = expand_steps_list(current_action, v)
        elif k == 'jobs':
            yaml_map_out[k] = expand_jobs_map(current_action, v)
        else:
            yaml_map_out[k] = expand(current_action, v)
    return yaml_map_out


def expand(current_action, yaml_item):
    assert not isinstance(yaml_item, dict), (type(yaml_item), yaml_item)
    if isinstance(yaml_item, YamlMap):
        return expand_yamlmap(current_action, yaml_item)
    elif isinstance(yaml_item, list):
        return expand_list(current_action, yaml_item)
    else:
        return yaml_item

# ==============================================================
# PyYaml Loader / Dumper Customization
# ==============================================================



class YamlMap:

    """

    >>> y = YamlMap()
    >>> '1' in y
    False
    >>> y['1'] = 1
    >>> '1' in y
    True
    >>> y['1']
    1
    >>> y['1'] = 2
    >>> '1' in y
    True
    >>> y['1']
    Traceback (most recent call last):
      ...
    actions_includes.YamlMap.MultiKeyError: 'Multi key: 1 == [1, 2]'
    >>> y['2'] = 3
    >>> y['1'] = 4
    >>> list(y.items())
    [('1', 1), ('1', 2), ('2', 3), ('1', 4)]

    >>> del y['1']
    >>> list(y.items())
    [('2', 3)]

    >>> y['3'] = 4
    >>> y.replace('2', 5)
    >>> list(y.items())
    [('2', 5), ('3', 4)]

    """
    _MARKER = []

    class MultiKeyError(KeyError):
        pass

    def __init__(self, d=None):
        self.__i = 0
        self._keys = defaultdict(list)
        self._values = {}
        self._order = []
        if d:
            if hasattr(d, 'items'):
                d = d.items()
            for k, v in d:
                self[k] = v

    def __getitem__(self, k):
        if k not in self._keys:
            raise KeyError(f'No such key: {k}')
        r = [self._values[i] for i in self._keys[k]]
        if len(r) == 1:
            return r[0]
        raise self.MultiKeyError(f'Multi key: {k} == {r}')

    def __setitem__(self, k, v):
        self.__i += 1
        assert self.__i not in self._values
        assert self.__i not in self._order
        self._keys[k].append(self.__i)
        self._values[self.__i] = v
        self._order.append((self.__i, k))

    def replace(self, k, v, allow_missing=False):
        if k not in self._keys:
            if not allow_missing:
                raise KeyError(f'No such key: {k}')
            else:
                self[k] = None
        i = self._keys[k]
        if len(i) > 1:
            raise self.MultiKeyError(f'Multi key: {k} == {i}')
        self._values[i[0]] = v

    def __delitem__(self, k):
        if k not in self._keys:
            raise KeyError(f'No such key: {k}')
        to_remove = self._keys[k]
        for i in to_remove:
            del self._values[i]
            self._order.remove((i, k))
        del self._keys[k]

    def get(self, k, default=_MARKER):
        try:
            return self[k]
        except KeyError:
            if default is not self._MARKER:
                return default
            raise

    def __contains__(self, k):
        return k in self._keys

    class map_items:
        def __init__(self, m):
            self.m = m

        def __iter__(self):
            for i, k in self.m._order:
                v = self.m._values[i]
                yield (k, v)

        def __len__(self):
            return len(self.m)

    def items(self):
        return self.map_items(self)

    class map_keys:
        def __init__(self, m):
            self.m = m

        def __iter__(self):
            for i, k in self.m._order:
                yield k

        def __len__(self):
            return len(self.m)

    def keys(self):
        return self.map_keys(self)

    class map_values:
        def __init__(self, m):
            self.m = m

        def __iter__(self):
            for i, _ in self.m._order:
                yield self.m._values[i]

        def __len__(self):
            return len(self.m)

    def values(self):
        return self.map_values(self)

    def __iter__(self):
        return iter(self.keys())

    def __len__(self):
        return len(self._order)

    def __repr__(self):
        return repr(list(self.items()))

    def pop(self, k):
        v = self[k]
        del self[k]
        return v

    @staticmethod
    def presenter(dumper, data):
        return dumper.represent_mapping('tag:yaml.org,2002:map', data)

    @staticmethod
    def _pprint(p, object, stream, indent, allowance, context, level):
        _sort_dicts = p._sort_dicts
        p._sort_dicts = False
        p._pprint_dict(object, stream, indent, allowance, context, level)
        p._sort_dicts = _sort_dicts


pprint.PrettyPrinter._dispatch[YamlMap.__repr__] = YamlMap._pprint


def construct_yaml_map(self, node):
    data = YamlMap()
    yield data
    for key_node, value_node in node.value:
        key = self.construct_object(key_node, deep=True)
        val = self.construct_object(value_node, deep=True)
        data[key] = val


FullConstructor.add_constructor(u'tag:yaml.org,2002:map', construct_yaml_map)


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


def exp_presenter(dumper, data):
    return dumper.represent_scalar('tag:yaml.org,2002:str', '${{ '+str(data)+' }}')


yaml.add_multi_representer(exp.Expression, exp_presenter)
yaml.add_representer(str, str_presenter)
yaml.add_representer(None.__class__, none_presenter)
yaml.add_representer(On, On.presenter)
yaml.add_representer(YamlMap, YamlMap.presenter)

# ==============================================================


def yaml_load_and_expand(current_action, yaml_data):
    md5sum = hashlib.md5(yaml_data.encode('utf-8')).hexdigest()
    printerr(f'Loading yaml file {current_action} with contents md5 of {md5sum}')
    return expand(current_action, yaml.load(
        yaml_data, Loader=yaml.FullLoader))


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
            to_abspath = outpath.resolve()
            to_path = to_abspath.relative_to(repo_root)
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
