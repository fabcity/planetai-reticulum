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
import time

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
loop_block = lift("said = None", "\n\n" + WHO) + "\n\n" + lift("def announce_loop", "\n\nthreading.Thread")

class Stop(BaseException): pass
fake = lambda **kw: type("F", (), kw)
def run_loop(answers):
    """The real announce_presence and announce_loop for half an hour, against a node that answers GET /presence with
    the body of the last (second, body) in answers whose second has come (None: not up yet). Returns the namespace,
    every announce as (seconds since start, body), and every body a path answer was set to carry (None: nothing)."""
    clock, said, defaults = [0], [], []
    def get(url, timeout):
        a = [b for t, b in answers if t <= clock[0]][-1]
        if a is None:
            raise ConnectionError("app not up yet")
        return type("R", (), {"json": lambda self: a})()
    def sleep(s):
        clock[0] += s
        if clock[0] >= 1800:                                # the next full announce is the next half hour's
            raise Stop
    ns = {"httpx": fake(get=staticmethod(get)), "time": fake(sleep=staticmethod(sleep)), "json": json,
          "API": "http://app", "ANNOUNCE_S": 1800, "announcing": False, "log": logging.getLogger("t"),
          "router": fake(announce=staticmethod(lambda h: None)), "me": fake(hash=b"x"),
          "PRESENCE": fake(announce=staticmethod(lambda app_data: said.append((clock[0], json.loads(app_data)))),
                           set_default_app_data=staticmethod(lambda d: defaults.append(d and json.loads(d))))}
    exec(compile(loop_block, "bridge-announce", "exec"), ns)  # noqa: S102
    try:
        ns["announce_loop"]()
    except Stop:
        pass
    return ns, said, defaults

ME = {"enabled": True, "node": "dieznode", "cell": "838db5fffffffff", "res": 3, "id": "lfzfhebv76r45tfr", "lat": -8.8}
SAY = {k: ME[k] for k in ("node", "cell", "res", "id")}
OFF = {"enabled": False}
ns, said, defaults = run_loop([(0, None), (60, ME)])
chk(f"a node not up yet is asked again soon (announced at {[t for t, _ in said]} s)", said and said[0][0] == 60)
chk("and presence goes out once it answers, and once only while it says the same",
    len(said) == 1 and ns["announcing"] is True)
chk("with the node's id, so a heard node can be matched to a listed one", said[0][1] == SAY)
chk("and a node asking for its path hears the same body, not an empty announce", defaults == [SAY])

# `planetai update` can start this container while the old app still answers (its version, and before planetai-node
# #425 no id), or replace the app and leave this container running. Either way that body went out and stayed for
# RETICULUM_ANNOUNCE_S (node #1, 25 Nov 2026, both seen the same morning).
OLD = {"enabled": True, "node": "dieznode", "cell": "838db5fffffffff", "res": 3, "version": "v0.92.0"}
NEW = dict(ME, version="v0.93.0")
SAY_OLD, SAY_NEW = {k: OLD[k] for k in ("node", "cell", "res", "version")}, dict(SAY, version="v0.93.0")
ns, said, defaults = run_loop([(0, OLD), (1, NEW)])
chk(f"the new app's body goes out a minute after the old one's, not half an hour (said {said})",
    said == [(0, SAY_OLD), (60, SAY_NEW)])
chk("and a path answer carries the newest body", defaults[-1] == SAY_NEW)
ns, said, defaults = run_loop([(0, OLD), (1200, NEW)])
chk(f"an app replaced twenty minutes into a run is said within a minute too (said at {[t for t, _ in said]} s)",
    said == [(0, SAY_OLD), (1200, SAY_NEW)])
ns, said, defaults = run_loop([(0, ME), (1, OFF)])
chk("turned off, a path answer carries nothing either", defaults[-1] is None and ns["announcing"] is False and len(said) == 1)
ns, said, defaults = run_loop([(0, ME), (1, OFF), (61, ME)])
chk("and turned on again, the same body goes out again", [b for _, b in said] == [SAY, SAY] and defaults[-1] == SAY)

# The receiving half keeps the id too (SPEC_hub §7 in planetai-node). The real handler runs with RNS faked.
block = lift("class PresenceHandler", "\n\nRNS.Transport.register_announce_handler")
ns = {"json": json, "time": time, "threading": threading, "log": logging.getLogger("t"), "heard": {},
      "heard_lock": threading.Lock(), "HEARD_MAX": 200, "_save_heard": lambda: None,
      "RNS": fake(hexrep=staticmethod(lambda b, delimit=True: b.hex())), "PRESENCE": fake(hash=b"\x00")}
