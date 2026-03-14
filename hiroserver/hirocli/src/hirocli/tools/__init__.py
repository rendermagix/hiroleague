from .base import Tool
from .channel import (
    ChannelDisableTool,
    ChannelEnableTool,
    ChannelInstallTool,
    ChannelListTool,
    ChannelRemoveTool,
    ChannelSetupTool,
)
from .device import DeviceAddTool, DeviceListTool, DeviceRevokeTool
from .gateway import (
    GatewaySetupTool,
    GatewayStartTool,
    GatewayStatusTool,
    GatewayStopTool,
    GatewayTeardownTool,
)
from .server import (
    RestartTool,
    SetupTool,
    StartTool,
    StatusTool,
    StopTool,
    TeardownTool,
    UninstallTool,
)
from .workspace import (
    WorkspaceCreateTool,
    WorkspaceListTool,
    WorkspaceRemoveTool,
    WorkspaceShowTool,
    WorkspaceUpdateTool,
)


def all_tools() -> list[Tool]:
    """Return one fresh instance of every registered tool."""
    return [
        DeviceAddTool(),
        DeviceListTool(),
        DeviceRevokeTool(),
        ChannelListTool(),
        ChannelInstallTool(),
        ChannelSetupTool(),
        ChannelEnableTool(),
        ChannelDisableTool(),
        ChannelRemoveTool(),
        WorkspaceListTool(),
        WorkspaceCreateTool(),
        WorkspaceRemoveTool(),
        WorkspaceUpdateTool(),
        WorkspaceShowTool(),
        SetupTool(),
        StartTool(),
        StopTool(),
        RestartTool(),
        StatusTool(),
        TeardownTool(),
        UninstallTool(),
        GatewayStatusTool(),
        GatewayStartTool(),
        GatewayStopTool(),
        GatewaySetupTool(),
        GatewayTeardownTool(),
    ]
