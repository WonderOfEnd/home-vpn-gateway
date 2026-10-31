# Maintenance

This repository stores reviewed, parameterized configuration for home, VPS service
templates, and the companion workstation tools. After an authorized change on
those machines, update the corresponding source/template and its documentation
here as part of the same task. Check GitHub's current head before publishing;
commit and push the related changes when repository synchronization is authorized.

Keep client UUIDs, private keys, MTProto secrets, passwords, client databases,
raw logs, Minecraft binaries/worlds, and personal session snapshots out of Git.
Use placeholders or local environment files. Distinguish deployed behavior from
template adaptations and tested checks from untested reboot/VM behavior.

Validate changed JSON/Python/shell files and desktop entries. Check Xray using
synthetic credentials in test mode and Compose using config only. Do not restart
the gateway, containers, games, or VMs merely to validate repository copies.
