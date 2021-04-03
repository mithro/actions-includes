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


import collections.abc
import json
import re

from pprint import pprint as p


class ExpressionShortName(type):
    def __repr__(self):
        return "<class 'exp.{}'>".format(self.__name__)


class Expression(metaclass=ExpressionShortName):
    pass


def to_literal(v):
    """
    >>> to_literal(None)
    'null'
    >>> to_literal(True)
    'true'
    >>> to_literal(False)
    'false'
    >>> to_literal(711)
    '711'
    >>> to_literal(-710)
    '-710'
    >>> to_literal(2.0)
    '2.0'
    >>> to_literal(-2.0)
    '-2.0'
    >>> to_literal('Mona the Octocat')
    "'Mona the Octocat'"
    >>> to_literal("It's open source")
    "'It''s open source'"
    >>> to_literal(Value("hello"))
    'hello'
    >>> to_literal(Lookup("hello", "testing"))
    'hello.testing'
    >>> to_literal(ContainsF(Lookup("hello"), "testing"))
    "contains(hello, 'testing')"
    """
    if isinstance(v, Expression):
        return str(v)
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
    raise ValueError('Unknown literal? {!r}'.format(v))


INT = re.compile('^-?[0-9]+$')
FLOAT = re.compile('^-?[0-9]+\\.[0-9]+$')
HEX = re.compile('^0x[0-9a-fA-F]+$')
EXP = re.compile('^(-?[0-9]+\\.\\[0-9]+)-?[eE]([0-9.]+)$')
VALUE = re.compile('^[a-zA-Z][_a-zA-Z0-9\\-]*$')
LOOKUP = re.compile('(?:\\.[a-zA-Z][_a-zA-Z0-9\\-]*)|(?:\\[[^\\]]+\\])')

S = "('[^']*')+"
I = "[a-zA-Z.\\-0-9_\\[\\]]+"

BITS = re.compile('((?P<S>{})|(?P<I>{}))'.format(S, I))


def swizzle(l):
    """

    >>> p(INFIX_FUNCTIONS)
    {'!=': <class 'exp.NotEqF'>,
     '&&': <class 'exp.AndF'>,
     '==': <class 'exp.EqF'>,
     '||': <class 'exp.OrF'>}

    >>> swizzle([1, '&&', 2])
    (<class 'exp.AndF'>, 1, 2)
    >>> swizzle([1, '&&', 2, '&&', 3])
    (<class 'exp.AndF'>, 1, (<class 'exp.AndF'>, 2, 3))
    >>> swizzle(['!', 1, '&&', 2, '&&', 3])
    (<class 'exp.AndF'>, (<class 'exp.NotF'>, 1), (<class 'exp.AndF'>, 2, 3))
    >>> swizzle(['!', [1, '&&', 2, '&&', 3]])
    (<class 'exp.NotF'>, (<class 'exp.AndF'>, 1, (<class 'exp.AndF'>, 2, 3)))

    >>> swizzle([(SuccessF,)])
    (<class 'exp.SuccessF'>,)

    """
    if isinstance(l, (list, tuple)):
        if len(l) > 1:
            if l[0] in ('!',):
                l = [(NotF, swizzle(l[1]))]+l[2:]
                l = swizzle(l)
        if len(l) > 2:
            a = swizzle(l[0])
            b = l[1]
            c = swizzle(l[2:])

            assert isinstance(b, collections.abc.Hashable), \
                "Unhashable object: {} (type: {}) from {!r}".format(b, type(b), l)

            if b in INFIX_FUNCTIONS:
                return (INFIX_FUNCTIONS[b], a, c)
        if isinstance(l, list) and len(l) == 1:
            return swizzle(l[0])
    return l


