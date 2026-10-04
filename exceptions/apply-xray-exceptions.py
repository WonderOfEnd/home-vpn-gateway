#!/usr/bin/env python3
"""Regenerate the 'exceptions' routing rule in xray's config.json from
/etc/xray-exceptions.json and restart xray. Must run as root."""
import json
import subprocess
import sys
import time

CONFIG = "/usr/local/etc/xray/config.json"
EXCEPTIONS = "/etc/xray-exceptions.json"

with open(EXCEPTIONS) as f:
    domains = json.load(f)

with open(CONFIG) as f:
    cfg = json.load(f)

rules = [r for r in cfg["routing"]["rules"] if not r.get("_managed") == "exceptions"]

if domains:
    exceptions_rule = {
        "type": "field",
        "domain": [f"domain:{d}" for d in domains],
        "outboundTag": "direct",
        "_managed": "exceptions",
    }
    # insert right after the first rule (geoip:private bypass)
    rules.insert(1, exceptions_rule)

cfg["routing"]["rules"] = rules

backup = f"{CONFIG}.bak-{time.strftime('%Y%m%d%H%M%S')}"
with open(CONFIG) as f:
    original = f.read()
with open(backup, "w") as f:
    f.write(original)

with open(CONFIG, "w") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)

subprocess.run(["systemctl", "restart", "xray"], check=True)
print(f"ok, {len(domains)} exception(s) applied, backup={backup}")
