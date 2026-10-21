import shutil
import subprocess
import unittest
from pathlib import Path

from fabricpy.compiler.transpiler import JavaTranspiler, TranspileError
from tests.support import project_dir


class TranspilerTests(unittest.TestCase):
    def test_reassignment_string_inequality_and_negative_range(self):
        output = JavaTranspiler({}).transpile_method('''def hook(ctx):
    value = 1
    value = 2
    for i in range(3, 0, -1):
        value += i
    if "left" != "right":
        value += 1
    return value
''')
        self.assertEqual(output.count('var value ='), 1)
        self.assertIn('i > 0', output)
        self.assertIn('!java.util.Objects.equals', output)

    def test_unsupported_python_has_actionable_errors(self):
        sources = [
            'def hook(ctx):\n    try:\n        pass\n    except Exception:\n        pass',
            'def hook(ctx):\n    x = {"a": 1}',
            'def hook(ctx):\n    for i in range(1, 5, 0):\n        pass',
            'def hook(ctx):\n    x = None',
        ]
        for source in sources:
            with self.subTest(source=source), self.assertRaises(TranspileError):
                JavaTranspiler({}).transpile_method(source)

    def test_wrong_api_arity_fails(self):
        with self.assertRaisesRegex(TranspileError, 'wrong arguments'):
            JavaTranspiler({'ctx.say': 'say({0})'}).transpile_method('def hook(ctx):\n    ctx.say()')
        with self.assertRaisesRegex(TranspileError, 'wrong arguments'):
            JavaTranspiler({'ctx.say': 'say({0})'}).transpile_method('def hook(ctx):\n    ctx.say(1, 2)')

    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK required')
    def test_generated_java_executes_with_python_result(self):
        callback = '''def hook(ctx):
    """Docstrings are ignored."""
    total = 0
    for i in range(5, -1, -1):
        total += i
    total = total + 2
    if "a" != "b":
        total += 3
    ratio = 5 / 2
    if ratio == 2.5:
        total += 10
    negative_floor = -5 // 2
    negative_floor //= 2
    inverted = ~1
    left = str(123)
    right = str(123)
    if left != right:
        total = 0
    return f"{total}:{negative_floor}:{inverted}\\n"
'''
        namespace = {}
        exec(callback, namespace)
        expected = namespace['hook'](None)
        output = JavaTranspiler({}).transpile_method(callback)
        with project_dir():
            Path('Check.java').write_text('public class Check { static String hook() {\n' + output + '\n} public static void main(String[] args) { System.out.print(hook()); }}')
            subprocess.run(['javac', 'Check.java'], check=True, capture_output=True, text=True)
            result = subprocess.run(['java', 'Check'], check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout, expected)
