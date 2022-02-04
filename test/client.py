import socket, json

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
    client.connect(("localhost", 9870))
    client.sendall(
        bytes(
            json.dumps(
                {
                    "id": 114514,
                    "method": "getFileInfo",
                    "params": {"path": ".prettierrc.json"},
                }
            ),
            "utf-8",
        )
    )
    client.shutdown(socket.SHUT_WR)  # trigger node's 'end' message
    data = b""
    while True:
        chunk = client.recv(512)
        if chunk:
            data += chunk
        else:
            break

print("received", data.decode("utf-8"))
