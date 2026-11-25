# planetai-reticulum

The Reticulum bridge for a [PLANETAI node](https://github.com/fabcity/planetai-node). It gives the node an LXMF
address, so people can write to it from Sideband or NomadNet over the LAN, the tailnet or a LoRa radio, with no
internet in between.

It runs in its own container, beside the node, and does four things:

- announces the node's LXMF address
- turns a message like `act 12 closed the windows` into an action on alert 12, the same as a Telegram reply. It
  takes one only from an address the node sends its alerts to, so a stranger on a shared network cannot close them
- delivers the node's alerts to the LXMF addresses the node sends with each one (Set up › Sharing on the node).
  A node too old to send them gets the bridge's own `RETICULUM_ALERT_DESTINATIONS` instead
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

## Running a hub

A hub is a node that other nodes dial, so they hear each other with nothing open on their own routers. Node #1 in
Bali is the first one, reached through Tailscale Funnel at `fabalabbali.tail71245c.ts.net:443`. `planetai reticulum`
on any node asks whether to dial it, and writes the `[[Fab City hub]]` block of `config.tpl` when the answer is yes.

To make a node a hub:

1. Turn transport on in its own `config/reticulum/config`, then `docker compose restart reticulum` (the bridge reads
   the file when it starts):

   ```
   [reticulum]
     enable_transport = Yes
   ```

2. Let the internet reach its port 4242. Through Tailscale Funnel, on a machine the tailnet policy grants `funnel`:

   ```bash
   sudo tailscale funnel --bg --tls-terminated-tcp=443 tcp://localhost:4242
   ```

   Funnel takes only TLS, so nodes dial it through `openssl s_client` in a `PipeInterface`, as the block in
   `config.tpl` does. Without Funnel, forward TCP 4242 on the router, or run a small relay with a fixed address that
   does only `socat TCP-LISTEN:4242,fork,reuseaddr TCP:<the node's tailnet name>:4242`. Nodes then dial it with a
   plain `TCPClientInterface`.

3. Check `curl localhost:4243/health`: `transport` is `true`, and `TCP Server` under `interfaces` counts the nodes
   connected (`clients`). On a node that dials a hub, `Fab City hub` says whether it is up.

A hub keeps what Reticulum needs to route, paths and known identities, and nothing more. Each node on it decides what
it says: its name and LXMF address always, its rough map cell only with presence on.

## Changing it

```bash
python3 tests/test_peers.py
```

To move the rns or lxmf pin, read `LICENSE` at the new tag first, then change the Dockerfile here and move
`RETICULUM_REF` in planetai-node in its own PR.
