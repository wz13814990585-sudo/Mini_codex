"""Check semantic edit contracts and deterministic diff quality separately from I/O."""
from dataclasses import dataclass
from contextvars import ContextVar
from pathlib import Path
import ast
import difflib

ACTIVE_EDIT_INTENT = ContextVar("active_edit_intent", default=None)


@dataclass(frozen=True)
class EditIntent:
    path: str
    expected_text: str = ""
    removed_text: str = ""
    symbol: str = ""
    allowed_paths: tuple[str, ...] = ()
    allow_contract_change: bool = False

    @classmethod
    def from_arguments(cls, arguments, *, allowed_paths=()):
        return cls(str(arguments.get("path", "")), str(arguments.get("new_text", arguments.get("content", ""))),
                   str(arguments.get("old_text", "")), str(arguments.get("symbol", "")), tuple(allowed_paths))


@dataclass(frozen=True)
class PostEditVerification:
    passed: bool
    issues: tuple[str, ...]


class DiffQualityGate:
    def check(self, intent, before, after):
        issues = []
        path = Path(intent.path)
        if intent.allowed_paths and intent.path not in intent.allowed_paths:
            issues.append("out_of_scope")
        if any(p in {".git", "node_modules", "vendor", ".venv"} for p in path.parts):
            issues.append("protected_path")
        old, new = before.splitlines(), after.splitlines()
        if len(old) >= 40 and len(new) < len(old) * .4:
            issues.append("mass_deletion")
        matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
        changed = sum(max(j-i, l-k) for tag, i, j, k, l in matcher.get_opcodes() if tag != "equal")
        if len(old) >= 200 and changed > len(old) * .8:
            issues.append("oversized_rewrite")
        if ("test" in path.name or "tests" in path.parts) and not intent.allow_contract_change:
            if before.count("assert ") > after.count("assert "):
                issues.append("assertions_removed")
            if after.count(".skip") > before.count(".skip") or after.count("xfail") > before.count("xfail"):
                issues.append("tests_disabled")
        if path.suffix == ".py":
            try:
                tree = ast.parse(after)
                imports = [ast.dump(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
                names = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
                try:
                    old_tree = ast.parse(before)
                except SyntaxError:
                    old_tree = ast.parse("")
                old_imports = [ast.dump(n) for n in old_tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
                old_names = [n.name for n in old_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
                if len(imports) - len(set(imports)) > len(old_imports) - len(set(old_imports)):
                    issues.append("duplicate_imports")
                if len(names) - len(set(names)) > len(old_names) - len(set(old_names)):
                    issues.append("duplicate_definitions")
            except SyntaxError:
                issues.append("syntax_invalid")
        return tuple(issues)


def verify_edit_intent(intent, before, after, *, defer_syntax=False):
    issues = list(DiffQualityGate().check(intent, before, after))
    if defer_syntax and "syntax_invalid" in issues:
        issues.remove("syntax_invalid")
    if intent.expected_text and intent.expected_text not in after:
        issues.append("expected_text_missing")
    if intent.removed_text and intent.removed_text != intent.expected_text and intent.removed_text in after:
        # Only demand deletion when it is not deliberately retained in replacement.
        if intent.removed_text not in intent.expected_text:
            issues.append("removed_text_still_present")
    if intent.symbol:
        if Path(intent.path).suffix == ".py":
            try:
                body = ast.parse(after).body
                for part in intent.symbol.split("."):
                    node = next((n for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == part), None)
                    if node is None:
                        issues.append("expected_symbol_missing")
                        break
                    body = node.body
            except SyntaxError:
                if not defer_syntax:
                    issues.append("expected_symbol_unverifiable")
        elif intent.symbol not in after:
            issues.append("expected_symbol_missing")
    if before == after:
        issues.append("no_change")
    return PostEditVerification(not issues, tuple(issues))
