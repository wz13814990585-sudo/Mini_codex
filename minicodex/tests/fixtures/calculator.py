"""Small calculator fixture used by agent-generated tests."""

def add(a, b):
    """Return the sum of two numbers."""
    return a + b


def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
