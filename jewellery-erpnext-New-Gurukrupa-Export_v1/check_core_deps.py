"""
Check that core dependencies are available.
Run from project root: python check_core_deps.py

- frappe, sql_metadata, filelock: required for local dev/debug.
- erpnext: required when running inside a Frappe bench; optional in local venv.

To verify without requiring erpnext: python check_core_deps.py
"""
import sys

def main():
    ok = True
    # Required
    for mod in ("frappe", "sql_metadata", "filelock"):
        try:
            __import__(mod)
            print(f"  OK: {mod}")
        except ModuleNotFoundError as e:
            print(f"  MISSING: {mod} - {e}")
            ok = False

    # Optional outside bench (jewellery_erpnext uses it only in bench)
    try:
        __import__("erpnext")
        print("  OK: erpnext")
    except ModuleNotFoundError:
        print("  SKIP: erpnext (not installed; required only when running in Frappe bench)")

    if ok:
        print("\nAll core dependencies installed!")
        return 0
    print("\nInstall missing packages, e.g.: pip install -r requirements.txt")
    return 1

if __name__ == "__main__":
    sys.exit(main())
