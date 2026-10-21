import uvicorn
import sys
import os

# Add project root to python path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

if __name__ == "__main__":
    print("=" * 70)
    print("  NDMA SMART DISASTER RESPONSE COORDINATION SYSTEM")
    print("  Powered by DuckDB 2.0 In-Process Vectorized Analytical Database")
    print("=" * 70)
    print("  Starting Command Server on http://127.0.0.1:8000")
    print("=" * 70)
    uvicorn.run("backend.app:app", host="127.0.0.1", port=8000, reload=False)
