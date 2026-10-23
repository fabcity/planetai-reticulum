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
block = lift("def announce_presence", "\n\ndef on_message") + "\n\n" + lift("def announce_loop", "\n\nthreading.Thread")

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

print("peers survive a restart, and presence listens" if not fails else f"{fails} failed")
raise SystemExit(1 if fails else 0)
