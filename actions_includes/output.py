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
import os
import sys


def printerr(*args, **kw):
    print(*args, file=sys.stderr, **kw)


DEBUG = bool(os.environ.get('DEBUG', False))


def printdbg(*args, **kw):
    if DEBUG:
        args = list(args)
        for i in range(0, len(args)):
            if not isinstance(args[i], str):
                args[i] = pprint.pformat(args[i])
        print(*args, file=sys.stderr, **kw)
