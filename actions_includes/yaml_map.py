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


import pprint

from collections import defaultdict



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
    actions_includes.yaml_map.YamlMap.MultiKeyError: 'Multi key: 1 == [1, 2]'
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
    if isinstance(node, MappingNode):
        self.flatten_mapping(node)
    data = YamlMap()
    yield data
    for key_node, value_node in node.value:
        key = self.construct_object(key_node, deep=True)
        val = self.construct_object(value_node, deep=True)
        data[key] = val