def tokenizer(s):
    """
    >>> s = re.compile(S)
    >>> [m.group(0) for m in s.finditer("'hello'")]
    ["'hello'"]
    >>> [m.group(0) for m in s.finditer("'hello''world'")]
    ["'hello''world'"]
    >>> i = re.compile(I)
    >>> [m.group(0) for m in i.finditer("null true false 711 2.0 hello.testing -9.2 -2.99-e2")]
    ['null', 'true', 'false', '711', '2.0', 'hello.testing', '-9.2', '-2.99-e2']
    >>> list(tokenizer("true || inputs.value"))
    [<class 'exp.OrF'>, True, Lookup('inputs', 'value')]

    >>> p(tokenizer("secrets.GITHUB_TOKEN"))
    Lookup('secrets', 'GITHUB_TOKEN')
    >>> p(tokenizer("inputs.use-me"))
    Lookup('inputs', 'use-me')

    >>> p(tokenizer("!startsWith(runner.os, 'Linux')"))
    (<class 'exp.NotF'>,
     (<class 'exp.StartsWithF'>, Lookup('runner', 'os'), 'Linux'))

    >>> p(tokenizer("!startsWith(matrix.os, 'ubuntu') && (true && null && startsWith('ubuntu-latest', 'ubuntu'))"))
    (<class 'exp.AndF'>,
     (<class 'exp.NotF'>,
      (<class 'exp.StartsWithF'>, Lookup('matrix', 'os'), 'ubuntu')),
     (<class 'exp.AndF'>,
      True,
      (<class 'exp.AndF'>,
       None,
       (<class 'exp.StartsWithF'>, 'ubuntu-latest', 'ubuntu'))))
    >>> p(tokenizer("!startsWith(matrix.os, 'ubuntu') && (true && startsWith('ubuntu-latest', 'ubuntu'))"))
    (<class 'exp.AndF'>,
     (<class 'exp.NotF'>,
      (<class 'exp.StartsWithF'>, Lookup('matrix', 'os'), 'ubuntu')),
     (<class 'exp.AndF'>,
      True,
      (<class 'exp.StartsWithF'>, 'ubuntu-latest', 'ubuntu')))

    >>> p(tokenizer("a != b"))
    (<class 'exp.NotEqF'>, Value(a), Value(b))

    >>> p(tokenizer("manylinux-versions[inputs.python-version]"))
    Lookup('manylinux-versions', Lookup('inputs', 'python-version'))

    >>> p(tokenizer('success()'))
    (<class 'exp.SuccessF'>,)

    >>> p(tokenizer('hashFiles()'))
    (<class 'exp.HashFilesF'>,)
    >>> p(tokenizer("hashFiles('**/package-lock.json')"))
    (<class 'exp.HashFilesF'>, '**/package-lock.json')
    >>> p(tokenizer("hashFiles('**/package-lock.json', '**/Gemfile.lock')"))
    (<class 'exp.HashFilesF'>, '**/package-lock.json', '**/Gemfile.lock')
    """
    try:
        tree = []
        def split(s):
            i = 0
            while True:
                try:
                    m = BITS.search(s, i)
                except TypeError as e:
                    print(BITS, repr(s), i)
                    raise

                if not m:
                    b = s[i:].strip()
                else:
                    b = s[i:m.start(0)].strip()
                if b:
                    for i in b:
                        if not i.strip():
                            continue
                        yield i

                if not m:
                    return
                yield from_literal(m.group(0))
                i = m.end(0)

        stack = [[]]
        for i in split(s):
            if i == '(':
                stack.append([])
                continue
            elif i == ')':
                i = swizzle(stack.pop(-1))
            if stack[-1]:
                l = stack[-1][-1]
                if str(l)+str(i) in INFIX_FUNCTIONS:
                    stack[-1][-1] += i
                    continue
                elif isinstance(l, type) and issubclass(l, BinFunction):
                    assert len(i) == 3, (l, i)
                    assert i[1] == ',', (l, i)
                    #r = l(i[0], i[2])
                    #print('Eval: {}({}, {}) = {}'.format(l, i[0], i[2], r))
                    stack[-1][-1] = (l, i[0], i[2])
                    continue
                elif isinstance(l, type) and issubclass(l, VarArgsFunction):
                    o = [l]
                    if isinstance(i, (list, tuple)):
                        for j, a in enumerate(i):
                            if j % 2 == 1:
                                assert a == ',', (j, a, i)
                            else:
                                o.append(a)
                    else:
                        o.append(i)
                    stack[-1][-1] = tuple(o)
                    continue
                elif isinstance(l, type) and issubclass(l, EmptyFunction):
                    assert len(i) == 0, (l, i)
                    stack[-1][-1] = (l,)
                    continue
            stack[-1].append(i)

        assert len(stack) == 1, stack
        return swizzle(stack[0])
    except Exception as e:
        raise TypeError('Error while parsing: {!r}'.format(s)) from e



def var_eval(v, context):
    assert isinstance(v, Var), (v, context)
    assert isinstance(context, dict), (v, context)
    if isinstance(v, Value):
        if v in context:
            return context[v]
        else:
            return v
    assert isinstance(v, Lookup), (v, context)

    ov = list(v)
    for i, j in enumerate(ov):
        if isinstance(j, Var):
            ov[i] = var_eval(j, context)

    ctx = context
    cv = list(ov)
    while len(cv) > 0:
        j = cv.pop(0)
        if j not in ctx:
            cv.insert(0, j)
            break
        ctx = ctx[j]

    if not cv:
        return ctx
    else:
        return Lookup(ov)



