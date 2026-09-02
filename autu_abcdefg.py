# autu_abcdefg.py
"""Advanced, stable, k-way merge of already-sorted iterables."""

import heapq


class _MergeEntry:
    """Heap entry that orders itself by ``(key, sequence order)`` only.

    The raw elements are never compared against each other, which is what
    makes the merge stable and lets ``key``/``reverse`` work together.

    Tie-breaking rules (identical to ``heapq.merge``/``sorted``):

      * ascending order  -> equal keys emit from *earlier* iterables first
      * descending order -> equal keys emit from *later* iterables first
    """

    __slots__ = ("key", "order", "value", "iterator", "reverse")

    def __init__(self, key, order, value, iterator, reverse):
        self.key = key
        self.order = order
        self.value = value
        self.iterator = iterator
        self.reverse = reverse

    def __lt__(self, other):
        if self.key != other.key:
            if self.reverse:
                return self.key > other.key  # want the largest key first
            return self.key < other.key
        if self.reverse:
            return self.order > other.order  # ties: later iterable first
        return self.order < other.order      # ties: earlier iterable first


def merge(*iterables, key=None, reverse=False):
    """Merge sorted iterables into one sorted list.

    A more advanced, fully backward-compatible version of the original
    two-list ``merge(left, right)``:

    * merges *any number* of sorted iterables (k-way merge),
    * accepts arbitrary iterables (lists, tuples, generators, ...),
    * supports a ``key`` function and ``reverse`` (descending) order,
    * is stable and keeps every duplicate element (multiset merge).

    Args:
        *iterables: One or more iterables, each already sorted in ascending
            order (or in descending order when ``reverse=True``).
        key: Optional function that maps each element to its sort key.
        reverse: If True, merge as if everything were sorted from largest
            to smallest.

    Returns:
        A new list containing all elements from ``iterables`` in sorted
        order. When called as ``merge(left, right)`` with two plain lists
        (no ``key``/``reverse``) the result is byte-for-byte identical to
        the original implementation.

    Examples:
        >>> merge([1, 3, 5], [2, 4, 6])
        [1, 2, 3, 4, 5, 6]
        >>> merge([], [1, 2])
        [1, 2]
        >>> merge([1, 1, 2], [1, 3])
        [1, 1, 1, 2, 3]
        >>> merge([1, 5, 9], [2, 6], [3, 7, 8])          # k-way
        [1, 2, 3, 5, 6, 7, 8, 9]
        >>> merge([(1, "a"), (3, "c")], [(2, "b")], key=lambda p: p[0])
        [(1, 'a'), (2, 'b'), (3, 'c')]
        >>> merge([5, 3, 1], [4, 2], reverse=True)
        [5, 4, 3, 2, 1]
    """
    # --- Legacy fast path: exactly the original two-list implementation ---
    if len(iterables) == 2 and key is None and not reverse:
        left, right = iterables
        if (hasattr(left, "__len__") and hasattr(left, "__getitem__")
                and hasattr(right, "__len__") and hasattr(right, "__getitem__")):
            result = []
            i = 0
            j = 0
            while i < len(left) and j < len(right):
                if left[i] <= right[j]:
                    result.append(left[i])
                    i += 1
                else:
                    result.append(right[j])
                    j += 1
            # 追加剩余元素
            result.extend(left[i:])
            result.extend(right[j:])
            return result

    # --- General k-way heap merge -------------------------------------------
    if not iterables:
        return []

    keyfunc = (lambda x: x) if key is None else key

    heap = []
    order = 0
    for iterable in iterables:
        it = iter(iterable)
        try:
            value = next(it)
        except StopIteration:
            continue  # skip empty inputs
        heapq.heappush(heap, _MergeEntry(keyfunc(value), order, value, it, reverse))
        order += 1

    result = []
    while heap:
        entry = heapq.heappop(heap)
        result.append(entry.value)
        try:
            value = next(entry.iterator)
        except StopIteration:
            continue  # this input is exhausted
        entry.value = value
        entry.key = keyfunc(value)
        heapq.heappush(heap, entry)
    return result
