"""Peers heard over Reticulum must outlive the container that heard them.

`heard` was a plain dict in memory. `planetai update` recreates containers, so a node forgot every peer
it knew on every update and showed "alone" on the Network tab until each one announced again — up to
RETICULUM_ANNOUNCE_S (30 minutes) later. Watched happen four times on 14 September while verifying the
presence fixes; the peer table was empty after every single update.

Runs the bridge's real _load_heard/_save_heard, lifted out of the module, against a temp directory. The
bridge itself imports RNS and LXMF, which this test has no business needing, so the two functions and
the constants they close over are exec'd on their own.
"""
import json
import logging
import os
import pathlib
import tempfile
import threading

src = pathlib.Path(__file__).resolve().parent.parent.joinpath("reticulum_bridge.py").read_text()

# the two functions plus PEERS_FILE, out of the real file. Never a retyped copy.
assert "PEERS_FILE = os.path.join(DATA" in src, (
    "reticulum_bridge.py has no PEERS_FILE — peers are back to memory only, so every restart "
    "empties the Network tab until each peer announces again (up to RETICULUM_ANNOUNCE_S later)")
start = src.index("PEERS_FILE = os.path.join(DATA")
end = src.index("\n_load_heard()", start)   # the bare call at column 0, not the def line
block = src[start:end]
assert "def _load_heard" in block and "def _save_heard" in block, "could not lift the peer store out of the bridge"

d = tempfile.mkdtemp()
ns = {"os": os, "json": json, "threading": threading, "DATA": d,
      "log": logging.getLogger("t"), "heard": {}}
exec(compile(block, "bridge-peers", "exec"), ns)          # noqa: S102 — the point is to run the real code

fails = 0
def chk(name, cond):
    global fails
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    fails += 0 if cond else 1

# nothing written yet: a first run is not an error
ns["_load_heard"]()
chk("a first run with no file starts empty", ns["heard"] == {})

# one peer, saved and read back by a fresh 'container'
ns["heard"]["ab12"] = {"hash": "ab12", "node": "dieznode", "cell": "838db5fffffffff",
                       "res": 3, "first": 1, "last": 2, "version": "v0.53", "kind": "home"}
ns["_save_heard"]()
chk("the file lands in DATA, not the cwd", os.path.isfile(os.path.join(d, "peers.json")))

ns2 = dict(ns); ns2["heard"] = {}
exec(compile(block, "bridge-peers", "exec"), ns2)          # noqa: S102
ns2["_load_heard"]()
chk("a restart remembers the peer", ns2["heard"].get("ab12", {}).get("node") == "dieznode")
chk("and its cell, so the tab can still place it", ns2["heard"]["ab12"]["cell"] == "838db5fffffffff")

# the write is atomic: no .tmp is left behind for the next run to trip over
chk("no .tmp left behind", not os.path.exists(os.path.join(d, "peers.json.tmp")))

# a corrupt file must not kill the bridge — the next announce rebuilds the list anyway
pathlib.Path(d, "peers.json").write_text("{ this is not json")
ns3 = dict(ns); ns3["heard"] = {}
exec(compile(block, "bridge-peers", "exec"), ns3)          # noqa: S102
try:
    ns3["_load_heard"]()
    chk("a corrupt file is survivable", ns3["heard"] == {})
except Exception as e:                                     # noqa: BLE001
    chk(f"a corrupt file is survivable (raised {type(e).__name__})", False)

# a row with no node name is a stranger's malformed announce, not a peer
pathlib.Path(d, "peers.json").write_text(json.dumps({"cd34": {"hash": "cd34"}, "ef56": "not a dict"}))
ns4 = dict(ns); ns4["heard"] = {}
exec(compile(block, "bridge-peers", "exec"), ns4)          # noqa: S102
ns4["_load_heard"]()
chk("malformed rows are dropped on load", ns4["heard"] == {})