def tokens_eval(t, context={}):
    """
    >>> tokens_eval(True)
    True
    >>> tokens_eval(False)
    False
    >>> tokens_eval((NotF, True))
    False
    >>> tokens_eval((NotF, False))
    True
    >>> tokens_eval((NotF, Value('a')))
    not(Value(a))

    >>> tokens_eval((StartsWithF, 'ubuntu-latest', 'ubuntu'))
    True
    >>> tokens_eval((StartsWithF, 'Windows', 'ubuntu'))
    False

    >>> tokens_eval((AndF, Value('a'), False))
    False

    >>> tokens_eval((AndF, False, Value('a')))
    False

    >>> tokens_eval((AndF, Value('a'), True))
    Value(a)

    >>> tokens_eval((AndF, True, Value('a')))
    Value(a)

    >>> tokens_eval((OrF, Value('a'), False))
    Value(a)

    >>> tokens_eval((OrF, False, Value('a')))
    Value(a)

    >>> tokens_eval((OrF, Value('a'), True))
    True

    >>> tokens_eval((OrF, True, Value('a')))
    True

    >>> tokens_eval((SuccessF,))
    success()

    >>> tokens_eval((OrF, (SuccessF,), Value('a')))
    or(success(), Value(a))

    >>> tokens_eval(Value("inputs"))
    Value(inputs)
    >>> tokens_eval(Value("inputs"), {'inputs': 'testing'})
    'testing'
    >>> l = Lookup("inputs", "value")
    >>> tokens_eval(l)
    Lookup('inputs', 'value')
    >>> tokens_eval(l, {'inputs': {'value': 'testing'}})
    'testing'
    >>> tokens_eval(l, {'inputs': {'value': Value('testing')}})
    Value(testing)

    >>> l1 = Lookup(Value("a"), "b")
    >>> l2 = Lookup("c", Value("a"))
    >>> c = {'c': {'b': Value('z'), 'c': Value('y')}, 'd':{'b': Value('x')}}
    >>> tokens_eval(l1, c)
    Lookup(Value(a), 'b')
    >>> c['a'] = 'c' ; tokens_eval(l1, c), tokens_eval(l2, c)
    (Value(z), Value(y))
    >>> c['a'] = 'd' ; tokens_eval(l1, c), tokens_eval(l2, c)
    (Value(x), Lookup('c', 'd'))

    >>> tokens_eval(Lookup('a', Value('b'), 'c'), {'b': Lookup('x', 'y')})
    Lookup('a', Lookup('x', 'y'), 'c')

    """
    assert not isinstance(t, list), t

    if isinstance(t, Var) and context:
        t = var_eval(t, context)

    if isinstance(t, tuple) and not isinstance(t, Lookup):
        assert isinstance(type(t[0]), type), t
        assert issubclass(t[0], Function), t
        t = list(t)
        f = t.pop(0)
        args = []
        while len(t) > 0:
            args.append(tokens_eval(t.pop(0), context))
        return f(*args)

    return t



class Function(Expression):
    def __copy__(self):
        return type(self)(self.args)

    def __deepcopy__(self, memo=None):
        return type(self)(*self.args)


class VarArgsFunction(Function):
    def __new__(cls, *args):
        o = Function.__new__(cls)
        o.args = args
        return o

    def __repr__(self):
        return '{}({})'.format(self.name, ', '.join(repr(a) for a in self.args))

    def __str__(self):
        return '{}({})'.format(self.name, ', '.join(to_literal(a) for a in self.args))


class BinFunction(Function):
    @property
    def args(self):
        return [self.a, self.b]

    @args.setter
    def args(self, v):
        v = list(v)
        assert len(v) == 2, v
        self.a = v.pop(0)
        self.b = v.pop(0)
        assert not v, v

    def __new__(cls, a, b):
        if isinstance(a, (Value, Lookup)) or isinstance(b, (Value, Lookup)):
            o = Function.__new__(cls)
            o.a = a
            o.b = b
            return o
        a = str(a)
        b = str(b)
        return cls.realf(a, b)

    def __repr__(self):
        return '{}({!r}, {!r})'.format(self.name, self.a, self.b)

    def __str__(self):
        a = to_literal(self.a)
        b = to_literal(self.b)
        return '{}({}, {})'.format(self.name, a, b)


