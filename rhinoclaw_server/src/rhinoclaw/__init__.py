"""Rhino integration through the Model Context Protocol."""

__version__ = "0.1.3.9"

# Expose key classes and functions for easier imports
from .prompts.assert_general_strategy import asset_general_strategy
from .server import RhinoConnection, get_rhino_connection, logger, mcp
from .static.rhinoscriptsyntax import rhinoscriptsyntax_json
from .tools.array_linear import array_linear
from .tools.array_polar import array_polar
from .tools.assign_material_to_layer import assign_material_to_layer
from .tools.boolean_operation import boolean_operation
from .tools.chamfer_curves import chamfer_curves
from .tools.copy_object import copy_object
from .tools.create_angular_dimension import create_angular_dimension
from .tools.create_layer import create_layer
from .tools.create_leader import create_leader
from .tools.create_linear_dimension import create_linear_dimension
from .tools.create_material import create_material
from .tools.create_object import create_object
from .tools.create_objects import create_objects
from .tools.create_radial_dimension import create_radial_dimension
from .tools.create_text import create_text
from .tools.create_text_dot import create_text_dot
from .tools.delete_layer import delete_layer
from .tools.delete_object import delete_object
from .tools.execute_rhinoscript_python_code import execute_rhinoscript_python_code
from .tools.export_file import export_file
from .tools.extrude_curve import extrude_curve
from .tools.fillet_curves import fillet_curves
from .tools.get_document_info import get_document_info
from .tools.get_logs import clear_logs, get_logs
from .tools.get_object_info import get_object_info

# Object Properties
from .tools.get_object_properties import get_object_properties
from .tools.get_or_set_current_layer import get_or_set_current_layer
from .tools.get_rhinoscript_python_code_guide import get_rhinoscript_python_code_guide
from .tools.get_rhinoscript_python_function_names import (
    get_rhinoscript_python_function_names,
)
from .tools.get_selected_objects_info import get_selected_objects_info
from .tools.loft_curves import loft_curves
from .tools.log_thought import log_thought
from .tools.mirror_object import mirror_object
from .tools.modify_object import modify_object
from .tools.modify_objects import modify_objects
from .tools.offset_curve import offset_curve

# File Operations
from .tools.open_file import open_file
from .tools.ping import ping
from .tools.revolve_curve import revolve_curve
from .tools.save_file import save_file
from .tools.select_objects import select_objects
from .tools.set_debug_mode import set_debug_mode
from .tools.set_object_properties import set_object_properties
from .tools.set_render_settings import set_render_settings
from .tools.set_view import set_view
from .tools.set_camera import set_camera
from .tools.orbit_camera import orbit_camera
from .tools.zoom_extents import zoom_extents
from .tools.zoom_selected import zoom_selected
from .tools.capture_viewport import capture_viewport
from .tools.render_view import render_view
from .tools.add_light import add_light
from .tools.create_block import create_block
from .tools.create_group import create_group
from .tools.explode_block import explode_block
from .tools.insert_block import insert_block
from .tools.ungroup import ungroup

# Grasshopper Operations
from .tools.run_grasshopper import run_grasshopper
from .tools.grasshopper_interactive import (
    run_door_script,
    run_grasshopper_interactive,
)

# WebSocket Streaming (Real-Time Events)
from .tools.stream_commands import (
    cancel_rhino_command,
    clear_stream_buffer,
    connect_rhino_stream,
    disconnect_rhino_stream,
    get_stream_events,
    get_stream_status,
    run_script_async,
    send_rhino_input,
    wait_for_prompt,
)

# WebSocket Client
from .websocket_client import (
    RhinoWebSocketClient,
    WebSocketEvent,
    get_websocket_client,
    reset_websocket_client,
)
