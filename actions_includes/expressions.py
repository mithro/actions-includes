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


import re

class ShortName(type):
    def __repr__(self):
        return "<class 'exp.{}'>".format(self.__name__)


class Expression(metaclass=ShortName):
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
    >>> to_literal(2.0)
    '2.0'
    >>> to_literal('Mona the Octocat')
    "'Mona the Octocat'"
    >>> to_literal("It's open source")
    "'It''s open source'"
    >>> to_literal(Value("hello"))
    'hello'
    >>> to_literal(Lookup("hello", "testing"))
    'hello.testing'
    """
    if isinstance(v, (Value, Lookup)):
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
FLOAT = re.compile('^-?[0-9]+\.[0-9]+$')
HEX = re.compile('^0x[0-9a-fA-F]+$')
EXP = re.compile('^(-?[0-9]+\.\[0-9]+)-?[eE]([0-9.]+)$')
VALUE = re.compile('^[a-zA-Z][_a-zA-Z0-9\\-]*$')
LOOKUP = re.compile('(?:\\.[a-zA-Z][_a-zA-Z0-9\\-]*)|(?:\\[[^\\]]+\\])')

S = "('[^']*')+"
I = "[a-zA-Z.\\-0-9_]+"

BITS = re.compile('((?P<S>{})|(?P<I>{}))'.format(S, I))


def swizzle(l):
    """

    >>> swizzle([1, '&&', 2])
    (<class 'exp.AndF'>, 1, 2)
    >>> swizzle([1, '&&', 2, '&&', 3])
    (<class 'exp.AndF'>, 1, (<class 'exp.AndF'>, 2, 3))
    >>> swizzle(['!', 1, '&&', 2, '&&', 3])
    (<class 'exp.AndF'>, (<class 'exp.NotF'>, 1), (<class 'exp.AndF'>, 2, 3))
    >>> swizzle(['!', [1, '&&', 2, '&&', 3]])
    (<class 'exp.NotF'>, (<class 'exp.AndF'>, 1, (<class 'exp.AndF'>, 2, 3)))


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

            f = {'&&': AndF, '||': OrF}
            if b in f:
                return (f[b], a, c)
        if len(l) == 1:
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
    >>> from pprint import pprint as p

    >>> p(tokenizer("secrets.GITHUB_TOKEN"))
    Lookup('secrets', 'GITHUB_TOKEN')
    >>> p(tokenizer("inputs.use-me"))
    Lookup('inputs', 'use-me')

    >>> p(tokenizer("!startswith(matrix.os, 'ubuntu') && (true && null && startswith('ubuntu-latest', 'ubuntu'))"))
    (<class 'exp.AndF'>,
     (<class 'exp.NotF'>,
      (<class 'exp.StartsWith'>, Lookup('matrix', 'os'), 'ubuntu')),
     (<class 'exp.AndF'>,
      True,
      (<class 'exp.AndF'>,
       None,
       (<class 'exp.StartsWith'>, 'ubuntu-latest', 'ubuntu'))))
    >>> p(tokenizer("!startswith(matrix.os, 'ubuntu') && (true && startswith('ubuntu-latest', 'ubuntu'))"))
    (<class 'exp.AndF'>,
     (<class 'exp.NotF'>,
      (<class 'exp.StartsWith'>, Lookup('matrix', 'os'), 'ubuntu')),
     (<class 'exp.AndF'>,
      True,
      (<class 'exp.StartsWith'>, 'ubuntu-latest', 'ubuntu')))

    """
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
            if i == l:
                stack[-1][-1] += i
                continue
            elif isinstance(l, type) and issubclass(l, Function):
                assert len(i) == 3, (l, i)
                assert i[1] == ',', (l, i)
                #r = l(i[0], i[2])
                #print('Eval: {}({}, {}) = {}'.format(l, i[0], i[2], r))
                stack[-1][-1] = (l, i[0], i[2])
                continue
        stack[-1].append(i)

    assert len(stack) == 1, stack
    return swizzle(stack[0])


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

    >>> tokens_eval((StartsWith, 'ubuntu-latest', 'ubuntu'))
    True
    >>> tokens_eval((StartsWith, 'Windows', 'ubuntu'))
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
    (Value(x), Lookup('c', Value(a)))

    """
    assert not isinstance(t, list), t

    if isinstance(t, Lookup) and context:
        v = context
        to = list(t)
        while len(to) > 0 and isinstance(v, dict):
            if isinstance(to[0], Value):
                if to[0] in context:
                    to[0] = context[to[0]]
            if to[0] not in v:
                break
            v = v[to.pop(0)]
        if not to:
            t = v

    if isinstance(t, Value) and context:
        if t in context:
            t = context[t]

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
    pass