class UnaryFunction(Function):
    @property
    def args(self):
        return [self.a]

    @args.setter
    def args(self, v):
        v = list(v)
        assert len(v) == 1, v
        self.a = v.pop(0)
        assert not v, v

    def __new__(cls, a):
        if isinstance(a, Expression):
            o = Function.__new__(cls)
            o.a = a
            return o
        return cls.realf(a)

    def __repr__(self):
        return '{}({!r})'.format(self.name, self.a)

    def __str__(self):
        a = to_literal(self.a)
        return '{}({})'.format(self.name, a)


# Operators
# https://docs.github.com/en/actions/reference/context-and-expression-syntax-for-github-actions#operators


class NotF(UnaryFunction):
    """
    >>> a1 = NotF(Value('a'))
    >>> a1
    not(Value(a))
    >>> str(a1)
    '!a'
    >>> a2 = NotF(NotF(Value('a')))
    >>> a2
    not(not(Value(a)))
    >>> str(a2)
    '!!a'

    >>> a3 = NotF(OrF(Value('a'), Value('b')))
    >>> a3
    not(or(Value(a), Value(b)))
    >>> str(a3)
    '!(a || b)'

    >>> a4 = NotF(StartsWithF(Value('a'), Value('b')))
    >>> a4
    not(startsWith(Value(a), Value(b)))
    >>> str(a4)
    '!startsWith(a, b)'

    >>> a5 = NotF(EqF(Value('a'), None))
    >>> a5
    not(eq(Value(a), None))
    >>> str(a5)
    '!(a == null)'

    >>> NotF(True)
    False

    >>> NotF(False)
    True

    >>> NotF(None)
    True

    >>> NotF('')
    True

    """
    name = 'not'

    @classmethod
    def realf(cls, v):
        return not bool(v)

    def __str__(self):
        if isinstance(self.args[0], InfixFunction):
            return '!({})'.format(str(self.args[0]))
        return '!'+str(self.args[0])


INFIX_FUNCTIONS = {}


class InfixFunctionMeta(ExpressionShortName):
    def __init__(self, *args, **kw):
        if self.op != None:
            INFIX_FUNCTIONS[self.op] = self
        type.__init__(self, *args, **kw)


class InfixFunction(Function, metaclass=InfixFunctionMeta):
    name = None
    op = None

    def __repr__(self):
        return '{}({})'.format(self.name, ', '.join(repr(i) for i in self.args))

    def __str__(self):
        return ' {} '.format(self.op).join(to_literal(i) for i in self.args)


class BinInfixFunction(InfixFunction, BinFunction):
    def __new__(cls, *args):

        assert len(args) == 2, (cls, args)
        a, b = args
        if not isinstance(a, Expression) and not isinstance(b, Expression):
            return cls.realf(a, b)
        if isinstance(a, (Value, Lookup)) and isinstance(b, (Value, Lookup)):
            v = cls.expf(a, b)
            if v in (False, True):
                return v

        o = Function.__new__(cls)
        o.args = (a, b)
        return o

    @staticmethod
    def realf(a, b):
        raise NotImplemented

    @staticmethod
    def expf(a, b):
        raise NotImplemented


class EqF(BinInfixFunction):
    """
    >>> a1 = EqF(Value('a'), Value('b'))
    >>> a1
    eq(Value(a), Value(b))
    >>> str(a1)
    'a == b'

    >>> EqF(True, Value('b'))
    eq(True, Value(b))
    >>> EqF(Value('a'), True)
    eq(Value(a), True)

    >>> a2 = EqF(Value('a'), True)
    >>> a2
    eq(Value(a), True)
    >>> str(a2)
    'a == true'

    >>> a3 = EqF(None, Value('b'))
    >>> a3
    eq(None, Value(b))
    >>> str(a3)
    'null == b'

    >>> a4 = EqF("Hello", Lookup('a', 'b'))
    >>> a4
    eq('Hello', Lookup('a', 'b'))
    >>> str(a4)
    "'Hello' == a.b"

    >>> a5 = EqF("'ello", Lookup('a', 'b'))
    >>> a5
    eq("'ello", Lookup('a', 'b'))
    >>> str(a5)
    "'''ello' == a.b"

    >>> EqF(1, 1)
    True

    >>> EqF(1, 10)
    False

    >>> EqF(Value('a'), Value('a'))
    True

    """
    name = 'eq'
    op = '=='

    @staticmethod
    def realf(a, b):
        return a == b

    @staticmethod
    def expf(a, b):
        if a == b:
            return True


