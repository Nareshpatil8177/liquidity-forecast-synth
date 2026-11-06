"""One-shot helper: tests, starter + full datasets, reproducibility proof, reports.   python scripts/run_all.py"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
PY = sys.executable


def run(*args):
    print("\n$", " ".join(args), flush=True)
    r = subprocess.run([PY, *args])
    if r.returncode:
        sys.exit(r.returncode)


run("-m", "pytest", "-q")
run("-m", "liquidity", "generate", "--scale", "starter")
run("-m", "liquidity", "generate", "--scale", "full", "--formats", "csv,sql", "--gzip-sql")
os.makedirs("reports/starter", exist_ok=True)
os.makedirs("reports/full", exist_ok=True)
for sc in ("starter", "full"):
    for f in ("validation_summary.json", "evaluation_report.json", "manifest.json"):
        shutil.copy(f"data/{sc}/{f}", f"reports/{sc}/{f}")
    run("-m", "liquidity", "repro", "--scale", sc, "--out", f"reports/reproducibility_{sc}.json")
run("-m", "liquidity", "docs")
print("\nAll done. See data/, reports/ and docs/.")
