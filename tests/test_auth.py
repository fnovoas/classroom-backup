import socket
import unittest

from src import auth


class OAuthPortSelectionTests(unittest.TestCase):
    def test_prefers_requested_port_when_available(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        self.assertEqual(auth._select_port(port), port)

    def test_falls_back_to_ephemeral_port_when_requested_port_is_busy(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy_sock:
            busy_sock.bind(("127.0.0.1", 0))
            port = busy_sock.getsockname()[1]
            self.assertEqual(auth._select_port(port), 0)


if __name__ == "__main__":
    unittest.main()
