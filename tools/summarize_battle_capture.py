"""Print only message names/counts from a private Morimens 8443 capture.

Run from the parent workspace containing decode_morimens_passive.py. Never
print payloads: authentication frames contain live account credentials.
"""

import argparse
import collections
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import decode_morimens_passive as passive
import morimens_direct_facade_pilot as pilot
import sympy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture", type=Path)
    args = ap.parse_args()
    flows = passive.read_flows(args.capture, 8443)
    for segments in flows.values():
        c2s, cgap = passive.reassemble(segments["c2s"])
        s2c, sgap = passive.reassemble(segments["s2c"])
        ch = passive.route(c2s, True)
        sh = passive.route(s2c, False)
        if not ch or not sh or cgap or sgap:
            continue
        private = sympy.discrete_log(passive.protocol.DH_P, ch["public"], passive.protocol.DH_G)
        secret = passive.protocol.u64le(pow(sh["public"], private, passive.protocol.DH_P))
        key = passive.protocol.derive_rc4_key(secret)
        plain = passive.decoded_client_stream(c2s[ch["consumed"]:], key)
        counts = collections.Counter()
        frame_count = 0
        for frame in pilot.app_frames(plain):
            frame_count += 1
            try:
                _, blobs = pilot.packet_fields(frame)
                if blobs and re.fullmatch(rb"[A-Za-z][A-Za-z0-9]*\.[A-Za-z][A-Za-z0-9]*", blobs[0]):
                    counts[blobs[0].decode("ascii")] += 1
            except Exception:
                pass
        print("flow", "main" if ".operate-global-game." in ch["target"] else "gateway",
              "client_frames", frame_count, "server_bytes", len(s2c),
              "method_counts", sorted(counts.items()))


if __name__ == "__main__":
    main()
