# Repository scope

This repository is only for the home VPN gateway server: Xray, Pi-hole,
iptables/policy routing, DNS, LAN exceptions, and server-side routing fixes
such as Discord voice or TruckersMP. Keep unrelated website hosting,
workstation tools, desktop settings, games, and external-server service
backups out of this repository. The external VPN server is a prerequisite
described in the README, not a deployment target of this repository.

After an authorized gateway change, update the corresponding source/template
and documentation here. Check the current GitHub head before publishing and
commit/push when synchronization is authorized. Keep credentials, client UUIDs,
private keys, passwords, live databases and raw logs out of Git; use placeholders
or local environment files.

Validate changed JSON/Python/shell files. Check Xray using synthetic credentials
in test mode and Compose using config only. Do not restart the working gateway
or its containers merely to validate repository copies.
