"""Sorting algorithms.

This module provides a clean-room implementation of quicksort so it can be
verified against Python's built-in :func:`sorted` in the test suite.
"""

from __future__ import annotations

from typing import List, TypeVar

T = TypeVar("T")


def sort(arr: List[T]) -> List[T]:
    """Return a new list with the elements of ``arr`` sorted in ascending order.

    The input list is not modified.  Elements must be mutually comparable
    (i.e. support ``<`` and ``==``), which holds for numbers and strings.

    This is an in-place-free, recursion-based quicksort:

    * empty/single-element lists are already sorted;
    * otherwise pick the middle element as the pivot and recurse on the
      left/equal/right partitions.
    """
    if len(arr) <= 1:
        return list(arr)

    pivot = arr[len(arr) // 2]
    left: List[T] = []
    middle: List[T] = []
    right: List[T] = []

    for item in arr:
        if item < pivot:
            left.append(item)
        elif item == pivot:
            middle.append(item)
        else:
            right.append(item)

    return sort(left) + middle + sort(right)
