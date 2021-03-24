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
import subprocess
import argparse

from ruamel import yaml
from ruamel.yaml import resolver
from ruamel.yaml import util
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.constructor import RoundTripConstructor
from ruamel.yaml.nodes import MappingNode

from pprint import pprint as p

from . import expressions as exp
from .files import LocalFilePath, RemoteFilePath
from .files import get_filepath
from .files import get_filepath_data
from .output import printerr, printdbg


MARKER = "It is generated from: "
INCLUDE_ACTION_NAME = 'mithro/actions-includes@main'

# -----------------------------------------------------------------------------
# Get Data
# -----------------------------------------------------------------------------

ACTION_YAML_NAMES = [
    '/action.yml',
    '/action.yaml',
]


def get_action_data(current_action, action_name):
    if isinstance(action_name, str):
        action_dirpath = get_filepath(current_action, action_name, 'action')
    else:
        assert isinstance(action_name, files.FilePath), (type(action_name), action_name)
        action_dirpath = action_name
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
    yaml_data = yaml_load(action_filepath, data)
    assert 'runs' in yaml_data, (type(yaml_data), yaml_data)
    assert yaml_data['runs'].get(
        'using', None) == 'includes', pprint.pformat(yaml_data)
    return action_filepath, yaml_data


JOBS_YAML_NAMES = [
    '/workflow.yml',
    '/workflow.yaml',
]


def get_workflow_data(current_workflow, jobs_name):
    jobs_dirpath = get_filepath(current_workflow, jobs_name, 'workflow')
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
    yaml_data = yaml_load(jobs_filepath, data)
    assert 'jobs' in yaml_data, pprint.pformat(yaml_data)
    return jobs_filepath, yaml_data



# -----------------------------------------------------------------------------


