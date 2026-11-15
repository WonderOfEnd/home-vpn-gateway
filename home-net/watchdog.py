#!/usr/bin/python3
"""Switch gateway modes after four consecutive checks, spaced 30 seconds apart."""
import json
from pathlib import Path
import runpy
import sys
import time

sys.dont_write_bytecode = True
STATE = Path('/run/home-net-watch.json')
REQUIRED_CHECKS = 4
MAX_CHECK_GAP = 75
STATE_VERSION = 2


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


def fresh_state(mode, now):
    return {'version': STATE_VERSION, 'mode': mode, 'failures': 0,
            'successes': 0, 'last_check': now}


def main():
    client = runpy.run_path('/usr/local/bin/home-net')
    mode = 'direct' if client['direct_mode']() else 'vpn'
    now = time.monotonic()
    state = load_state()
    previous_check = state.get('last_check')
    if (state.get('version') != STATE_VERSION or state.get('mode') != mode
            or not isinstance(previous_check, (int, float))
            or not 0 <= now - previous_check <= MAX_CHECK_GAP
            or any(type(state.get(key)) is not int or not 0 <= state[key] < REQUIRED_CHECKS
                   for key in ('failures', 'successes'))):
        state = fresh_state(mode, now)
    health = client['health']()
    # Discard a probe if a manual command changed the mode while it was running.
    current_mode = 'direct' if client['direct_mode']() else 'vpn'
    if current_mode != mode:
        save_state(fresh_state(current_mode, time.monotonic()))
        return 0
    state['last_check'] = time.monotonic()
    state['successes'] = state['successes'] + 1 if mode == 'direct' and health['vpn'] else 0
    state['failures'] = state['failures'] + 1 if mode == 'vpn' and not (health['vpn'] and health['dns']) else 0
    if state['failures']:
        print('Gateway check failed:', health, 'consecutive:', state['failures'], flush=True)
    if state['successes']:
        print('VPN recovery check passed; consecutive:', state['successes'], flush=True)
    if max(state['failures'], state['successes']) < REQUIRED_CHECKS:
        save_state(state)
        return 0
    # Start a new sequence after every attempted transition, including DNS rollback.
    save_state(fresh_state(mode, time.monotonic()))
    if mode == 'vpn':
        print('Four failed checks: enabling direct mode.', flush=True)
        result = client['enable_direct']()
    else:
        print('Four successful VPN checks: restoring VPN and checking its DNS.', flush=True)
        result = client['restore_vpn']()
    current_mode = 'direct' if client['direct_mode']() else 'vpn'
    save_state(fresh_state(current_mode, time.monotonic()))
    if current_mode == mode:
        print('Mode unchanged after transition attempt; starting a new sequence.', flush=True)
    return result


if __name__ == '__main__':
    sys.exit(main())
