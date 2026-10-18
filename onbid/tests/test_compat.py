"""루틴 컨테이너의 기본 python3는 3.11이다. 3.12부터 되는 문법(f-string 표현식 안의 역슬래시·같은 종류 따옴표)을 쓰면 실행이 처음부터 죽는다."""
import ast
import glob
import os
import shutil
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FILES = sorted(glob.glob(os.path.join(REPO_ROOT, "onbid", "*.py")) + glob.glob(os.path.join(REPO_ROOT, "onbid", "tests", "*.py")))


class TestPy311Syntax(unittest.TestCase):
    def test_compiles_under_python311_when_available(self):
        py = shutil.which("python3.11") or ("/usr/bin/python3.11" if os.path.exists("/usr/bin/python3.11") else None)
        if not py:
            self.skipTest("python3.11 없음(아래 AST 검사가 대신 본다)")
        bad = []
        for f in FILES:
            r = subprocess.run([py, "-B", "-c", "import sys; compile(open(sys.argv[1], encoding='utf-8').read(), sys.argv[1], 'exec')", f],
                               capture_output=True, text=True)
            if r.returncode:
                bad.append(f"{os.path.relpath(f, REPO_ROOT)}: {r.stderr.strip().splitlines()[-1]}")
        self.assertEqual(bad, [])

    def test_no_backslash_or_same_quote_inside_fstring_expressions(self):
        bad = []
        for f in FILES:
            src = open(f, encoding="utf-8").read()
            for node in ast.walk(ast.parse(src)):
                if not isinstance(node, ast.JoinedStr):
                    continue
                whole = ast.get_source_segment(src, node) or ""
                head = whole.lstrip("fFrRbBuU")
                quote = head[:3] if head[:3] in ('"""', "'''") else head[:1]
                for part in node.values:
                    if not isinstance(part, ast.FormattedValue):
                        continue
                    seg = ast.get_source_segment(src, part.value) or ""
                    if "\\" in seg or (len(quote) == 1 and quote in seg):
                        bad.append(f"{os.path.relpath(f, REPO_ROOT)}:{part.lineno}: {seg[:60]}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