def expand_input_expressions(yaml_item, context):
    """

    >>> expand_input_expressions('${{ hello }}', {'hello': 'world'})
    'world'
    >>> expand_input_expressions(exp.Value('hello'), {'hello': 'world'})
    'world'

    >>> expand_input_expressions('${{ hello }}-${{ world }}', {'hello': 'world'})
    'world-${{ world }}'

    >>> step = {
    ...     'if': "startswith(inputs.os, 'ubuntu')",
    ...     'name': '🚧 Build distribution 📦',
    ...     'uses': 'RalfG/python-wheels-manylinux-build@v0.3.3-manylinux2010_x86_64',
    ...     'str': '${{ inputs.empty }}',
    ...     'with': {
    ...         'build-requirements': 'cython',
    ...         'pre-build-command': 'bash ',
    ...         'python-versions': '${{ manylinux-versions[inputs.python-version] }}'
    ...     },
    ... }
    >>> inputs = {
    ...     'os': exp.Lookup('matrix', 'os'),
    ...     'python-version': exp.Lookup('matrix', 'python-version'),
    ...     'root_branch': 'refs/heads/master',
    ...     'root_user': 'SymbiFlow',
    ...     'empty': '',
    ... }
    >>> p(expand_input_expressions(step, {'inputs': inputs, 'manylinux-versions': {'blah'}}))
    {'if': "startswith(inputs.os, 'ubuntu')",
     'name': '🚧 Build distribution 📦',
     'str': '',
     'uses': 'RalfG/python-wheels-manylinux-build@v0.3.3-manylinux2010_x86_64',
     'with': {'build-requirements': 'cython',
              'pre-build-command': 'bash ',
              'python-versions': Lookup('manylinux-versions', Lookup('matrix', 'python-version'))}}

    >>> step = CommentedMap({'f': exp.Lookup('a', 'b')})
    >>> list(step.items())
    [('f', Lookup('a', 'b'))]
    >>> step = expand_input_expressions(step, {'a': {'b': 'c'}})
    >>> list(step.items())
    [('f', 'c')]

    >>> ref1 = CommentedMap({'a': 'b'})
    >>> ref2 = CommentedMap({'a': 'c', 'd': 'e'})
    >>> step = CommentedMap({'f': 'g'})
    >>> step.add_yaml_merge([(0, ref1)])
    >>> step.add_yaml_merge([(1, ref2)])
    >>> list(step.non_merged_items())
    [('f', 'g')]
    >>> list(step.items())
    [('f', 'g'), ('a', 'b'), ('d', 'e')]

    >>> ref1 = CommentedMapExpression(exp.Value('hello'))
    >>> step = CommentedMap({'f': 'g'})
    >>> step.add_yaml_merge([(0, ref1)])
    >>> list(step.items())
    [('f', 'g')]
    >>> step = expand_input_expressions(step, {'hello': yaml.comments.CommentedMap({'a': 'b'})})
    >>> list(step.items())
    [('f', 'g'), ('a', 'b')]

    >>> ref1 = CommentedMapExpression(exp.Lookup('a', 'b'))
    >>> step = CommentedMap({'f': 'g'})
    >>> step.add_yaml_merge([(0, ref1)])
    >>> list(step.items())
    [('f', 'g')]
    >>> step = expand_input_expressions(step, {'a': {'b': yaml.comments.CommentedMap({'c': 'd'})}})
    >>> list(step.items())
    [('f', 'g'), ('c', 'd')]

    """
    marker = []
    new_yaml_item = marker
    if isinstance(yaml_item, CommentedMapExpression):
        if yaml_item.exp_value is not None:
            assert isinstance(yaml_item.exp_value, exp.Expression), yaml_item.node

            new_value = expand_input_expressions(yaml_item.exp_value, context)
            if isinstance(new_value, exp.Expression):
                new_yaml_item = CommentedMapExpression()
                new_yaml_item.node = MapExpressionNode('tag:github.com,2020:expression', new_value)
                return new_yaml_item

            assert isinstance(new_value, dict), (new_value, yaml_item.exp_value, context)
            yaml_item = yaml.comments.CommentedMap(new_value)

    if isinstance(yaml_item, yaml.comments.CommentedMap):
        new_merge_attrib = []
        for name, mapping in getattr(yaml_item, yaml.comments.merge_attrib, []):
            new_mapping = expand_input_expressions(mapping, context)
            assert isinstance(new_mapping, yaml.comments.CommentedMap), (type(new_mapping), pprint.pformat(new_mapping))
            new_merge_attrib.append((name, new_mapping))

        new_yaml_item = yaml.comments.CommentedMap()
        yaml_item.copy_attributes(new_yaml_item)
        setattr(new_yaml_item, yaml.comments.merge_attrib, [])

        for k, v in yaml_item.non_merged_items():
            new_yaml_item[k] = expand_input_expressions(v, context)

        if new_merge_attrib:
            new_yaml_item.add_yaml_merge(new_merge_attrib)

    elif isinstance(yaml_item, dict):
        new_yaml_item = {}
        for k, v in list(yaml_item.items()):
            new_yaml_item[k] = expand_input_expressions(v, context)
    elif isinstance(yaml_item, list):
        new_yaml_item = []
        for i in range(0, len(yaml_item)):
            new_yaml_item.append(expand_input_expressions(yaml_item[i], context))
    elif isinstance(yaml_item, exp.Expression):
        new_yaml_item = exp.simplify(yaml_item, context)
    elif isinstance(yaml_item, str):
        if '${{' in yaml_item:
            new_yaml_item = exp.eval(yaml_item, context)
        else:
            new_yaml_item = yaml_item
    elif isinstance(yaml_item, (bool, int, float, None.__class__)):
        return yaml_item
    else:
        raise TypeError('{} ({!r})'.format(type(yaml_item), yaml_item))

    assert new_yaml_item is not marker

    return new_yaml_item


def get_needs(d):
    needs = d.get('needs', [])
    if isinstance(needs, str):
        needs = [needs]
    return needs


def get_if_exp(d):
    if 'if' not in d:
        return True

    v = d['if']
    if isinstance(v, CommentedMapExpression):
        v = v.exp_value
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


def resolve_paths(root_filepath, data):
    assert isinstance(root_filepath, files.FilePath), (type(root_filepath), root_filepath)
    assert isinstance(data, dict), (type(data), data)
    for k, v in data.items():
        if isinstance(v, dict):
            resolve_paths(root_filepath, v)
            continue

        assert isinstance(k, str), (type(k), k)
        if not k.startswith('includes'):
            continue

        assert isinstance(v, str), (type(v), v)
        data[k] = files.get_filepath(root_filepath, v, filetype='action')



