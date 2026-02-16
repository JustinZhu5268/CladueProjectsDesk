import subprocess
import sys

result = subprocess.run(
    [sys.executable, "unittest/run_tests.py"],
    cwd=r"c:\Users\Think\Desktop\ClaudeStation\claude_station",
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="ignore"
)

output = result.stdout + result.stderr
lines = output.split("\n")
# Find test summary
for i, line in enumerate(lines):
    try:
        print(line)
    except:
        pass
print("Exit code:", result.returncode)
