import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def project_dir():
    previous = Path.cwd()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        try:
            os.chdir(root)
            yield root
        finally:
            os.chdir(previous)