def build_inputs(target_yamldata, include_yamldata, current_filepath):
    """

    >>> def w(**kw):
    ...     return {'with': kw}

    >>> target = {'inputs': {'arg1': {'default': 1}, 'arg2': {'required': True}}}
    >>> p(build_inputs(target, w(arg1=2, arg2=3), None))
    {'arg1': 2, 'arg2': 3}
    >>> p(build_inputs(target, w(arg2=3), None))
    {'arg1': 1, 'arg2': 3}

    >>> p(build_inputs(target, w(arg1=4), None))
    Traceback (most recent call last):
        ...
    KeyError: "with statement was missing required argument 'arg2'...

    >>> p(build_inputs(target, w(arg1=2, arg2=3, arg3=4), None))
    Traceback (most recent call last):
        ...
    KeyError: 'with statement had unused extra arguments: arg3: 4'

    >>> p(build_inputs(target, w(arg1=2, arg2=3, arg3=4, arg4='a'), None))
    Traceback (most recent call last):
        ...
    KeyError: "with statement had unused extra arguments: arg3: 4, arg4: 'a'"

    >>> target = {'inputs': {'args1': None}}
    >>> lp = LocalFilePath(repo_root='/path', path='.github/actions/blah')
    >>> rp = RemoteFilePath(user='user', repo='repo', ref='ref', path='.github/includes/workflows/blah')
    >>> p(build_inputs(target, w(args1={'includes': '/a'}), lp))
    {'args1': {'includes': LocalFilePath(repo_root=PosixPath('/path'), path=PosixPath('.github/includes/actions/a'))}}
    >>> p(build_inputs(target, w(args1={'includes': '/a'}), rp))
    {'args1': {'includes': RemoteFilePath(user='user', repo='repo', ref='ref', path='.github/includes/actions/a')}}

    """

    # Calculate the inputs dictionary
    with_data = copy.copy(include_yamldata.get('with', {}))

    # FIXME: This is a hack to make sure that paths used in include values are
    # relative to the file they are defined in, not the place they are used.
    if current_filepath is not None:
        resolve_paths(current_filepath, with_data)

    inputs = {}
    for in_name, in_info in target_yamldata.get('inputs', {}).items():
        if not in_info:
            in_info = {}

        marker = {}
        v = marker

        # Set the default value
        if 'default' in in_info:
            v = in_info['default']

        # Override with the provided value
        if in_name in with_data:
            v = with_data.pop(in_name)

        # Check the value is set if required.
        if in_info.get('required', False):
            if v is marker:
                raise KeyError(
                    "with statement was missing required argument {!r}, got with:\n{}".format(
                        in_name, pprint.pformat(include_yamldata.get('with', '*nothing*')),
                    ),
                )

        inputs[in_name] = v

    if with_data:
        raise KeyError(
            "with statement had unused extra arguments: {}".format(
                ", ".join('%s: %r' % (k,v) for k,v in with_data.items())
            )
        )
    return inputs


# -----------------------------------------------------------------------------


def add_github_context(context):
    github = {}
    for k in os.environ.keys():
        if not k.startswith('GITHUB_'):
            continue
        github[k[7:].lower()] = os.environ[k]

    if not github:
        # FIXME: pull the data from the local git repository.
        github['sha'] = git_root_output = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'])

    assert not 'github' in context, pprint.format(context)
    context['github'] = github


def step_type(m):
    if 'run' in m:
        return 'run'
    elif 'uses' in m:
        return 'uses'
    elif 'includes' in m:
        return 'includes'
    elif 'includes-script' in m:
        return 'includes-script'
    else:
        raise ValueError('Unknown step type:\n' + pprint.pformat(m) + '\n')


