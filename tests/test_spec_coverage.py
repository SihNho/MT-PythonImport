import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_spec_coverage_passes():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "spec_coverage.py"), ROOT],
                       check=False, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