class NotEqF(BinInfixFunction):
    """
    >>> a1 = NotEqF(Value('a'), Value('b'))
    >>> a1
    neq(Value(a), Value(b))
    >>> str(a1)
    'a != b'

    >>> NotEqF(True, Value('b'))
    neq(True, Value(b))
    >>> NotEqF(Value('a'), True)
    neq(Value(a), True)

    >>> NotEqF(1, 1)
    False

    >>> NotEqF(1, 10)
    True

    >>> NotEqF(Value('a'), Value('a'))
    False

    """
    name = 'neq'
    op = '!='

    @staticmethod
    def realf(a, b):
        return a != b

    @staticmethod
    def expf(a, b):
        if a == b:
            return False



class OrF(InfixFunction):
    """
    >>> a1 = OrF(Value('a'), Value('b'))
    >>> a1
    or(Value(a), Value(b))
    >>> str(a1)
    'a || b'

    >>> OrF(True, Value('a'))
    True
    >>> OrF(Value('a'), True)
    True

    >>> OrF(False, Value('a'))
    Value(a)

    >>> OrF(Value('a'), False)
    Value(a)

    >>> OrF(Value('a'), Value('a'))
    Value(a)
    """
    name = 'or'
    op = '||'

    def __new__(cls, *args):

        nargs = []
        for a in args:
            if a is True:
                return True
            elif a in (False, None, ''):
                continue
            elif a in nargs:
                continue
            else:
                nargs.append(a)

        if not nargs:
            return False

        if len(nargs) == 1:
            return nargs.pop(0)

        o = Function.__new__(cls)
        o.args = nargs
        return o


class AndF(InfixFunction):
    """

    # Simplifying booleans
    >>> AndF(True, True)
    True
    >>> AndF(True, False)
    False
    >>> AndF(False, True)
    False
    >>> AndF(False, False)
    False

    # Keeping normal groups
    >>> a1 = AndF(Value('a'), Value('b'))
    >>> a1
    and(Value(a), Value(b))
    >>> str(a1)
    'a && b'

    >>> AndF(True, Value('a'))
    Value(a)
    >>> AndF(Value('a'), True)
    Value(a)

    >>> AndF(False, Value('a'))
    False
    >>> AndF(Value('a'), False)
    False

    >>> AndF(Value('a'), Value('a'))
    Value(a)
    """
    name = 'and'
    op = '&&'

    def __new__(cls, *args):

        nargs = []
        for a in args:
            if a in (False, None, ''):
                return False
            elif a is True:
                continue
            elif a in nargs:
                continue
            else:
                nargs.append(a)

        if not nargs:
            return True

        if len(nargs) == 1:
            return nargs.pop(0)

        o = Function.__new__(cls)
        o.args = nargs
        return o


# Functions
# https://docs.github.com/en/actions/reference/context-and-expression-syntax-for-github-actions#functions


NAMED_FUNCTIONS = {}


class NamedFunctionMeta(ExpressionShortName):
    def __init__(self, *args, **kw):
        if self.name != None:
            NAMED_FUNCTIONS[self.name.lower()] = self
        type.__init__(self, *args, **kw)


class NamedFunction(Function, metaclass=NamedFunctionMeta):
    name = None


class ContainsF(BinFunction, NamedFunction):
    """
    https://docs.github.com/en/actions/reference/context-and-expression-syntax-for-github-actions#contains

    >>> ContainsF('Hello world', 'mo')
    False
    >>> ContainsF('Hello world', 'lo')
    True
    >>> ContainsF('Hello world', 'He')
    True
    >>> ContainsF('Hello world', 'ld')
    True
    >>> repr(ContainsF(Value('a'), 'Ho'))
    "contains(Value(a), 'Ho')"
    >>> str(ContainsF(Value('a'), 'Ho'))
    "contains(a, 'Ho')"

    """
    name = 'contains'

    @classmethod
    def realf(cls, a, b):
        assert isinstance(a, str), (a, b)
        assert isinstance(b, str), (a, b)
        return b in a


class StartsWithF(BinFunction, NamedFunction):
    """
    https://docs.github.com/en/actions/reference/context-and-expression-syntax-for-github-actions#startswith

    >>> StartsWithF('Hello world', 'He')
    True
    >>> StartsWithF('Hello world', 'Ho')
    False
    >>> repr(StartsWithF(Value('a'), 'Ho'))
    "startsWith(Value(a), 'Ho')"
    >>> str(StartsWithF(Value('a'), 'Ho'))
    "startsWith(a, 'Ho')"
    >>> str(StartsWithF(Value('a'), "M'lady"))
    "startsWith(a, 'M''lady')"

    """
    name = 'startsWith'

    @classmethod
    def realf(cls, a, b):
        assert isinstance(a, str), (a, b)
        assert isinstance(b, str), (a, b)
        return a.startswith(b)