def expand_step_includes(current_filepath, include_step):
    assert step_type(include_step) == 'includes', (current_filepath, include_step)

    include_filepath, include_yamldata = get_action_data(current_filepath, include_step['includes'])
    assert 'runs' in include_yamldata, pprint.pformat(include_yamldata)
    assert 'steps' in include_yamldata['runs'], pprint.pformat(include_yamldata)

    try:
        input_data = build_inputs(include_yamldata, include_step, current_filepath)
    except KeyError as e:
        raise SyntaxError('{}: {} while processing {} included with\n{}'.format(
            current_filepath, e, include_filepath, pprint.pformat(include_step)))
    if 'inputs' in include_yamldata:
        del include_yamldata['inputs']

    context = dict(include_yamldata)
    context['inputs'] = input_data

    printdbg('\nInclude Step:')
    printdbg(include_step)
    printdbg('Inputs:')
    printdbg(input_data)
    printdbg('Before data:')
    printdbg(include_yamldata)

    # Do the input replacements in the yaml file.
    include_yamldata = expand_input_expressions(include_yamldata, context)

    printdbg('---')
    printdbg('After data:\n', pprint.pformat(include_yamldata))
    printdbg('\n', end='')

    assert 'runs' in include_yamldata, pprint.pformat(include_yamldata)
    assert 'steps' in include_yamldata['runs'], pprint.pformat(include_yamldata)

    current_if = get_if_exp(include_step)

    out = []
    for i, step in enumerate(include_yamldata['runs']['steps']):
        step_if = exp.AndF(current_if, get_if_exp(step))

        printdbg(f'Step {i} -', step.get('name', '????'))
        printdbg('           Before If:', repr(step_if))
        step_if = exp.simplify(step_if, context)
        printdbg('            After If:', repr(step_if))

        if isinstance(step_if, exp.Expression):
            step['if'] = step_if
        elif step_if in (False, None, ''):
            continue
        else:
            assert step_if is True, (step_if, repr(step_if))
            if 'if' in step:
                del step['if']

        out.append((include_filepath, step))

    return out


def expand_step_includes_script(current_filepath, v):
    assert step_type(v) == 'includes-script', (current_filepath, v)

    script = v.pop('includes-script')
    script_file = str((pathlib.Path('/'+current_filepath.path).parent / script).resolve())[1:]
    printerr(f"Including script: {script} (relative to {current_filepath}) found at {script_file}")

    script_filepath = get_filepath(current_filepath, './'+script_file)
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

    return expand_step_run(current_filepath, v)


def expand_step_uses(current_filepath, v):
    assert step_type(v) == 'uses', (current_filepath, v)
    # Support the `/{name}` format on `uses` values.
    if v['uses'].startswith('/'):
        v['uses'] = './.github/includes/actions' + v['uses']

    return v


def expand_step_run(current_filepath, v):
    assert step_type(v) == 'run', (current_filepath, v)
    return v


# -----------------------------------------------------------------------------


def expand_job_steps(current_filepath, job_data):
    assert 'steps' in job_data, pprint.pformat(job_data)

    steps = list((current_filepath, s) for s in job_data['steps'])

    new_steps = []
    while steps:
        step_filepath, step_data = steps.pop(0)

        st = step_type(step_data)
        if st != 'includes':
            new_steps.append({
                'run': expand_step_run,
                'uses': expand_step_uses,
                'includes-script': expand_step_includes_script,
            }[st](step_filepath, step_data))
        else:
            steps_to_add = expand_step_includes(step_filepath, step_data)
            while steps_to_add:
                new_step_filepath, new_step_data = steps_to_add.pop(-1)
                steps.insert(0, (new_step_filepath, new_step_data))

    job_data = copy.copy(job_data)
    job_data['steps'] = new_steps
    return job_data


def expand_job_include(current_filepath, include_job):
    assert 'includes' in include_job, pprint.pformat(include_job)

    include_filepath, include_yamldata = get_workflow_data(
        current_filepath, include_job['includes'])
    assert 'jobs' in include_yamldata, pprint.pformat(include_yamldata)

    try:
        input_data = build_inputs(include_yamldata, include_job, current_filepath)
    except KeyError as e:
        raise SyntaxError('{} while processing {} included with:\n{}'.format(
            e, include_filepath, pprint.pformat(include_job)))
    del include_yamldata['inputs']

    context = dict(include_yamldata)
    context['inputs'] = input_data

    printdbg('')
    printdbg('Include Job:')
    printdbg(include_job)
    printdbg('Inputs:')
    printdbg(input_data)
    printdbg('')
    printdbg('Before job data:')
    printdbg(include_yamldata)

    # Do the input replacements in the yaml file.
    printdbg('---')
    include_yamldata = expand_input_expressions(include_yamldata, context)
    printdbg('---')

    printdbg('After job data:')
    printdbg(include_yamldata)
    printdbg('')

    return include_filepath, include_yamldata, context


