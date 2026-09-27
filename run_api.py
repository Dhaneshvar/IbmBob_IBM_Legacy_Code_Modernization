"""Launch the FastAPI API server (no reload for stability)."""
import sys
import os

# Put src/ on the path so `lm.*` imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
os.makedirs(".lm", exist_ok=True)
os.makedirs("data", exist_ok=True)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "lm.api.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,          # reload=True forks and swallows logs in PowerShell
        log_level="info",
    )
