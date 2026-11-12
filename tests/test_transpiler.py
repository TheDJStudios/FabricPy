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

    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK required')
    def test_branch_variables_keep_python_scope_without_evaluating_inactive_calls(self):
        callback = '''def hook(flag):
    if flag == 0:
        moved = ctx.stack.inventory.insert_from_hand("off_hand", 5)
        label = "inserted"
    elif flag == 1:
        moved = ctx.stack.inventory.extract_to_player(0, 3)
        label = "extracted"
    else:
        if flag == 2:
            moved = 1
        else:
            moved = 2
        label = "other"
    if label == str("inserted"):
        moved += 10
    return f"{moved}:{label}"
'''
        api = {
            'ctx.stack.inventory.insert_from_hand': 'insert({0}, {1})',
            'ctx.stack.inventory.extract_to_player': 'extract({0}, {1})',
        }
        output = JavaTranspiler(api).transpile_method(callback)
        self.assertEqual(output.count('int moved;'), 1)
        self.assertEqual(output.count('String label;'), 1)
        self.assertIn('java.util.Objects.equals(label,', output)
        with project_dir():
            Path('BranchCheck.java').write_text('''public class BranchCheck {
static int calls;
static int insert(String hand,int n){calls++;return n;}
static int extract(int slot,int n){calls++;return n;}
static String hook(int flag) {''' + output + '''}
public static void main(String[] args){
String result=hook(0)+"/"+hook(1)+"/"+hook(2)+"/"+hook(3);
if(calls!=2)throw new AssertionError("inactive branch evaluated");
System.out.print(result);
}}''')
            subprocess.run(['javac', 'BranchCheck.java'], check=True, capture_output=True, text=True)
            result = subprocess.run(['java', 'BranchCheck'], check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout, '15:inserted/3:extracted/1:other/2:other')

    def test_branch_type_errors_explain_how_to_fix_callback(self):
        sources = [
            ('if ctx.flag:\n        value = "text"\n    else:\n        value = 1', 'incompatible types'),
            ('if ctx.flag:\n        local = 1\n        value = local\n    else:\n        value = 2', 'branch-local'),
            ('if ctx.flag:\n        value = ctx.unknown()\n    else:\n        value = ctx.other()', 'initialize it before'),
        ]
        for body, message in sources:
            with self.subTest(body=body), self.assertRaisesRegex(TranspileError, message):
                JavaTranspiler({}).transpile_method('def hook(ctx):\n    ' + body + '\n    return value')

    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK required')
    def test_branch_numeric_promotion_and_boolean_values(self):
        output = JavaTranspiler({}).transpile_method('''def hook(flag):
    if flag:
        number = 1000
        enabled = True
    else:
        number = 2.5
        enabled = False
    if enabled:
        number += 0.5
    return number
''')
        self.assertIn('double number;', output)
        self.assertIn('boolean enabled;', output)
        with project_dir():
            Path('NumericCheck.java').write_text('public class NumericCheck { static double hook(boolean flag) {' + output + '} public static void main(String[] args) {System.out.print(hook(true)+":"+hook(false));}}')
            subprocess.run(['javac', 'NumericCheck.java'], check=True, capture_output=True, text=True)
            result = subprocess.run(['java', 'NumericCheck'], check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout, '1000.5:2.5')