# Presence listens as well as it announces. These lived in planetai-node's tests/test_shipped.py until the bridge
# moved here (23 Oct 2026); the node's dashboard lists heard peers on the strength of them.
chk("it collects other nodes' announces", "register_announce_handler" in src)
chk("on its own aspect, not on LXMF delivery", 'aspect_filter = "planetai.presence"' in src)
chk("and hands what it heard to the node at /peers", '"/peers"' in src)
chk("its own announce is not a peer", "if h == RNS.hexrep(PRESENCE.hash" in src)
chk("it asks the node what to announce", "/presence" in src)

# The node's docker-compose.yml passes this container eight variables and no env_file, so a variable read here and
# not listed there is always empty. The list is the one in planetai-node's compose `reticulum` service.
import re
ENV = {"LOG_LEVEL", "NODE_NAME", "NODE_API_URL", "RETICULUM_CONFIGDIR", "RETICULUM_DATA",
       "RETICULUM_ALERT_DESTINATIONS", "RETICULUM_ANNOUNCE_S", "ACT_TOKEN"}
read = set(re.findall(r"getenv\(['\"]([A-Z_]+)['\"]", src))
chk(f"reads exactly the eight compose passes it (extra: {sorted(read - ENV)}, unread: {sorted(ENV - read)})", read == ENV)

# A node that is still starting must not cost half an hour of silence. `planetai update` restarts the app and this
# container together; the first GET /presence found no node, announce_presence gave up, and the loop slept
# RETICULUM_ANNOUNCE_S. Seen on node #1 on 23 Oct 2026 at 12:54 UTC. The real two functions run here against a node
# that answers on the third ask; the loop's long sleep ends the test.
lift = lambda a, b: src[src.index(a):src.index(b, src.index(a))]
WHO = "# ---------------------------------------------------------------- who may act"
block = lift("def announce_presence", "\n\n" + WHO) + "\n\n" + lift("def announce_loop", "\n\nthreading.Thread")

class Stop(BaseException): pass
asks, sleeps, said = [], [], []
def get(url, timeout):
    asks.append(url)
    if len(asks) < 3:
        raise ConnectionError("app not up yet")
    return type("R", (), {"json": lambda self: {"enabled": True, "node": "dieznode", "cell": "838db5fffffffff", "res": 3}})()
def sleep(s):
    sleeps.append(s)
    if s == 1800:
        raise Stop
fake = lambda **kw: type("F", (), kw)
ns = {"httpx": fake(get=staticmethod(get)), "time": fake(sleep=staticmethod(sleep)), "json": json,
      "API": "http://app", "ANNOUNCE_S": 1800, "announcing": False, "log": logging.getLogger("t"),
      "router": fake(announce=staticmethod(lambda h: None)), "me": fake(hash=b"x"),
      "PRESENCE": fake(announce=staticmethod(lambda app_data: said.append(app_data)))}
exec(compile(block, "bridge-announce", "exec"), ns)        # noqa: S102
try:
    ns["announce_loop"]()
except Stop:
    pass
chk(f"a node not up yet is asked again soon (slept {sleeps})", sleeps == [30, 30, 1800])
chk("and presence goes out once it answers", len(said) == 1 and ns["announcing"] is True)

# /send goes to the addresses the node sends with the alert, read from its settings at that moment. The bridge's own
# RETICULUM_ALERT_DESTINATIONS is read when the container is created, so an address saved in Set up never got an
# alert (23 Nov 2026). An older node sends no "to", and then the bridge's own list is still used.
import io                                                   # noqa: E402
start = src.index("    def do_POST(self):")
end = src.index("\n\n\ndef announce_loop", start)
block = "class H:\n" + src[start:end]
send_block = block
def post_send(ns, to):
    """Run the real do_POST in `ns` with one /send body; return what it delivered to."""
    sent = []
    ns["deliver"] = lambda d, text, title: sent.append(d) or True
    exec(compile(send_block, "bridge-send", "exec"), ns)     # noqa: S102
    h = ns["H"]()
    payload = json.dumps({"text": "act alert", **to}).encode()
    h.path, h.headers, h.rfile = "/send", {"Content-Length": str(len(payload))}, io.BytesIO(payload)
    out = []
    h._json = lambda code, obj: out.append(obj)
    h.do_POST()
    return sent, out

