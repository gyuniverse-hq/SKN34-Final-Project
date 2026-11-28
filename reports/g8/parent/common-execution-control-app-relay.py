"""Temporary local WSL TCP bridge; forwards bytes without logging credentials."""
import select
import socket
import threading


def forward(client):
    with client, socket.create_connection(("127.0.0.1", 15441)) as upstream:
        while True:
            ready, _, _ = select.select([client, upstream], [], [], 120)
            if not ready:
                return
            for source in ready:
                data = source.recv(65536)
                if not data:
                    return
                (upstream if source is client else client).sendall(data)


if __name__ == "__main__":
    import sys
    with socket.socket() as server:
        server.bind((sys.argv[1], 19841))
        server.listen()
        print("Local G5 bridge ready", flush=True)
        while True:
            client, _ = server.accept()
            threading.Thread(target=forward, args=(client,), daemon=True).start()
