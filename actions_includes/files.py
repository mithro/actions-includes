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


import os.path
import pathlib
import urllib
import urllib.request

from collections import namedtuple

from .output import printerr, printdbg


"""
Functions for dealing with files that could either be local on disk or on in a
remote GitHub repository.
"""

class FilePath:
    pass


_LocalFilePath = namedtuple('LocalFilePath', 'repo_root path')
class LocalFilePath(_LocalFilePath, FilePath):
    def __new__(cls, repo_root, path):
        if isinstance(repo_root, str):
            repo_root = pathlib.Path(repo_root)
        if isinstance(path, str):
            path = pathlib.Path(path)
        return super().__new__(cls, repo_root, path)

    def __str__(self):
        return os.path.join(self.repo_root, self.path)


_RemoteFilePath = namedtuple('RemoteFilePath', 'user repo ref path')
class RemoteFilePath(_RemoteFilePath, FilePath):
    def __str__(self):
        return '{user}/{repo}/{path}@{ref}'.format(
            user=self.user, repo=self.repo, path=self.path, ref=self.ref)


def parse_remote_path(action_name):
    """Convert action name into a FilePath object."""
    assert not action_name.startswith('docker://'), action_name
    if '@' not in action_name:
        action_name = action_name + '@main'

    repo_plus_path, ref = action_name.split('@', 1)
    assert '@' not in ref, action_name
    if repo_plus_path.count('/') == 1:
        repo_plus_path += '/'

    user, repo, path = repo_plus_path.split('/', 2)
    return RemoteFilePath(user, repo, ref, path)


def get_filepath(current, filepath, filetype=None):
    """
    >>> localfile_current = LocalFilePath(pathlib.Path('/path'), 'abc.yaml')
    >>> remotefile_current = RemoteFilePath('user', 'repo', 'ref', 'abc.yaml')

    Local path on local current becomes a local path.
    >>> fp = get_filepath(localfile_current, './.github/actions/blah')
    >>> fp
    LocalFilePath(repo_root=PosixPath('/path'), path=PosixPath('.github/actions/blah'))
    >>> str(fp)
    '/path/.github/actions/blah'

    >>> fp = get_filepath(localfile_current, '/blah', 'action')
    >>> fp
    LocalFilePath(repo_root=PosixPath('/path'), path=PosixPath('.github/includes/actions/blah'))
    >>> str(fp)
    '/path/.github/includes/actions/blah'

    >>> fp = get_filepath(localfile_current, '/blah', 'workflow')
    >>> fp
    LocalFilePath(repo_root=PosixPath('/path'), path=PosixPath('.github/includes/workflows/blah'))
    >>> str(fp)
    '/path/.github/includes/workflows/blah'

    Local path on current remote gets converted to a remote path.
    >>> fp = get_filepath(remotefile_current, './.github/actions/blah')
    >>> fp
    RemoteFilePath(user='user', repo='repo', ref='ref', path='.github/actions/blah')
    >>> str(fp)
    'user/repo/.github/actions/blah@ref'

    >>> fp = get_filepath(remotefile_current, '/blah', 'workflow')
    >>> fp
    RemoteFilePath(user='user', repo='repo', ref='ref', path='.github/includes/workflows/blah')
    >>> str(fp)
    'user/repo/.github/includes/workflows/blah@ref'

    """

    # Resolve '/$XXX' to './.github/actions/$XXX'
    assert isinstance(filepath, str), (type(filepath), filepath)
    if filepath.startswith('/'):
        assert filetype is not None, (current, filepath, filetype)
        filepath = '/'.join(
            ['.', '.github', 'includes', filetype+'s', filepath[1:]])

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
