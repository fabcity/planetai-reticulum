# Reticulum config for the node. `planetai reticulum` copies it to the node's config/reticulum/config once,
# and never over a copy you have edited.
# Interfaces:
#   TCP server: Sideband, NomadNet or another node connects here over the LAN or the tailnet. Always on.
#   Fab City hub: dials the hub so this node hears other nodes, with nothing open on your router. Others on the hub
#               see this node's name and LXMF address. `planetai reticulum` asks, and writes the block below
#               uncommented when you say yes. Tailscale Funnel carries it, which takes only TLS, so openssl wraps it.
#   RNode:      a LoRa radio on USB. Commented out: needs the device passed into the container (Linux only;
#               macOS Docker cannot see USB serial) and the frequency for your region.
[reticulum]
  enable_transport = No          # Yes only on a hub: it passes other nodes' announces and messages on
  share_instance = Yes
  shared_instance_port = 37428
  instance_control_port = 37429
  panic_on_interface_error = No

[logging]
  loglevel = 3

[interfaces]
  [[TCP Server]]
    type = TCPServerInterface
    enabled = yes
    listen_ip = 0.0.0.0
    listen_port = 4242

  # [[Fab City hub]]
  #   type = PipeInterface
  #   enabled = yes
  #   command = openssl s_client -quiet -verify_return_error -connect fabalabbali.tail71245c.ts.net:443 -servername fabalabbali.tail71245c.ts.net
  #   respawn_delay = 15

  # [[RNode LoRa]]
  #   type = RNodeInterface
  #   enabled = yes
  #   port = /dev/ttyACM0
  #   frequency = 923000000        # AS923 (Bali / SE Asia) · 868000000 EU · 915000000 US. Match local law.
  #   bandwidth = 125000
  #   txpower = 17
  #   spreadingfactor = 8
  #   codingrate = 5
