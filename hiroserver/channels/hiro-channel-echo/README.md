# hiro-channel-echo

Echo channel plugin for Hiro — for development and integration testing.

Any outbound message sent to this channel is immediately reflected back as an inbound
message, prefixed with `[echo]`. Use it to verify the full plugin pipeline is working.

## Usage

```bash
# Install within the uv workspace (dev)
uv sync

# Register with hirocli
hirocli channel setup echo

# Run manually (hirocli starts it automatically on hirocli start)
hiro-channel-echo --hiro-ws ws://127.0.0.1:18081
```
