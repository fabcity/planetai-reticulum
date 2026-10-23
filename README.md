# planetai-reticulum

The Reticulum bridge for a [PLANETAI node](https://github.com/fabcity/planetai-node). It gives the node an LXMF
address, so people can write to it from Sideband or NomadNet over the LAN, the tailnet or a LoRa radio, with no
internet in between.

It runs in its own container, beside the node, and does four things:

- announces the node's LXMF address
- turns a message like `act 12 closed the windows` into an action on alert 12, the same as a Telegram reply
- delivers the node's alerts to the LXMF addresses in `RETICULUM_ALERT_DESTINATIONS`
- if the household turns presence on, announces the node's name and a coarse map cell, and keeps a list of the
  other nodes it hears

The node talks to it over HTTP only (`/health`, `/peers`, `/send`), and it talks back to the node's API. It never
sees the node's `.env`: compose hands it eight variables and that is all it reads.

## Why it has its own repository

The node is moving from Apache-2.0 to AGPL-3.0. rns and lxmf are under the Reticulum License, which adds two
conditions to MIT, and the AGPL does not allow extra conditions on a work that imports them. So the bridge left the
node's repository on 23 October 2026 and stays Apache-2.0 here. Read [NOTICE](NOTICE) before you turn it on. The
node's record of the decision is `docs/decisions/2026-10-23-reticulum-licence.md` in planetai-node.

## Installing it

On a node:

```bash
planetai reticulum
```

The node downloads this repository at the commit its release pins (`RETICULUM_REF` in `bin/planetai`), builds the
image on your machine and starts it. `planetai update` fetches it again whenever the pin moves. The identity lives in
the node's `reticulum` volume, so a rebuild keeps the address. Deleting the volume gives the node a new one.

## Changing it

```bash
python3 tests/test_peers.py
```

To move the rns or lxmf pin, read `LICENSE` at the new tag first, then change the Dockerfile here and move
`RETICULUM_REF` in planetai-node in its own PR.