exec(compile(block, "bridge-presence", "exec"), ns)        # noqa: S102
hp = ns["PresenceHandler"]()
hp.received_announce(b"\xab\x12", None, b'{"node":"mahon1","cell":"831e5ffffffffff","res":3,"id":"k4xq2"}')
hp.received_announce(b"\xcd\x34", None, b'{"node":"old-node","cell":"831e5ffffffffff","res":3}')
chk("a heard node keeps its id", ns["heard"]["ab12"]["id"] == "k4xq2")
chk("and one from an older node has none, so it is matched by name", ns["heard"]["cd34"]["id"] is None)

# /health lists the interfaces the node opened and whether each is up, so a node that hears nobody can tell whether
# its hub is down. A hub's server gives a count of the nodes on it, not one row each.
block = lift("def interfaces()", "\n\nclass H(")
class Server:
    name, online, parent_interface = "TCP Server", True, None
    @property
    def clients(self): return 2
Client = lambda n: fake(name=n, online=True, parent_interface=Server())
Pipe = lambda up: type("PipeInterface", (), {"name": "Fab City hub", "online": up, "parent_interface": None})()
for up in (True, False):
    ns = {"RNS": fake(Transport=fake(interfaces=[Server(), Client("Client on TCP Server"), Pipe(up)]))}
    exec(compile(block, "bridge-interfaces", "exec"), ns)  # noqa: S102
    rows = ns["interfaces"]()
    chk(f"/health says the hub is {'up' if up else 'down'}",
        rows == [{"name": "TCP Server", "type": "Server", "online": True, "clients": 2},
                 {"name": "Fab City hub", "type": "PipeInterface", "online": up}])

# config.tpl carries the hub block commented, word for word what `planetai reticulum` writes when a household says yes
tpl = pathlib.Path(__file__).resolve().parent.parent.joinpath("config.tpl").read_text()
chk("config.tpl has the hub block, commented", "  # [[Fab City hub]]\n  #   type = PipeInterface\n" in tpl)
# -servername only sends the name; without -verify_hostname any trusted certificate passes (CodeRabbit on #2)
chk("and it checks that the certificate is the hub's, by name", "openssl s_client -quiet -verify_return_error -verify_hostname fabalabbali.tail71245c.ts.net -connect fabalabbali.tail71245c.ts.net:443 -servername fabalabbali.tail71245c.ts.net" in tpl)
chk("transport stays off for a node that is not a hub", re.search(r"(?m)^  enable_transport = No\b", tpl) is not None)

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

for to, want in (({"to": [" AB12 ", "cd 34", ""]}, ["ab12", "cd34"]), ({}, ["env1"]), ({"to": []}, [])):
    ns = {"json": json, "DESTS": ["env1"], "alert_to": [], "_save_alert_to": lambda to: True}
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
    ns = {"os": os, "re": re, "json": json, "time": time, "threading": threading, "DATA": d, "DESTS": dests,
          "log": logging.getLogger("t"), "API": "http://app",
          "httpx": fake_httpx, "RNS": fake_rns, "reply": lambda h, text: replies.append((h.hex(), text))}
    exec(compile(act_block, "bridge-act", "exec"), ns)     # noqa: S102
    return ns
msg = lambda who, text, signed=True: fake(content=text.encode(), source_hash=bytes.fromhex(who),
                                         signature_validated=signed, unverified_reason=None if signed else 0x02)

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
# LXMF 1.1.1 delivers a message whose signature failed, so a forger can put an alert address in source_hash
ns["on_message"](msg("aa11", "act 4", signed=False))
chk("an act that only claims an alert address records nothing, and gets no reply", len(posts) == 1 and len(replies) == 2)

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

# A list that cannot be written is not taken up either, so memory never runs ahead of the file: a restart cannot bring
# back an address memory had dropped, and the next alert tries the write again.
good = ns3["ALERT_TO_FILE"]
post_send(ns3, {"to": ["dd44"]})
ns3["ALERT_TO_FILE"] = os.path.join(d, "missing", "alert_to.json")
post_send(ns3, {"to": []})
chk("a list that cannot be saved is not taken up", ns3["alert_to"] == ["dd44"])
ns3["ALERT_TO_FILE"] = good
post_send(ns3, {"to": []})
ns4 = bridge(["aa11"])
ns4["on_message"](msg("dd44", "act 11"))
chk("the next alert saves it, and a restart keeps the address out", ns3["alert_to"] == [] and posts[-1]["alert_id"] == 10)

# hello: the programme's inbox (SPEC_hub §9 in planetai-node). An entry with only the fields `planetai hello` writes, from
# a signed sender, is kept, one per sender and at most INBOX_MAX, and answered; anything else is not kept. Same block as
# the act tests above, so the inbox lives in that DATA and a restart is a fresh exec.
d = tempfile.mkdtemp()
entry = {"name": "mahon1", "place": "Mahon, Menorca, ES", "cell": "8839a1b2c3fffff", "lat": 39.889, "lon": 4.265,
         "scale": "community", "operator": "Lucas", "sources": ["smartcitizen"], "since": "2026-11", "parent": None,
         "id": "cc5gqlek2e2rhfy6", "key": "0EqyMnQrtKs6E2i9RhXk5tAiSrcaAWuvhSCjMsl3hzc="}