def expand_workflow_jobs(current_workflow, current_workflow_data):
    assert 'jobs' in current_workflow_data, pprint.pformat(current_workflow_data)

    jobs = list((current_workflow, k, v) for k, v in current_workflow_data['jobs'].items())

    new_jobs = []

    while jobs:
        current_filepath, job_name, job_data = jobs.pop(0)
        printdbg('\nJob:', f'{job_name}#{len(new_jobs)}')

        if job_name is None:
            job_name = ''

        if 'includes' not in job_data:
            # Once all the job includes have been expanded, we can expand the
            # steps.
            job_data = expand_job_steps(current_filepath, job_data)
            new_jobs.append((job_name, job_data))
            continue

        current_needs = get_needs(job_data)
        current_if = get_if_exp(job_data)

        include_filepath, included_data, context = expand_job_include(current_filepath, job_data)
        assert 'jobs' in included_data, pprint.pformat(included_data)

        included_jobs = list(included_data['jobs'].items())
        while included_jobs:
            included_job_name, included_job_data = included_jobs.pop(-1)
            new_job_name = job_name+included_job_name

            new_needs = current_needs + [job_name+n for n in get_needs(included_job_data)]
            if new_needs:
                if len(new_needs) == 1:
                    new_needs = new_needs.pop(0)
                included_job_data['needs'] = new_needs

            new_if = exp.AndF(current_if, get_if_exp(included_job_data))

            printdbg(new_job_name)
            printdbg('Before Job If:', repr(new_if))
            new_if = exp.simplify(new_if, context)
            printdbg(' After Job If:', repr(new_if))

            if isinstance(new_if, exp.Expression):
                included_job_data['if'] = current_if
            elif new_if in (False, None, ''):
                continue
            else:
                assert new_if is True, (new_if, repr(new_if))
                if 'if' in included_job_data:
                    del included_job_data['if']

            jobs.insert(0, (include_filepath, new_job_name, included_job_data))

    new_workflow = copy.copy(current_workflow_data)

    job_names = []
    # Set all the new jobs
    for job_name, job_data in new_jobs:
        new_workflow['jobs'][job_name] = job_data
        job_names.append(job_name)
    # Remove any jobs of the older jobs which still exist.
    for job_name in list(new_workflow['jobs'].keys()):
        if job_name not in job_names:
            del new_workflow['jobs'][job_name]
    return new_workflow


# ==============================================================
# PyYaml Loader / Dumper Customization
# ==============================================================


resolver.BaseResolver.add_implicit_resolver(
    u'tag:github.com,2020:expression',
    util.RegExp(u'^(?:\\${{[^}]*}})$'),
    [u'$'], # - a list of first characters to match
)


def construct_expression(self, node):
    if isinstance(node, MapExpressionNode):
        return CommentedMapExpression(node.value)

    assert isinstance(node, yaml.nodes.ScalarNode), (type(node), node)

    v = node.value
    if isinstance(v, str):
        v = exp.parse(v)

    assert isinstance(v, exp.Expression), (type(v), v)

    return v


RoundTripConstructor.add_constructor(u'tag:github.com,2020:expression', construct_expression)


# ==============================================================


class CommentedMapExpression(yaml.comments.CommentedMap):
    def __init__(self, a0, *args, **kw):
        yaml.comments.CommentedMap.__init__(self, [], *args, **kw)

        if isinstance(a0, str):
            a0 = exp.parse(a0)

        self.exp_value = a0

    def __repr__(self):
        return 'CommentedMap({!r})'.format(self.exp_value)


class MapExpressionNode(yaml.nodes.MappingNode):
    def __init__(self, tag, value, *args, **kw):
        yaml.nodes.MappingNode.__init__(self, tag, value, *args, **kw)

    def __repr__(self):
        return 'MapNode({!r})'.format(self.value)


class RoundTripConstructorWithExp(RoundTripConstructor):
    def construct_mapping(self, node, maptyp, deep=False):  # type: ignore
        for i, (key_node, value_node) in enumerate(node.value):
            # Upgrade a ScalarNode into a MappingNode so it can be added as a merge reference
            if key_node.tag == u'tag:yaml.org,2002:merge' and value_node.tag == 'tag:github.com,2020:expression':
                assert isinstance(value_node, yaml.nodes.ScalarNode), value_node
                new_node = MapExpressionNode('tag:github.com,2020:expression', value_node.value)
                node.value[i] = (key_node, new_node)

        return RoundTripConstructor.construct_mapping(self, node, maptyp, deep)


