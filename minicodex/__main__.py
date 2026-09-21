"""Allow ``python -m minicodex`` to behave like the installed command."""

from .main import main


if __name__ == "__main__":
    raise SystemExit(main())