replies.clear()
hb = bridge([])
hb["on_message"](msg("ee55", "hello " + json.dumps(entry)))
chk("a hello from a signed sender is kept", hb["inbox"].get("ee55", {}).get("entry") == entry)
chk("and answered", replies[-1] == ("ee55", "received: a person reads it before it is listed"))
hb["on_message"](msg("ee55", "hello " + json.dumps(dict(entry, place="Mahón"))))
chk("one entry per sender, the newest", len(hb["inbox"]) == 1 and hb["inbox"]["ee55"]["entry"]["place"] == "Mahón")
hb["on_message"](msg("ff66", "hello " + json.dumps(dict(entry, name="x", lat=1)), signed=False))
chk("an unsigned hello is not kept, and not answered", "ff66" not in hb["inbox"] and replies[-1][0] == "ee55")
n = len(replies)
hb["on_message"](msg("ab77", "hello " + json.dumps(dict(entry, readings=[1, 2]))))
hb["on_message"](msg("ab77", "hello {not json"))
chk("a hello with a field planetai hello does not write is not kept, and told so once",
    "ab77" not in hb["inbox"] and len(replies) == n + 1 and replies[-1] == ("ab77", "not kept: hello takes the entry planetai hello writes, and nothing else"))
hb["on_message"](msg("cd88", "hello there"))
chk("a greeting is not a hello", "cd88" not in hb["inbox"] and len(replies) == n + 1)
hb2 = bridge([])
chk("the inbox survives a restart", hb2["inbox"].get("ee55", {}).get("entry", {}).get("place") == "Mahón")
hb2["INBOX_MAX"], t0 = 2, hb2["inbox"]["ee55"]["at"]
for who, t in (("a1", 1), ("a2", 2)):
    hb2["on_message"](msg(who, "hello " + json.dumps(dict(entry, name=who))))
    hb2["inbox"][who]["at"] = t0 + t
chk("at most INBOX_MAX, the oldest out first", sorted(hb2["inbox"]) == ["a1", "a2"])

# GET /inbox lists them, newest first; POST /hello sends this node's entry and returns what the inbox said, and never
# touches who may act (it is not /send)
def handler(ns, method, path, body=None):
    exec(compile("class H:\n" + src[src.index("    def do_GET(self):"):src.index("\n\n\ndef announce_loop")], "bridge-http", "exec"), ns)  # noqa: S102
    h, out = ns["H"](), []
    payload = json.dumps(body or {}).encode()
    h.path, h.headers, h.rfile = path, {"Content-Length": str(len(payload))}, io.BytesIO(payload)
    h._json = lambda code, obj: out.append((code, obj))
    getattr(h, "do_" + method)()
    return out[0]
code, got = handler(hb2, "GET", "/inbox")
chk("GET /inbox lists what arrived, newest first", code == 200 and [r["from"] for r in got["inbox"]] == ["a2", "a1"])
hb2["HELLO_WAIT_S"], hb2["alert_to"][:] = 1, ["aa11"]
# the inbox's answer comes back as a message, through on_message, a moment after the hello goes out
hb2["deliver"] = lambda to, text, title: threading.Timer(0.2, lambda: hb2["on_message"](
    msg(to, "received: a person reads it before it is listed"))).start() or text.startswith("hello {")
code, got = handler(hb2, "POST", "/hello", {"inbox": " 1B4F 7640 ", "entry": entry})
hb2["on_message"](msg("1b4f7640", "a late answer, after the wait"))
chk("POST /hello sends the entry and returns the inbox's answer",
    code == 200 and got == {"sent": True, "answer": "received: a person reads it before it is listed"})
chk("and leaves who may act as it was, keeping no answer once it stops waiting",
    hb2["alert_to"] == ["aa11"] and not hb2["waiting"] and not hb2["answers"])
hb2["deliver"] = lambda to, text, title: True
code, got = handler(hb2, "POST", "/hello", {"inbox": "1b4f", "entry": entry})
chk("an inbox that does not answer in time is said so", got == {"sent": True, "answer": None})
code, got = handler(hb2, "POST", "/hello", {"inbox": "1b4f", "entry": dict(entry, readings=[1])})
chk("and an entry planetai hello would not write is not sent", code == 400)

print("peers survive a restart, presence listens, the hub shows, the inbox keeps hellos, and only the node's own people act" if not fails else f"{fails} failed")
raise SystemExit(1 if fails else 0)