class RoundTripLoaderWithExp(
    yaml.reader.Reader,
    yaml.scanner.RoundTripScanner,
    yaml.parser.RoundTripParser,
    yaml.composer.Composer,
    RoundTripConstructorWithExp,
    yaml.resolver.VersionedResolver,
):
    def __init__(self, stream, version=None, preserve_quotes=None):
        # type: (StreamTextType, Optional[VersionType], Optional[bool]) -> None
        # self.reader = Reader.__init__(self, stream)
        yaml.reader.Reader.__init__(self, stream, loader=self)
        yaml.scanner.RoundTripScanner.__init__(self, loader=self)
        yaml.parser.RoundTripParser.__init__(self, loader=self)
        yaml.composer.Composer.__init__(self, loader=self)
        RoundTripConstructorWithExp.__init__(self, preserve_quotes=preserve_quotes, loader=self)
        yaml.resolver.VersionedResolver.__init__(self, version, loader=self)


# ==============================================================


def exp_presenter(dumper, data):
    return dumper.represent_scalar('tag:github.com,2020:expression', '${{ '+str(data)+' }}')


yaml.representer.RoundTripRepresenter.add_multi_representer(exp.Expression, exp_presenter)


def map_exp_presenter(dumper, data):
    print("-->", data.node)
    return data.node


yaml.representer.RoundTripRepresenter.add_representer(MapExpressionNode, map_exp_presenter)


# ==============================================================


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


yaml.representer.RoundTripRepresenter.add_representer(str, str_presenter)
yaml.representer.RoundTripRepresenter.add_representer(None.__class__, none_presenter)
yaml.representer.RoundTripRepresenter.add_representer(On, On.presenter)


def yaml_load(current_action, yaml_data):
    """

    >>> d = yaml_load(None, '''
    ... jobs:
    ...   First:
    ...     if: ${{ hello }}
    ... ''')
    >>> p(d)
    {'jobs': {'First': {'if': Value(hello)}}}
    >>> yaml_dump(None, d)
    'jobs:\\n  First:\\n    if: ${{ hello }}\\n'
    """

    md5sum = hashlib.md5(yaml_data.encode('utf-8')).hexdigest()
    printerr(f'Loading yaml file {current_action} with contents md5 of {md5sum}')
    printdbg(yaml_data)
    return yaml.load(yaml_data, Loader=RoundTripLoaderWithExp)


class RoundTripDumperWithoutAliases(yaml.RoundTripDumper):
    def ignore_aliases(self, data):
        return True


def yaml_dump(current_action, data):
    return yaml.dump(data, allow_unicode=True, width=1000, Dumper=RoundTripDumperWithoutAliases)


# Enable pretty printing for the ruamel.yaml.comments objects
# --------------------------------------------------------------


def commentedmapexp_pprint(p, object, stream, indent, allowance, context, level):
    assert isinstance(object, CommentedMapExpression), object
    p._format(object.exp_value, stream, indent, allowance, context, level)


def commentedmap_pprint(p, object, stream, indent, allowance, context, level):
    _sort_dicts = p._sort_dicts
    p._sort_dicts = False

    m = getattr(object, yaml.comments.merge_attrib, [])
    if m:
        write = stream.write
        write('<')
        if p._indent_per_level > 1:
            write((p._indent_per_level - 1) * ' ')
        l = [(None, dict(object.non_merged_items()))]+m
        while l:
            _, o = l.pop(0)
            p._format(o, stream, indent, allowance, context, level)
            if l:
                write('+')
        write('>')
    else:
        p._pprint_dict(object, stream, indent, allowance, context, level)

    p._sort_dicts = _sort_dicts


def commentedseq_pprint(p, object, stream, indent, allowance, context, level):
    assert isinstance(object, yaml.comments.CommentedSeq), (type(object), object)
    p._pprint_list(list(object), stream, indent, allowance, context, level)


def commentedset_pprint(p, object, stream, indent, allowance, context, level):
    assert isinstance(object, yaml.comments.CommentedSet), (type(object), object)
    p._pprint_set(set(object), stream, indent, allowance, context, level)


def commentedmap_repr(self):
    if self.merge:
        l = [(None, dict(self.non_merged_items()))]+self.merge
        return '<{}>'.format('+'.join(repr(d) for _, d in l))
    else:
        return repr(dict(self))

