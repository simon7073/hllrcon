"""RCONv2 protocol constants."""

from typing import Final

# Header format: magic (4 bytes LE) + request_id (4 bytes LE) + payload_len (4 bytes LE)
REQUEST_HEADER_FORMAT: Final[str] = "<III"
RESPONSE_HEADER_FORMAT: Final[str] = "<III"

# Magic value used to identify RCONv2 packets (little-endian)
MAGIC_HEADER_VALUE: Final[int] = 0xDE450508
MAGIC_HEADER_BYTES: Final[bytes] = MAGIC_HEADER_VALUE.to_bytes(4, "little")

# Header size in bytes
HEADER_SIZE: Final[int] = 12

# Maximum allowed payload size to prevent memory exhaustion attacks.
# The RCON protocol does not natively define a max size; this is a defensive
# ceiling (16 MiB) chosen to accommodate large responses (e.g. full player
# lists or long log buffers) while still bounding allocation.
MAX_PAYLOAD_SIZE: Final[int] = 16 * 1024 * 1024

# Default timeouts (seconds)
DEFAULT_CONNECT_TIMEOUT: Final[float] = 15.0
DEFAULT_REQUEST_TIMEOUT: Final[float] = 10.0

# Heartbeat / keepalive defaults (seconds)
DEFAULT_HEARTBEAT_INTERVAL: Final[float] = 30.0
DEFAULT_HEARTBEAT_TIMEOUT: Final[float] = 10.0
