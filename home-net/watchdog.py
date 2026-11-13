#!/usr/bin/python3
"""Recover failures automatically; never switch back from direct mode by timer."""
import json
from pathlib import Path
import runpy
import sys
import time

sys.dont_write_bytecode = True
STATE = Path('/run/home-net-watch.json')
COOLDOWN = 300


def load_state():
    try:
        data = json.loads(STATE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state):
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state))
    temporary.chmod(0o600)
    temporary.replace(STATE)


def main():
    client = runpy.run_path('/usr/local/bin/home-net')
    state = load_state()
    if client['direct_mode']():
        state['failures'] = 0
        save_state(state)
        return 0
    health = client['health']()
    if health['vpn'] and health['dns']:
        state['failures'] = 0
        save_state(state)
        return 0
    state['failures'] = state.get('failures', 0) + 1
    print('Gateway check failed:', health, 'consecutive:', state['failures'], flush=True)
    if state['failures'] < 2:
        save_state(state)
        return 0
    # Recheck after probes: a manual command may already have restored connectivity.
    if client['direct_mode']():
        state['failures'] = 0
        save_state(state)
        return 0
    now = time.monotonic()
    last = state.get('last_attempt')
    state['failures'] = 0
    if last is not None and now - last < COOLDOWN:
        save_state(state)
        print('Repeated failure during cooldown: enabling direct mode.', flush=True)
        return client['enable_direct']()
    state['last_attempt'] = now
    save_state(state)
    print('Attempting one Xray recovery; direct mode is the fallback.', flush=True)
    return client['recover']()


if __name__ == '__main__':
    sys.exit(main())
