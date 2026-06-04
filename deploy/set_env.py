"""Update keys in an .env file from a JSON object read on stdin.

Used during deploy to set secrets WITHOUT exposing values in argv / process
list / shell history. Prints only the key NAMES it changed, never the values.

Usage:
    echo '{"KEY":"value"}' | python set_env.py /opt/reachly/.env
"""
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/reachly/.env")
updates = json.load(sys.stdin)

lines = path.read_text().splitlines() if path.exists() else []
seen = set()
out = []
for line in lines:
    m = re.match(r"\s*([A-Za-z0-9_]+)\s*=", line)
    if m and m.group(1) in updates:
        k = m.group(1)
        out.append(f'{k}="{updates[k]}"')
        seen.add(k)
    else:
        out.append(line)

for k, v in updates.items():
    if k not in seen:
        out.append(f'{k}="{v}"')

path.write_text("\n".join(out) + "\n")
print("updated keys:", ", ".join(sorted(updates.keys())))
