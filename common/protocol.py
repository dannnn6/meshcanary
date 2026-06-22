"""
Wire protocol: length-prefixed JSON messages over TCP.
Simple and debuggable — fine for the volume of data a status-gossip
network like this needs to move.
"""
import struct
import json


def recv_exact(sock, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed before expected bytes arrived")
        buf += chunk
    return buf


def send_json(sock, obj) -> None:
    data = json.dumps(obj).encode()
    sock.sendall(struct.pack("!I", len(data)) + data)


def recv_json(sock, max_len: int = 10_000_000):
    length = struct.unpack("!I", recv_exact(sock, 4))[0]
    if length > max_len:
        raise ValueError(f"message too large: {length} bytes")
    data = recv_exact(sock, length)
    return json.loads(data.decode())