for to, want in (({"to": [" AB12 ", "cd34", ""]}, ["ab12", "cd34"]), ({}, ["env1"]), ({"to": []}, [])):
    ns = {"json": json, "DESTS": ["env1"], "alert_to": [], "_save_alert_to": lambda to: None}
    sent, out = post_send(ns, to)
    chk(f"/send {to or 'with no to'} delivers to {want}", sent == want and out == [{"queued": len(want), "of": len(want)}])

# An `act` closes an alert and counts in ρ, which the node publishes. On a LAN or a tailnet only the household could
# send one; on a hub anyone who heard the address can (SPEC_hub §5 in planetai-node, 24 Nov 2026). So an act counts
# only from an address the node sends alerts to: RETICULUM_ALERT_DESTINATIONS, or the last `to` list /send was given.
# The real who-may-act block and on_message run here, with the node, the replies and RNS faked.
assert WHO in src, "reticulum_bridge.py has no who-may-act section: any sender on a hub can close this node's alerts"
act_block = src[src.index("ACT = re.compile"):].split("\n", 1)[0] + "\n\n" + lift(WHO, "\n\nrouter.register_delivery_callback")
posts, replies = [], []
class Resp:
    def raise_for_status(self): pass
fake_httpx = fake(post=staticmethod(lambda url, json, headers, timeout: posts.append(json) or Resp()))
fake_rns = fake(hexrep=staticmethod(lambda b, delimit=True: b.hex()), prettyhexrep=staticmethod(lambda b: f"<{b.hex()}>"))
d = tempfile.mkdtemp()
def bridge(dests):
    """A fresh container: the who-may-act block exec'd against DATA = d, as a restart would load it."""
    ns = {"os": os, "re": re, "json": json, "DATA": d, "DESTS": dests, "log": logging.getLogger("t"), "API": "http://app",
          "httpx": fake_httpx, "RNS": fake_rns, "reply": lambda h, text: replies.append((h.hex(), text))}
    exec(compile(act_block, "bridge-act", "exec"), ns)     # noqa: S102
    return ns
msg = lambda who, text: fake(content=text.encode(), source_hash=bytes.fromhex(who))

ns = bridge(["aa11"])
ns["on_message"](msg("aa11", "act 3 closed the windows"))
chk("an act from an alert address is recorded", [p["alert_id"] for p in posts] == [3])
ns["on_message"](msg("bb22", "act 4"))
chk("an act from a stranger records nothing", len(posts) == 1)
chk("and the stranger is told why, once", len(replies) == 2 and replies[-1][0] == "bb22" and "only from" in replies[-1][1])
ns["on_message"](msg("bb22", "act 5"))
chk("a stranger who keeps trying is not answered again", len(posts) == 1 and len(replies) == 2)
ns["on_message"](msg("bb22", "hello there"))
chk("a message that is not an act is left alone", len(posts) == 1 and len(replies) == 2)

post_send(ns, {"to": ["CC33", "aa11"]})
ns["on_message"](msg("cc33", "act 6"))
chk("an address the node sent an alert to may act", [p["alert_id"] for p in posts] == [3, 6])
ns2 = bridge([])
ns2["on_message"](msg("cc33", "act 7"))
chk("and still may after a restart", [p["alert_id"] for p in posts] == [3, 6, 7])
post_send(ns2, {"to": ["aa11"]})
ns2["on_message"](msg("cc33", "act 8"))
chk("an address taken out of Set up stops counting with the next alert", [p["alert_id"] for p in posts] == [3, 6, 7])
post_send(ns2, {})
ns2["on_message"](msg("aa11", "act 9"))
chk("an alert from an old node with no to list forgets nothing", [p["alert_id"] for p in posts] == [3, 6, 7, 9])
pathlib.Path(d, "alert_to.json").write_text("{ not json")
ns3 = bridge(["aa11"])
ns3["on_message"](msg("aa11", "act 10"))
chk("a corrupt list falls back to RETICULUM_ALERT_DESTINATIONS", [p["alert_id"] for p in posts][-1] == 10)

print("peers survive a restart, presence listens, and only the node's own people act" if not fails else f"{fails} failed")
raise SystemExit(1 if fails else 0)