class BinFunction(Function):
    @property
    def args(self):
        return [self.a, self.b]

    @args.setter
    def args(self, v):
        v = list(v)
        assert len(v) == 2, v
        self.a = v.pop(0)
        self.b = v.pop(1)
        assert not v, v


class NotF(Function):
    """
    >>> a1 = NotF(Value('a'))
    >>> a1
    not(Value(a))
    >>> str(a1)
    '!a'

    >>> NotF(True)
    False

    >>> NotF(False)
    True

    >>> NotF(None)
    True

    >>> NotF('')
    True

    """
    def __new__(cls, v):
        if v is True:
            return False
        if v in (False, None, ''):
            return True

        o = Function.__new__(cls)
        o.args = [v]
        return o


    def __repr__(self):
        return 'not({})'.format(repr(self.args[0]))

    def __str__(self):
        if isinstance(self.args[0], InfixFunction):
            return '!({})'.format(str(self.args[0]))
        return '!'+str(self.args[0])


class InfixFunction(Function):
    name = None
    op = None

    def __repr__(self):
        return '{}({})'.format(self.name, ', '.join(repr(i) for i in self.args))

    def __str__(self):
        return ' {} '.format(self.op).join(str(i) for i in self.args)


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


class StartsWith(BinFunction):
    """

    >>> StartsWith('Hello world', 'He')
    True
    >>> StartsWith('Hello world', 'Ho')
    False
    >>> repr(StartsWith(Value('a'), 'Ho'))
    "startswith(Value(a), 'Ho')"
    >>> str(StartsWith(Value('a'), 'Ho'))
    "startswith(a, 'Ho')"

    """
    def __new__(cls, a, b):
        if isinstance(a, (Value, Lookup)) or isinstance(b, (Value, Lookup)):
            o = Function.__new__(cls)
            o.a = a
            o.b = b
            return o
        a = str(a)
        b = str(b)
        return a.startswith(b)

    def __repr__(self):
        return 'startswith({!r}, {!r})'.format(self.a, self.b)
    def __str__(self):
        a = self.a
        if isinstance(a, str) and not isinstance(a, Value):
            a = repr(a)
        b = self.b
        if isinstance(b, str) and not isinstance(b, Value):
            b = repr(b)
        return 'startswith({}, {})'.format(a, b)


FUNCTIONS = {
    'startswith': StartsWith,
}



#BITS = re.compile('[0-9-.a-zA-Z]

class Value(str, Expression):
    """
    >>> v = Value('hello')
    >>> print(v)
    hello
    >>> print(repr(v))
    Value(hello)
    >>> Value('startswith')
    <class 'exp.StartsWith'>
    >>> Value('startsWith')
    <class 'exp.StartsWith'>

    """
    def __new__(cls, s):
        if s.lower() in FUNCTIONS:
            return FUNCTIONS[s.lower()]
        return str.__new__(cls, s)

    def __str__(self):
        return str.__str__(self)

    def __repr__(self):
        return 'Value('+str.__str__(self)+')'


class Lookup(tuple, Expression):
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

    """
    def __new__(cls, *args):
        if len(args) > 1:
            args = (args,)
        return tuple.__new__(cls, *args)

    def __str__(self):
        o = []
        for i in self:
            if isinstance(i, Value):
                o.append('[{}]'.format(i))
            elif isinstance(i, str):
                if o:
                    o.append('.')
                o.append(i)
            else:
                raise ValueError(i)
        return ''.join(o)

    def __repr__(self):
        return 'Lookup'+tuple.__repr__(self)


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

    >>> from_literal('2.0')
    2.0

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
                args.append(Value(s[1:-1]))
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
    False
    >>> simplify("null")
    False

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

    >>> simplify("startswith(a, 'testing')")
    startswith(Value(a), 'testing')

    >>> simplify("startswith('testing-123', 'testing')")
    True

    >>> simplify("startswith('output', 'testing')")
    False

    >>> a = simplify("!startswith(matrix.os, 'ubuntu') && (true && startswith('ubuntu-latest', 'ubuntu'))")
    >>> a
    not(startswith(Lookup('matrix', 'os'), 'ubuntu'))
    >>> print(str(a))
    !startswith(matrix.os, 'ubuntu')
    >>> simplify("!startswith(matrix.os, 'ubuntu') && (true && null && startswith('ubuntu-latest', 'ubuntu'))")
    False

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

    if o in (True, False):
        return o
    elif o in ('', None):
        return False
    else:
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

    """
    if isinstance(s, str):
        exp = s.strip()
        if exp.startswith('${{'):
            assert exp.endswith('}}'), exp
            return simplify(exp[3:-2].strip())
    return s
