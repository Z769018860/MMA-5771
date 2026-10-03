"""Store a short PCAPdroid UDP export as a local PCAP (sensitive, do not commit)."""

import argparse
import socket
import struct
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 5123))
    sock.settimeout(1)
    count = 0
    with open(args.output, "wb") as out:
        out.write(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 101))
        end = time.monotonic() + args.seconds
        print("READY", flush=True)
        while time.monotonic() < end:
            try:
                data, _ = sock.recvfrom(65535)
            except socket.timeout:
                continue
            # PCAPdroid UDP exporter datagrams contain the original IP packet.
            if not data or data[0] >> 4 not in (4, 6):
                continue
            now = time.time()
            sec = int(now)
            usec = int((now - sec) * 1_000_000)
            out.write(struct.pack("<IIII", sec, usec, len(data), len(data)))
            out.write(data)
            count += 1
    print("PACKETS", count, flush=True)


if __name__ == "__main__":
    main()