yaml.comments.CommentedMap.__repr__ = commentedmap_repr


pprint.PrettyPrinter._dispatch[CommentedMapExpression.__repr__] = commentedmapexp_pprint
pprint.PrettyPrinter._dispatch[yaml.comments.CommentedMap.__repr__] = commentedmap_pprint
pprint.PrettyPrinter._dispatch[yaml.comments.CommentedKeyMap.__repr__] = commentedmap_pprint
pprint.PrettyPrinter._dispatch[yaml.comments.CommentedSeq.__repr__] = commentedseq_pprint
pprint.PrettyPrinter._dispatch[yaml.comments.CommentedSet.__repr__] = commentedset_pprint

# --------------------------------------------------------------


# ==============================================================


def expand_workflow(current_workflow, to_path, insert_check_steps: bool):
    src_path = os.path.relpath('/'+str(current_workflow.path), start='/'+str(os.path.dirname(to_path)))

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

    data = yaml_load(current_workflow, '\n'.join(workflow_data))
    data = expand_workflow_jobs(current_workflow, data)
    new_data = {}
    if True in data:
        new_data[On()] = data.pop(True)
    for k, v in data.items():
        new_data[k] = v
    data = new_data

    to_insert = []

    is_actions_include = os.environ.get('GITHUB_REPOSITORY', '').endswith('/actions-includes')
    if is_actions_include:
        # Checkout the repo
        to_insert.append({
            'name': '⏰ 📝 - Get source code',
            'uses': 'actions/checkout@v2',
        })
        # Setup python
        to_insert.append({
            'name': '⏰ 📝 - Setting up Python for local docker build',
            'uses': 'actions/setup-python@v2',
            'with': {'python-version': 3.9},
        })
        # Prepare for building the docker image locally
        to_insert.append({
            'name': '⏰ 📝 - Setting up remaining bit for local docker build',
            'uses': './.github/includes/actions/prepare-for-docker-build',
        })
        # Use the local docker image
        include_action = './.github/includes/actions/local'
        include_name = '⏰ 🛂 📖 - Checking workflow expansion is up to date (local)'
    else:
        # Use the action at mithro/actions-includes
        include_action = INCLUDE_ACTION_NAME
        include_name = '⏰ 🛂 📕 - Checking workflow expansion is up to date'

    to_insert.append({
        'name': include_name,
        'uses': include_action,
        # FIXME: This check should run on all platforms.
        'if': "runner.os == 'Linux'",
        'continue-on-error': False,
        'with': {
            'workflow': str(to_path),
        },
    })

    for j in data['jobs'].values():
        assert 'steps' in j, pprint.pformat(j)
        steps = j['steps']
        assert isinstance(steps, list), pprint.pformat(j)

        for s in reversed(to_insert):
            if insert_check_steps:
                steps.insert(0, s)

    printdbg('')
    printdbg('Final yaml data:')
    printdbg('-'*75)
    printdbg(data)
    printdbg('-'*75)

    output.append(yaml_dump(current_workflow, data))

    return '\n'.join(output)


def main():
    ap = argparse.ArgumentParser(
        prog="actions-includes",
        description="Allows including an action inside another action")
    ap.add_argument("in_workflow", metavar="input-workflow", type=str,
        help="Path to input workflow relative to repo root")
    ap.add_argument("out_workflow", metavar="output-workflow", type=str,
        help="Path where flattened workflow will be written, relative to repo root")
    ap.add_argument("--no-check", action="store_true",
        help="Don't insert extra step in jobs to check that the workflow is up to date")
    args = ap.parse_args()

    tfile = None
    try:
        git_root_output = subprocess.check_output(
            ['git', 'rev-parse', '--show-toplevel'])

        repo_root = pathlib.Path(git_root_output.decode(
            'utf-8').strip()).resolve()

        from_filename = args.in_workflow
        to_filename = args.out_workflow
        insert_check = not args.no_check

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
        out_data = expand_workflow(current_action, to_path, insert_check)

        with open(to_abspath, 'w') as f:
            f.write(out_data)

        return 0
    finally:
        if tfile is not None and os.path.exists(tfile):
            with open(tfile) as f:
                print(f.read())

            os.unlink(tfile)
            tfile = None