class EndsWithF(BinFunction, NamedFunction):
    """
    https://docs.github.com/en/actions/reference/context-and-expression-syntax-for-github-actions#endswith

    >>> EndsWithF('Hello world', 'He')
    False
    >>> EndsWithF('Hello world', 'ld')
    True
    >>> repr(EndsWithF(Value('a'), 'Ho'))
    "endsWith(Value(a), 'Ho')"
    >>> str(EndsWithF(Value('a'), 'Ho'))
    "endsWith(a, 'Ho')"

    """
    name = 'endsWith'

    @classmethod
    def realf(cls, a, b):
        assert isinstance(a, str), (a, b)
        assert isinstance(b, str), (a, b)
        return a.endswith(b)


# FIXME: https://docs.github.com/en/actions/reference/context-and-expression-syntax-for-github-actions#format
# FIXME: https://docs.github.com/en/actions/reference/context-and-expression-syntax-for-github-actions#join


class ToJSONF(UnaryFunction, NamedFunction):
    """
    https://docs.github.com/en/actions/reference/context-and-expression-syntax-for-github-actions#tojson

    >>> f = ToJSONF(Value('a'))
    >>> repr(f)
    'toJSON(Value(a))'
    >>> str(f)
    'toJSON(a)'

    >>> a = ToJSONF(True)
    >>> a
    'true'
    >>> type(a)
    <class 'str'>

    """
    name = 'toJSON'

    @classmethod
    def realf(cls, a):
        return json.dumps(a)


class FromJSONF(UnaryFunction, NamedFunction):
    """
    https://docs.github.com/en/actions/reference/context-and-expression-syntax-for-github-actions#fromjson

    >>> f = FromJSONF(Value('a'))
    >>> repr(f)
    'fromJSON(Value(a))'
    >>> str(f)
    'fromJSON(a)'

    >>> a = FromJSONF('{"a": null, "b": 1.0, "c": false}')
    >>> p(a)
    {'a': None, 'b': 1.0, 'c': False}
    >>> type(a)
    <class 'dict'>

    """
    name = 'fromJSON'

    @classmethod
    def realf(cls, a):
        assert isinstance(a, str), a
        return json.loads(a)


class HashFilesF(VarArgsFunction, NamedFunction):
    """
    https://docs.github.com/en/actions/reference/context-and-expression-syntax-for-github-actions#hashfiles

    >>> f = HashFilesF(Value('a'))
    >>> repr(f)
    'hashFiles(Value(a))'
    >>> str(f)
    'hashFiles(a)'

    >>> a = HashFilesF(Value('a'), Value('b'))
    >>> repr(a)
    'hashFiles(Value(a), Value(b))'
    >>> str(a)
    'hashFiles(a, b)'

    """
    name = 'hashFiles'


# Job status check functions
# https://docs.github.com/en/actions/reference/context-and-expression-syntax-for-github-actions#job-status-check-functions


class EmptyFunction(Function):
    @property
    def args(self):
        return []

    @args.setter
    def args(self, v):
        v = list(v)
        assert len(v) == 0, v

    #def __new__(cls):
    #    return Function.__new__(cls)

    def __repr__(self):
        return '{}()'.format(self.name)

    def __str__(self):
        return '{}()'.format(self.name)


class SuccessF(EmptyFunction, NamedFunction):
    """

    >>> f = SuccessF()
    >>> repr(f)
    'success()'
    >>> str(f)
    'success()'
    """
    name = 'success'


class AlwaysF(EmptyFunction, NamedFunction):
    """

    >>> f = AlwaysF()
    >>> repr(f)
    'always()'
    >>> str(f)
    'always()'
    """
    name = 'always'


class CancelledF(EmptyFunction, NamedFunction):
    """

    >>> f = CancelledF()
    >>> repr(f)
    'cancelled()'
    >>> str(f)
    'cancelled()'
    """
    name = 'cancelled'



# Variables in statements.
class Var(Expression):
    pass


