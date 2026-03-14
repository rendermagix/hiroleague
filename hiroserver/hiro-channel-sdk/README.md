# hiro-channel-sdk

Shared SDK and contract for Hiro channel plugins.

## Overview

Every channel plugin (Telegram, WhatsApp, mobile app, etc.) is a standalone Python
package that implements `ChannelPlugin` and communicates with `hirocli` over a local
WebSocket using JSON-RPC 2.0.

This package provides:

| Module | Purpose |
|---|---|
| `models.py` | `UnifiedMessage`, `RpcRequest`, `RpcResponse`, `ChannelInfo` |
| `base.py` | `ChannelPlugin` abstract base class |
| `rpc.py` | JSON-RPC 2.0 helpers (build / parse) |
| `transport.py` | `PluginTransport` — WS client that connects to hirocli |

## Writing a channel plugin

```python
from hiro_channel_sdk import ChannelPlugin, ChannelInfo, UnifiedMessage, PluginTransport
import asyncio

class MyChannel(ChannelPlugin):
    @property
    def info(self) -> ChannelInfo:
        return ChannelInfo(name="mychannel", version="0.1.0")

    async def on_configure(self, config):
        self.api_key = config.get("api_key", "")

    async def on_start(self):
        # start polling / webhooks
        asyncio.create_task(self._poll())

    async def on_stop(self):
        pass  # cancel polling tasks here

    async def send(self, message: UnifiedMessage) -> None:
        # translate and send via third-party API
        pass

    async def _poll(self):
        while True:
            # receive message from third party...
            msg = UnifiedMessage(
                channel=self.info.name,
                direction="inbound",
                sender_id="user123",
                body="Hello!",
            )
            await self.emit(msg)
            await asyncio.sleep(1)

# Entry point
if __name__ == "__main__":
    import typer

    def main(hiro_ws: str = "ws://127.0.0.1:18081"):
        plugin = MyChannel()
        transport = PluginTransport(plugin, hiro_ws)
        asyncio.run(transport.run())

    typer.run(main)
```

## JSON-RPC protocol

| Direction | Method | Params | Notes |
|---|---|---|---|
| plugin → hirocli | `channel.register` | `{name, version, description}` | First frame after connect |
| plugin → hirocli | `channel.receive` | `UnifiedMessage` dict | Inbound message from third party |
| plugin → hirocli | `channel.event` | `{event, data}` | Status, errors, receipts |
| hirocli → plugin | `channel.send` | `UnifiedMessage` dict | Send outbound message |
| hirocli → plugin | `channel.configure` | `{config: {...}}` | Push credentials |
| hirocli → plugin | `channel.status` | — | Health probe |
| hirocli → plugin | `channel.stop` | — | Graceful shutdown |
