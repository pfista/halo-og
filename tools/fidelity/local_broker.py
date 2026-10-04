"""Temporary loopback-only MQTT 3.1.1 subset for Halo's encrypted signalling.

Supports the exact QoS 0 CONNECT/SUBSCRIBE/PUBLISH/PING/UNSUBSCRIBE messages
used by p2p_signal.c. It makes no outbound connections and never persists topics,
session keys or payloads. This is a test fixture, not a general MQTT service.
"""
import selectors
import socket
import threading


def packet(kind, body):
    remaining, encoded = len(body), bytearray([kind])
    while True:
        value = remaining % 128
        remaining //= 128
        encoded.append(value | (128 if remaining else 0))
        if not remaining:
            return bytes(encoded) + body


def take_packet(buffer):
    if len(buffer) < 2:
        return None
    remaining, shift = 0, 0
    for index in range(1, 5):
        if index >= len(buffer):
            return None
        value = buffer[index]
        remaining |= (value & 127) << shift
        if remaining > 65536:
            raise ValueError("Oversized signalling packet")
        if not value & 128:
            end = index + 1 + remaining
            if len(buffer) < end:
                return None
            result = buffer[0], bytes(buffer[index + 1:end])
            del buffer[:end]
            return result
        shift += 7
    raise ValueError("Invalid MQTT length")


class LocalBroker:
    def __init__(self):
        self.selector = selectors.DefaultSelector()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(4)
        self.listener.setblocking(False)
        self.port = self.listener.getsockname()[1]
        self.selector.register(self.listener, selectors.EVENT_READ, None)
        self.clients = {}
        self.stats = {"connections": 0, "publications": 0, "deliveries": 0, "errors": 0}
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._run, name="halo-fidelity-local-signal", daemon=True)
        self.thread.start()

    def close(self):
        self.stopped.set()
        self.thread.join(2)
        for client in list(self.clients):
            self._drop(client)
        self.listener.close()
        self.selector.close()

    def _drop(self, client):
        self.selector.unregister(client)
        self.clients.pop(client)
        client.close()

    def _send(self, client, kind, body):
        self.clients[client]["out"].extend(packet(kind, body))
        self.selector.modify(client, selectors.EVENT_READ | selectors.EVENT_WRITE, True)

    def _message(self, client, kind, body):
        if kind == 0x10:
            if not body.startswith(b"\x00\x04MQTT\x04\x02"):
                raise ValueError("Unsupported MQTT connection")
            self._send(client, 0x20, b"\x00\x00")
        elif kind in (0x82, 0xA2):
            if len(body) < 4:
                raise ValueError("Truncated subscription")
            index, count = 2, 0
            while index < len(body):
                length = int.from_bytes(body[index:index + 2], "big")
                end = index + 2 + length
                if length == 0 or end > len(body):
                    raise ValueError("Invalid topic")
                topic = body[index + 2:end]
                if kind == 0x82:
                    if end >= len(body) or body[end] != 0:
                        raise ValueError("Only QoS 0 is supported")
                    self.clients[client]["topics"].add(topic)
                    index = end + 1
                else:
                    self.clients[client]["topics"].discard(topic)
                    index = end
                count += 1
            self._send(client, 0x90 if kind == 0x82 else 0xB0,
                       body[:2] + (bytes(count) if kind == 0x82 else b""))
        elif kind == 0x30:
            if len(body) < 2:
                raise ValueError("Truncated publication")
            length = int.from_bytes(body[:2], "big")
            if not length or length + 2 > len(body):
                raise ValueError("Invalid publication topic")
            topic = body[2:2 + length]
            self.stats["publications"] += 1
            for recipient, state in self.clients.items():
                if topic in state["topics"]:
                    self._send(recipient, 0x30, body)
                    self.stats["deliveries"] += 1
        elif kind == 0xC0 and not body:
            self._send(client, 0xD0, b"")
        elif kind == 0xE0 and not body:
            self._drop(client)
        else:
            raise ValueError("Unsupported MQTT message")

    def _run(self):
        while not self.stopped.is_set():
            for key, events in self.selector.select(0.1):
                client = key.fileobj
                if client is self.listener:
                    connection, _ = self.listener.accept()
                    if len(self.clients) >= 4:
                        connection.close()
                        continue
                    connection.setblocking(False)
                    self.clients[connection] = {"in": bytearray(), "out": bytearray(), "topics": set()}
                    self.selector.register(connection, selectors.EVENT_READ, True)
                    self.stats["connections"] += 1
                    continue
                try:
                    state = self.clients[client]
                    if events & selectors.EVENT_READ:
                        data = client.recv(8192)
                        if not data:
                            self._drop(client)
                            continue
                        state["in"].extend(data)
                        while client in self.clients:
                            message = take_packet(state["in"])
                            if message is None:
                                break
                            self._message(client, *message)
                    if client in self.clients and events & selectors.EVENT_WRITE:
                        count = client.send(state["out"])
                        del state["out"][:count]
                        if not state["out"]:
                            self.selector.modify(client, selectors.EVENT_READ, True)
                except (OSError, ValueError):
                    self.stats["errors"] += 1
                    if client in self.clients:
                        self._drop(client)
