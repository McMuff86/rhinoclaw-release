"""Rhino integration through the Model Context Protocol."""

__version__ = "0.7.2"

# Expose key classes and functions for easier imports
from .prompts.assert_general_strategy import asset_general_strategy
from .server import RhinoConnection, get_rhino_connection, logger, mcp
from .static.rhinoscriptsyntax import rhinoscriptsyntax_json
from .tools.array_linear import array_linear
from .tools.array_polar import array_polar
from .tools.assign_material_to_layer import assign_material_to_layer
from .tools.batch_operations import batch_operations
from .tools.boolean_operation import boolean_operation
from .tools.build_and_bake_gh import build_and_bake_gh
from .tools.build_and_bake_recipe import build_and_bake_recipe
from .tools.build_gh_definition import build_gh_definition
from .tools.build_gh_interactive import build_gh_interactive
from .tools.chamfer_curves import chamfer_curves
from .tools.check_setup import rhinoclaw_doctor
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
from .tools.deploy_gh_to_compute import deploy_gh_to_compute
from .tools.erp_bridge import erp_invoke, erp_list_tools
from .tools.execute_python3_code import execute_python3_code, get_script_capabilities
from .tools.execute_rhinoscript_python_code import execute_rhinoscript_python_code
from .tools.export_file import export_file
from .tools.export_mesh import export_mesh
from .tools.extrude_curve import extrude_curve
from .tools.fillet_curves import fillet_curves
from .tools.find_gh_component import find_gh_component
from .tools.find_nearby import find_nearby
from .tools.find_objects import find_objects
from .tools.get_auth_status import get_auth_status
from .tools.get_command_history import get_command_history
from .tools.hello import hello
from .tools.get_document_info import get_document_info
from .tools.judge_door_placement import judge_door_placement
from .tools.get_logs import clear_logs, get_logs
from .tools.get_object_info import get_object_info
from .tools.get_objects_info import get_objects_info
from .tools.get_relationships import get_relationships

# Object Properties
from .tools.get_object_properties import get_object_properties
from .tools.get_or_set_current_layer import get_or_set_current_layer
from .tools.get_rhinoscript_python_code_guide import get_rhinoscript_python_code_guide
from .tools.get_rhinoscript_python_function_names import (
    get_rhinoscript_python_function_names,
)
from .tools.get_selected_objects_info import get_selected_objects_info
from .tools.get_session_stats import get_session_stats, new_session, set_logging_enabled
from .tools.get_ui_state import get_ui_state, wait_until_ready
from .tools.import_mesh import import_mesh
from .tools.loft_curves import loft_curves
from .tools.log_thought import log_thought
from .tools.mesh_from_brep import mesh_from_brep
from .tools.mirror_object import mirror_object
from .tools.modify_object import modify_object
from .tools.modify_objects import modify_objects
from .tools.offset_curve import offset_curve

# File Operations
from .tools.open_file import open_file
from .tools.ping import ping
from .tools.place_doors import place_doors
from .tools.preflight import preflight
from .tools.recall_placements import recall_placements
from .tools.redo import redo
from .tools.revolve_curve import revolve_curve
from .tools.run_native_command import run_native_command
from .tools.save_file import save_file
from .tools.select_objects import select_objects
from .tools.set_debug_mode import set_debug_mode, set_debug_mode_tool
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
from .tools.is_inside import is_inside
from .tools.list_capabilities import list_capabilities
from .tools.scene_summary import scene_summary
from .tools.subscribe_events import subscribe_events
from .tools.undo import undo
from .tools.ungroup import ungroup
from .tools.validate_gh_definition import validate_gh_definition
from .tools.wait_for_object_event import wait_for_object_event

# Grasshopper Operations
from .tools.bake_grasshopper import bake_grasshopper
from .tools.get_grasshopper_outputs import get_grasshopper_outputs
from .tools.inspect_grasshopper_definition import inspect_grasshopper_definition
from .tools.list_grasshopper_definitions import list_grasshopper_definitions
from .tools.load_grasshopper_definition import load_grasshopper_definition
from .tools.run_grasshopper import run_grasshopper
from .tools.set_grasshopper_parameter import set_grasshopper_parameter
from .tools.solve_grasshopper import solve_grasshopper
from .tools.unload_grasshopper_definition import unload_grasshopper_definition
from .tools.grasshopper_interactive import (
    run_door_script,
    run_grasshopper_interactive,
)

# VisualARQ BIM (graceful degradation without the plugin)
from .tools.visualarq import (
    va_add_level,
    va_create_door,
    va_create_wall,
    va_ifc_export,
    va_ifc_import,
    va_list_levels,
    va_list_styles,
    va_status,
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
