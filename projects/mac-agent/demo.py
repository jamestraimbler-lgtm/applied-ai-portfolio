"""Exercise the archived memory store in a disposable database, offline."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix="mac-agent-demo-") as directory:
    env = {**os.environ, "MAC_AGENT_DB": str(Path(directory) / "memory.db")}
    script = Path(__file__).parent / "source/memory_store.py"
    commands = [
        ["set", "demo-project", "Catalog monitoring walkthrough", "--category", "projects"],
        ["get", "demo-project"],
        ["search", "monitoring"],
        ["delete", "demo-project"],
        ["get", "demo-project"],
    ]
    for command in commands:
        print("$ memory_store.py " + " ".join(command), flush=True)
        subprocess.run([sys.executable, str(script), *command], env=env, check=True)
print("Finished. Temporary database removed; no personal records used.")
