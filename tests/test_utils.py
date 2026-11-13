from __future__ import annotations

import asyncio
import random
from typing import Generic, TypeVar

import pytest

from web_poet.utils import cached_method, ensure_awaitable, get_generic_param


@pytest.mark.asyncio
async def test_ensure_awaitable_sync() -> None:
    assert await ensure_awaitable(5) == 5

    def foo():
        return 42

    assert await ensure_awaitable(foo()) == 42


@pytest.mark.asyncio
async def test_ensure_awaitable_async() -> None:
    async def foo():
        return 42

    assert await ensure_awaitable(foo()) == 42

    async def bar():
        await asyncio.sleep(0.01)
        return 42

    assert await ensure_awaitable(bar()) == 42


def test_cached_method_basic() -> None:
    class Foo:
        n_called = 0

        def __init__(self, name):
            self.name = name

        @cached_method
        def meth(self):
            self.n_called += 1
            return self.n_called, self.name

    foo = Foo("first")
    assert foo.meth() == (1, "first")
    assert foo.meth() == (1, "first")

    bar = Foo("second")
    assert bar.meth() == (1, "second")
    assert bar.meth() == (1, "second")


@pytest.mark.asyncio
async def test_cached_method_async() -> None:
    class Foo:
        n_called = 0

        def __init__(self, name):
            self.name = name

        @cached_method
        async def meth(self):
            self.n_called += 1
            return self.n_called, self.name

    foo = Foo("first")
    assert await foo.meth() == (1, "first")
    assert await foo.meth() == (1, "first")

    bar = Foo("second")
    assert await bar.meth() == (1, "second")
    assert await bar.meth() == (1, "second")


def test_cached_method_argument() -> None:
    class Foo:
        n_called = 0

        def __init__(self, name):
            self.name = name

        @cached_method
        def meth(self, x):
            self.n_called += 1
            return self.n_called, self.name, x

    foo = Foo("first")
    assert foo.meth(5) == (1, "first", 5)
    assert foo.meth(5) == (1, "first", 5)
    assert foo.meth(6) == (2, "first", 6)
    assert foo.meth(6) == (2, "first", 6)


@pytest.mark.asyncio
async def test_cached_method_argument_async() -> None:
    class Foo:
        n_called = 0

        def __init__(self, name):
            self.name = name

        @cached_method
        async def meth(self, x):
            self.n_called += 1
            return self.n_called, self.name, x

    foo = Foo("first")
    assert await foo.meth(5) == (1, "first", 5)
    assert await foo.meth(5) == (1, "first", 5)
    assert await foo.meth(6) == (2, "first", 6)
    assert await foo.meth(6) == (2, "first", 6)


def test_cached_method_unhashable() -> None:
    class Foo(list):
        n_called = 0

        @cached_method
        def meth(self):
            self.n_called += 1
            return self.n_called

    foo = Foo()
    assert foo.meth() == 1
    assert foo.meth() == 1


@pytest.mark.asyncio
async def test_cached_method_unhashable_async() -> None:
    class Foo(list):
        n_called = 0

        @cached_method
        async def meth(self):
            self.n_called += 1
            return self.n_called

    foo = Foo()
    assert await foo.meth() == 1
    assert await foo.meth() == 1


def test_cached_method_exception() -> None:
    class Error(Exception):
        pass

    class Foo(list):
        n_called = 0

        @cached_method
        def meth(self):
            self.n_called += 1
            raise Error

    foo = Foo()

    for idx in range(2):
        with pytest.raises(Error):
            foo.meth()
        assert foo.n_called == idx + 1


@pytest.mark.asyncio
async def test_cached_method_exception_async() -> None:
    class Error(Exception):
        pass

    class Foo(list):
        n_called = 0

        @cached_method
        async def meth(self):
            self.n_called += 1
            raise Error

    foo = Foo()

    for idx in range(2):
        with pytest.raises(Error):
            await foo.meth()
        assert foo.n_called == idx + 1


@pytest.mark.asyncio
async def test_cached_method_async_race() -> None:
    class Foo:
        _n_called = 0

        @cached_method
        async def n_called(self):
            await asyncio.sleep(random.randint(0, 10) / 100.0)
            self._n_called += 1
            return self._n_called

    foo = Foo()
    results = await asyncio.gather(
        foo.n_called(),
        foo.n_called(),
        foo.n_called(),
        foo.n_called(),
        foo.n_called(),
    )
    assert results == [1, 1, 1, 1, 1]


ItemT = TypeVar("ItemT")


class Item:
    pass


class Item2:
    pass


class MyGeneric(Generic[ItemT]):
    pass


class MyGeneric2(Generic[ItemT]):
    pass


class Base(MyGeneric[ItemT]):
    pass


class BaseSpecialized(MyGeneric[Item]):
    pass


class BaseAny(MyGeneric):
    pass


class Derived(Base):
    pass


class Specialized(BaseSpecialized):
    pass


class SpecializedAdditionalClass(BaseSpecialized, Item2):
    pass


class SpecializedTwice(BaseSpecialized, Base[Item2]):
    pass


class SpecializedTwoGenerics(MyGeneric2[Item2], BaseSpecialized):
    pass


@pytest.mark.parametrize(
    ("cls", "param"),
    [
        (MyGeneric, None),
        (Base, None),
        (BaseAny, None),
        (Derived, None),
        (BaseSpecialized, Item),
        (Specialized, Item),
        (SpecializedAdditionalClass, Item),
        (SpecializedTwice, Item2),
        (SpecializedTwoGenerics, Item),
    ],
)
def test_get_generic_param(cls, param) -> None:
    assert get_generic_param(cls, expected=MyGeneric) == param
