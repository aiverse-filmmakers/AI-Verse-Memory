import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
SUBPROCESS_NAMES = {"run", "check_output", "Popen", "check_call", "call"}


def python_files():
    for path in sorted(ROOT.rglob("*.py")):
        if not SKIP_DIRS.intersection(path.relative_to(ROOT).parts):
            yield path


def literal_mode(call, position):
    node = None
    if len(call.args) > position:
        node = call.args[position]
    for keyword in call.keywords:
        if keyword.arg == "mode":
            node = keyword.value
    if node is None:
        return "r"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None  # not a literal: cannot tell, so treat as text


def bare_text_calls(path):
    source = path.read_text(encoding="utf-8")
    problems = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        keywords = {k.arg for k in node.keywords}
        if name in ("read_text", "write_text"):
            bad = "encoding" not in keywords
        elif name == "open":
            owner = func.value if isinstance(func, ast.Attribute) else None
            if isinstance(owner, ast.Name) and owner.id == "os":
                continue  # os.open is a file descriptor call, not text mode
            # Path.open(mode) has mode first, builtin open(path, mode) second.
            position = 0 if isinstance(func, ast.Attribute) else 1
            mode = literal_mode(node, position)
            bad = (mode is None or "b" not in mode) and "encoding" not in keywords
        elif name in SUBPROCESS_NAMES and keywords & {"text", "universal_newlines"}:
            bad = "encoding" not in keywords
        else:
            continue
        if bad:
            problems.append(f"{path.relative_to(ROOT)}:{node.lineno} {name}() without encoding")
    return problems


class TextEncodingLintTests(unittest.TestCase):
    def test_no_text_io_without_explicit_encoding(self):
        problems = []
        for path in python_files():
            problems.extend(bare_text_calls(path))
        self.assertEqual(problems, [], "Add encoding=\"utf-8\" to:\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
