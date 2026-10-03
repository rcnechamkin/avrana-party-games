"""core.ws_limit — a bound on what the server will hold for one WebSocket that is not reading.

Nothing in this application queues outbound messages: `ws.send_text` hands the frame to uvicorn,
which hands it to the asyncio transport and returns. uvicorn's WebSocket protocol (0.51.0,
`websockets_sansio_impl`, the one `ws="auto"` selects when `websockets` is installed, on the Pi
too) has no write flow control: its `writable` event is never cleared. So a send never blocks,
and a room is never stalled by a slow socket, but whatever the peer does not read piles up in the
transport's buffer without limit. The only thing that ever stopped it was the keepalive ping
(20 s + 20 s), and a peer that is merely slow keeps answering pings.

Here the transport's own high-water mark is set to MAX_OUTBOUND_BACKLOG, and reaching it drops
the connection. asyncio calls `pause_writing()` exactly when the buffered bytes exceed the mark,
so there is no polling and no per-send cost. Behind nginx the kernel's loopback buffers and
nginx's own fill first, so a socket that reaches the mark is already megabytes behind.

Dropping is the right policy for this protocol: every push carries the whole state, so a client
that reconnects (web/hubnet.js does, with a fresh Party ticket when it has one) is current after
one frame. Nothing it missed needs replaying.

AVR-217.
"""

from __future__ import annotations

import logging

from uvicorn.protocols.websockets.websockets_sansio_impl import WebSocketsSansIOProtocol

from core.events import event

log = logging.getLogger("gamehub.net")

# Bytes held in the server process for one socket before it is dropped. A state push is a few
# kilobytes; the largest burst a healthy client is ever sent is well under 100 KiB.
MAX_OUTBOUND_BACKLOG = 1024 * 1024


class BoundedWebSocketProtocol(WebSocketsSansIOProtocol):
    """uvicorn's WebSocket protocol, with a hard limit on unread outbound bytes."""

    def connection_made(self, transport):
        super().connection_made(transport)
        transport.set_write_buffer_limits(high=MAX_OUTBOUND_BACKLOG)

    def pause_writing(self):
        # The peer is at least MAX_OUTBOUND_BACKLOG behind. abort() discards the buffer and closes
        # at once; connection_lost() then delivers `websocket.disconnect` to the application, whose
        # receive loop reaps the socket exactly as for any other disconnect.
        path = getattr(self, "scope", None) and self.scope.get("path") or ""
        parts = path.strip("/").split("/")
        game = parts[1] if len(parts) > 1 and parts[0] == "games" else (parts[0] or "-")
        event(game, "slow_socket_dropped", backlog=self.transport.get_write_buffer_size(),
              limit=MAX_OUTBOUND_BACKLOG)
        self.transport.abort()