class Value(str, Var):
    """
    >>> p(NAMED_FUNCTIONS)
    {'always': <class 'exp.AlwaysF'>,
     'cancelled': <class 'exp.CancelledF'>,
     'contains': <class 'exp.ContainsF'>,
     'endswith': <class 'exp.EndsWithF'>,
     'fromjson': <class 'exp.FromJSONF'>,
     'hashfiles': <class 'exp.HashFilesF'>,
     'startswith': <class 'exp.StartsWithF'>,
     'success': <class 'exp.SuccessF'>,
     'tojson': <class 'exp.ToJSONF'>}

    >>> v = Value('hello')
    >>> print(v)
    hello
    >>> print(repr(v))
    Value(hello)
    >>> Value('startsWith')
    <class 'exp.StartsWithF'>
    >>> Value('startsWith')
    <class 'exp.StartsWithF'>

    """
    def __new__(cls, s):
        if s.lower() in NAMED_FUNCTIONS:
            return NAMED_FUNCTIONS[s.lower()]
        assert '.' not in s, s
        return str.__new__(cls, s)

    def __str__(self):
        return str.__str__(self)

    def __repr__(self):
        return 'Value('+str.__str__(self)+')'


class Lookup(tuple, Var):
    """
    >>> l = Lookup("a", "b")
    >>> print(l)
    a.b
    >>> print(repr(l))
    Lookup('a', 'b')

    >>> l = Lookup(["1", "2"])
    >>> print(l)
    1.2
    >>> print(repr(l))
    Lookup('1', '2')

    >>> l = Lookup(["1", Value("a")])
    >>> print(l)
    1[a]
    >>> print(repr(l))
    Lookup('1', Value(a))

    >>> l = Lookup("hello")
    >>> print(l)
    hello
    >>> print(repr(l))
    Value(hello)
    """
    def __new__(cls, *args):
        if len(args) == 1:
            if isinstance(args[0], str):
                return Value(args[0])
        elif len(args) > 1:
            args = (args,)
        return tuple.__new__(cls, *args)

    def __str__(self):
        o = []
        for i in self:
            if isinstance(i, Var):
                o.append('[{}]'.format(i))
            elif isinstance(i, str):
                if o:
                    o.append('.')
                o.append(i)
            else:
                raise ValueError(i)
        return ''.join(o)

    def __repr__(self):
        return 'Lookup({})'.format(", ".join(repr(i) for i in self))


def from_literal(v):
    """
    >>> repr(from_literal('null'))
    'None'

    >>> from_literal('true')
    True

    >>> from_literal('false')
    False

    >>> from_literal('711')
    711
    >>> from_literal('-711')
    -711

    >>> from_literal('2.0')
    2.0
    >>> from_literal('-2.0')
    -2.0

    >>> from_literal("'Mona the Octocat'")
    'Mona the Octocat'

    >>> from_literal("'It''s open source'")
    "It's open source"

    >>> from_literal("'It''s open source'")
    "It's open source"

    >>> from_literal("a.b")
    Lookup('a', 'b')
    >>> from_literal("a[b]")
    Lookup('a', Value(b))
    >>> from_literal("a[12]")
    Lookup('a', 12)
    >>> from_literal("a[b.c]")
    Lookup('a', Lookup('b', 'c'))
    >>> from_literal("a.b.c")
    Lookup('a', 'b', 'c')
    >>> from_literal("a[b].c")
    Lookup('a', Value(b), 'c')
    >>> from_literal("a[b][c]")
    Lookup('a', Value(b), Value(c))

    >>> from_literal("inputs")
    Value(inputs)

    """
    v = v.strip()

    if v == 'null':
        return None
    elif v == 'true':
        return True
    elif v == 'false':
        return False
    elif INT.match(v):
        return int(v)
    elif FLOAT.match(v):
        return float(v)
    elif HEX.match(v) or EXP.match(v):
        return v
    elif v[0] == "'" and v[-1] == "'":
        return v[1:-1].replace("''", "'")

    m = LOOKUP.search(v)
    if m:
        args = [v[:m.start(0)]]
        for m in LOOKUP.finditer(v):
            s = m.group()
            if s.startswith('.'):
                args.append(s[1:])
            elif s.startswith('['):
                assert s.endswith(']'), (s, v)
                args.append(from_literal(s[1:-1]))
        return Lookup(args)

    if VALUE.match(v):
        return Value(v)

    raise ValueError('Unknown literal? {!r}'.format(v))


def simplify(exp, context={}):
    """

    >>> simplify("true")
    True
    >>> simplify("false")
    False
    >>> simplify("''")
    ''
    >>> str(simplify("null"))
    'None'

    >>> simplify("inputs")
    Value(inputs)
    >>> simplify("inputs", {'inputs': 'testing'})
    'testing'
    >>> simplify("inputs.value")
    Lookup('inputs', 'value')
    >>> simplify("inputs.value", {'inputs': {'value': 'testing'}})
    'testing'

    >>> simplify("inputs.value", {'inputs': {'value': Value('testing')}})
    Value(testing)

    >>> simplify("true || inputs.value")
    True

    >>> simplify("false && inputs.value")
    False

    >>> simplify("startsWith(a, 'testing')")
    startsWith(Value(a), 'testing')

    >>> simplify("startsWith('testing-123', 'testing')")
    True

    >>> simplify("startsWith('output', 'testing')")
    False

    >>> a = simplify("!startsWith(matrix.os, 'ubuntu') && (true && startsWith('ubuntu-latest', 'ubuntu'))")
    >>> a
    not(startsWith(Lookup('matrix', 'os'), 'ubuntu'))
    >>> print(str(a))
    !startsWith(matrix.os, 'ubuntu')
    >>> simplify("!startsWith(matrix.os, 'ubuntu') && (true && null && startsWith('ubuntu-latest', 'ubuntu'))")
    False

    >>> b = simplify("a[b].c")
    >>> b
    Lookup('a', Value(b), 'c')
    >>> str(b)
    'a[b].c'

    >>> ctx = {'a': {'x': {'c': False}, 'y': {'c': True}}}
    >>> c = simplify("a[b].c", ctx)
    >>> c
    Lookup('a', Value(b), 'c')
    >>> str(c)
    'a[b].c'

    >>> ctx['b'] = 'x'
    >>> c = simplify("a[b].c", ctx)
    >>> c
    False
    >>> str(c)
    'False'

    >>> ctx['b'] = 'y'
    >>> c = simplify("a[b].c", ctx)
    >>> c
    True
    >>> str(c)
    'True'

    >>> ctx = {'a': {'x': {'c': False}, 'y': {'c': True}}}
    >>> ctx['b'] = Lookup('other', 'place')
    >>> c = simplify("a[b].c", ctx)
    >>> c
    Lookup('a', Lookup('other', 'place'), 'c')
    >>> str(c)
    'a[other.place].c'

    >>> simplify('manylinux-versions[inputs.python-version]', {'inputs': {'python-version': 12}})
    Lookup('manylinux-versions', 12)

    >>> simplify(parse('${{ inputs.empty }}'), {'inputs': {'empty': ''}})
    ''

    """
    if isinstance(exp, Expression):
        exp = str(exp)
    elif not isinstance(exp, str):
        return exp

    assert isinstance(exp, str), (exp, repr(exp))

    o = tokens_eval(tokenizer(exp), context)
    if isinstance(o, Value):
        if o in context:
            o = context[o]

    return o


def parse(s):
    """
    >>> parse(True)
    True
    >>> parse(False)
    False
    >>> parse('hello')
    'hello'
    >>> parse('${{ hello }}')
    Value(hello)
    >>> parse('${{ hello && world }}')
    and(Value(hello), Value(world))
    >>> parse('${{ hello && true }}')
    Value(hello)
    >>> parse('${{ hello || true }}')
    True

    >>> parse('a[b].c || false')
    'a[b].c || false'

    >>> parse('')
    ''

    >>> parse('${{ success() }}')
    success()

    >>> parse('${{ hashFiles() }}')
    hashFiles()
    >>> parse("${{ hashFiles('**/package-lock.json') }}")
    hashFiles('**/package-lock.json')
    >>> parse("${{ hashFiles('**/package-lock.json', '**/Gemfile.lock') }}")
    hashFiles('**/package-lock.json', '**/Gemfile.lock')
    """
    if isinstance(s, str):
        exp = s.strip()
        if exp.startswith('${{'):
            assert exp.endswith('}}'), exp
            return simplify(exp[3:-2].strip())
    return s


RE_EXP = re.compile('\\${{(.*?)}}', re.DOTALL)


def eval(s, context):
    """

    >>> eval('Hello', {})
    'Hello'

    >>> eval('Hello ${{ a }}! You are ${{ b }}.', {'a': 'world', 'b': 'awesome'})
    'Hello world! You are awesome.'

    >>> eval('Hello ${{ a }}! You are ${{ b }}.', {'a': 1, 'b': 2})
    'Hello 1! You are 2.'

    >>> eval('${{ a }}', {'a': 1})
    1

    >>> eval(' ${{ a }}', {'a': 1})
    ' 1'

    """

    exp_bits = s[:3] + s[-2:]
    mid_bits = s[3:-2]
    if exp_bits == '${{}}' and '${{' not in mid_bits:
        newe = parse(s)
        return simplify(newe, context)

    assert isinstance(s, str), (type(s), repr(s))
    def replace_exp(m):
        e = m.group(1).strip()
        v = simplify(e, context)
        if isinstance(v, Expression):
            return '${{ %s }}' % (v,)
        else:
            return str(v)

    new_s = RE_EXP.sub(replace_exp, s)
    return new_s
