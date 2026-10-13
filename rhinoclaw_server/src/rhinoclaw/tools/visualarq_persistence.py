"""Read-only persistence readiness checks for VisualARQ products.

VisualARQ semantic identity and Rhino block persistence are deliberately
separate contracts.  A product may answer ``IsProduct == true`` while its
outer instance reference still targets Rhino's transient
``*EmptyDefinition`` system component.  Such an object is useful for live
display, but it is not ready for a save/new-process/reload proof.
"""

import json
from typing import Any, Dict, List
from uuid import UUID

from mcp.server.fastmcp import Context

from rhinoclaw.server import get_rhino_connection, logger, mcp
from rhinoclaw.utils.errors import ErrorCode
from rhinoclaw.utils.responses import from_exception, ok
from rhinoclaw.utils.visualarq import run_va, va_unavailable, warm_va


_MAX_IDS = 200


_PERSISTENCE_READINESS_BODY = r"""
import scriptcontext as sc

max_depth = 32
max_nodes = 10000
max_definitions = 128
max_reported_errors = 100

specific_classifiers = [
    ("curtain_wall", "IsCurtainWall"),
    ("door", "IsDoor"), ("window", "IsWindow"),
    ("wall", "IsWall"), ("column", "IsColumn"),
    ("beam", "IsBeam"), ("slab", "IsSlab"),
    ("stair", "IsStair"), ("railing", "IsRailing"),
    ("roof", "IsRoof"), ("space", "IsSpace"),
    ("furniture", "IsFurniture"),
    ("generic_element", "IsGenericElement"),
    ("opening", "IsOpening"), ("element", "IsElement"),
    ("building_element", "IsBuildingElement"),
]

def add_error(state, code, message, path=None):
    state["error_count"][0] += 1
    if len(state["errors"]) < max_reported_errors:
        item = {"code": code, "message": message}
        if path is not None:
            item["path"] = list(path)
        state["errors"].append(item)

def definition_identity(definition):
    if definition is None:
        return None
    try:
        if definition.Id == Guid.Empty:
            return None
        return str(definition.Id)
    except Exception:
        return None

def read_bool_property(definition, property_name, state, path):
    try:
        return bool(getattr(definition, property_name))
    except Exception as error:
        add_error(
            state, "definition_property_unreadable",
            property_name + ": " + va_text(error), path)
        return None

def visit_definition(definition, path, depth, state):
    if definition is None:
        add_error(
            state, "definition_missing",
            "Instance definition is unavailable", path)
        return
    definition_id = definition_identity(definition)
    if definition_id is None:
        add_error(
            state, "definition_id_empty",
            "Instance definition has an empty or unreadable Guid", path)
        return
    current_path = list(path)
    current_path.append(definition_id)
    if definition_id in path:
        add_error(
            state, "definition_cycle",
            "Cyclic instance definition graph detected", current_path)
        return
    if depth > max_depth:
        add_error(
            state, "definition_depth_exceeded",
            "Instance definition nesting exceeds " + str(max_depth),
            current_path)
        return

    is_new_definition = definition_id not in state["seen_definitions"]
    if is_new_definition and \
            len(state["seen_definitions"]) >= max_definitions:
        add_error(
            state, "definition_limit_exceeded",
            "Validation exceeds " + str(max_definitions) +
                " unique instance definitions", current_path)
        return
    if is_new_definition:
        state["seen_definitions"][definition_id] = True

    name = None
    try:
        name = va_text(definition.Name)
    except Exception as error:
        add_error(
            state, "definition_name_unreadable", va_text(error),
            current_path)
    name_key = name.Trim().ToUpperInvariant() \
        if name is not None else ""
    empty_name = not bool(name_key)
    empty_definition = name_key.StartsWith("*EMPTYDEFINITION")
    if empty_name:
        add_error(
            state, "definition_name_empty",
            "Instance definition name is empty", current_path)
    if empty_definition:
        add_error(
            state, "empty_definition",
            "Instance definition is Rhino's *EmptyDefinition placeholder",
            current_path)

    is_system = read_bool_property(
        definition, "IsSystemComponent", state, current_path)
    is_deleted = read_bool_property(
        definition, "IsDeleted", state, current_path)
    is_valid = read_bool_property(
        definition, "IsValid", state, current_path)
    if is_system is True:
        add_error(
            state, "system_definition",
            "System instance definitions are not persistence-ready roots",
            current_path)
    if is_deleted is True:
        add_error(
            state, "deleted_definition",
            "Deleted instance definition is not persistence-ready",
            current_path)
    if is_valid is not True:
        add_error(
            state, "invalid_definition",
            "Instance definition is not valid", current_path)

    index = None
    table_resident = False
    try:
        index = int(definition.Index)
        if index >= 0 and index < int(sc.doc.InstanceDefinitions.Count):
            table_definition = sc.doc.InstanceDefinitions[index]
            table_resident = table_definition is not None and \
                definition_identity(table_definition) == definition_id
    except Exception as error:
        add_error(
            state, "definition_table_lookup_failed", va_text(error),
            current_path)
    if not table_resident:
        add_error(
            state, "definition_not_document_resident",
            "Instance definition is not present at its document-table index",
            current_path)

    object_count = None
    members = []
    try:
        object_count = int(definition.ObjectCount)
    except Exception as error:
        add_error(
            state, "definition_object_count_unreadable", va_text(error),
            current_path)
    try:
        members = list(definition.GetObjects() or [])
    except Exception as error:
        add_error(
            state, "definition_members_unreadable", va_text(error),
            current_path)
    member_count = len(members)
    if object_count is None or object_count <= 0 or member_count <= 0:
        add_error(
            state, "zero_definition_members",
            "Instance definition has no persistent member objects",
            current_path)
    if object_count is not None and object_count != member_count:
        add_error(
            state, "definition_member_count_mismatch",
            "ObjectCount and GetObjects disagree", current_path)

    if is_new_definition:
        summary = {
            "definition_id": definition_id,
            "name": name,
            "index": index,
            "is_system": is_system,
            "is_deleted": is_deleted,
            "is_valid": is_valid,
            "table_resident": table_resident,
            "object_count": object_count,
            "member_count": member_count,
            "depth": depth,
        }
        state["definitions"].append(summary)
        state["definition_by_id"][definition_id] = summary
        if is_system is True:
            state["system_definition_count"][0] += 1
        if empty_definition:
            state["empty_definition_count"][0] += 1
        if object_count is None or object_count <= 0 or member_count <= 0:
            state["zero_member_definition_count"][0] += 1
    if depth > state["max_depth"][0]:
        state["max_depth"][0] = depth

    for member in members:
        if state["node_count"][0] >= max_nodes:
            if not state["node_limit_reported"][0]:
                add_error(
                    state, "node_limit_exceeded",
                    "Validation exceeds " + str(max_nodes) +
                        " definition member objects", current_path)
                state["node_limit_reported"][0] = True
            break
        state["node_count"][0] += 1
        if member is None:
            add_error(
                state, "definition_member_missing",
                "Definition contains a null member", current_path)
            continue
        member_id = None
        try:
            if member.Id != Guid.Empty:
                member_id = str(member.Id)
        except Exception:
            pass
        member_path = list(current_path)
        member_path.append(member_id or "<empty-member-id>")
        if member_id is None:
            add_error(
                state, "definition_member_id_empty",
                "Definition member has an empty Guid", member_path)
        try:
            member_owned = bool(
                member.Attributes.IsInstanceDefinitionObject)
        except Exception as error:
            member_owned = False
            add_error(
                state, "definition_member_ownership_unreadable",
                va_text(error), member_path)
        if not member_owned:
            add_error(
                state, "definition_member_not_owned",
                "Member is not marked as an instance-definition object",
                member_path)

        if isinstance(member, Rhino.DocObjects.InstanceObject):
            nested_definition = member.InstanceDefinition
            nested_geometry = member.Geometry
            if not isinstance(nested_geometry, rg.InstanceReferenceGeometry):
                add_error(
                    state, "nested_reference_geometry_invalid",
                    "Nested InstanceObject has no InstanceReferenceGeometry",
                    member_path)
            nested_definition_id = definition_identity(nested_definition)
            parent_definition_id = None
            try:
                if nested_geometry is not None and \
                        nested_geometry.ParentIdefId != Guid.Empty:
                    parent_definition_id = str(
                        nested_geometry.ParentIdefId)
            except Exception as error:
                add_error(
                    state, "nested_parent_definition_unreadable",
                    va_text(error), member_path)
            if nested_definition_id is None or \
                    parent_definition_id != nested_definition_id:
                add_error(
                    state, "nested_parent_definition_mismatch",
                    "Nested ParentIdefId does not match InstanceDefinition.Id",
                    member_path)
            visit_definition(
                nested_definition, current_path, depth + 1, state)
            continue

        state["leaf_count"][0] += 1
        geometry = member.Geometry
        if geometry is None:
            add_error(
                state, "leaf_geometry_missing",
                "Definition leaf geometry is unavailable", member_path)
            continue
        try:
            geometry_valid = bool(geometry.IsValid)
        except Exception as error:
            geometry_valid = False
            add_error(
                state, "leaf_geometry_validity_unreadable",
                va_text(error), member_path)
        if not geometry_valid:
            add_error(
                state, "leaf_geometry_invalid",
                "Definition leaf geometry is invalid", member_path)
        else:
            state["valid_leaf_count"][0] += 1

def semantic_probe(object_id):
    product_shape = va_exact_method_shape(
        "IsProduct", ["System.Guid"], "System.Boolean")
    method_shape = {
        "verified": product_shape["verified"],
        "match_count": product_shape["match_count"],
        "parameter_types": product_shape["parameter_types"],
        "return_type": product_shape["return_type"],
    }
    is_product = None
    errors = []
    if product_shape["verified"]:
        try:
            is_product = bool(va.IsProduct(object_id))
        except Exception as error:
            errors.append({
                "method": "IsProduct", "error": va_text(error)})
    else:
        errors.append({
            "method": "IsProduct",
            "error": "exact IsProduct(Guid) -> Boolean shape unavailable",
        })

    classifications = []
    classifier_errors = []
    unavailable_classifiers = []
    for kind, method_name in specific_classifiers:
        if not va_method_available(method_name):
            unavailable_classifiers.append(method_name)
            continue
        try:
            if bool(getattr(va, method_name)(object_id)):
                classifications.append(kind)
        except Exception as error:
            classifier_errors.append({
                "method": method_name, "error": va_text(error)})
    if is_product is True:
        classifications.append("product")

    style_id = None
    style_read_error = None
    if va_method_available("GetProductStyle"):
        try:
            value = va.GetProductStyle(object_id)
            if value is not None and value != Guid.Empty:
                style_id = str(value)
        except Exception as error:
            style_read_error = va_text(error)
    else:
        style_read_error = "method unavailable"
    return {
        "pass": product_shape["verified"] is True and
            is_product is True and not errors,
        "contract": "VisualARQ.Script IsProduct(Guid) -> Boolean",
        "method_shape": method_shape,
        "is_product": is_product,
        "kind": classifications[0] if classifications else None,
        "classifications": classifications,
        "style_id": style_id,
        "style_read_error": style_read_error,
        "errors": errors,
        "classifier_errors": classifier_errors,
        "unavailable_classifiers": unavailable_classifiers,
    }

def persistence_probe(obj):
    state = {
        "errors": [], "error_count": [0],
        "seen_definitions": {}, "definitions": [],
        "definition_by_id": {},
        "node_count": [0], "leaf_count": [0],
        "valid_leaf_count": [0], "max_depth": [0],
        "system_definition_count": [0],
        "empty_definition_count": [0],
        "zero_member_definition_count": [0],
        "node_limit_reported": [False],
    }
    response = {
        "applicable": False,
        "pass": False,
        "root_object_type": None,
        "root_geometry_type": None,
        "root_is_definition_member": None,
        "root_definition_id": None,
        "root_parent_definition_id": None,
        "root_parent_matches": False,
    }
    if obj is None:
        add_error(
            state, "object_not_found",
            "Rhino object was not found in the active document")
    else:
        response["root_object_type"] = str(obj.GetType().FullName)
        geometry = obj.Geometry
        response["root_geometry_type"] = str(geometry.GetType().FullName) \
            if geometry is not None else None
        try:
            response["root_is_definition_member"] = bool(
                obj.Attributes.IsInstanceDefinitionObject)
        except Exception as error:
            add_error(
                state, "root_ownership_unreadable", va_text(error))
        if response["root_is_definition_member"] is True:
            add_error(
                state, "root_not_top_level",
                "Requested object is itself an instance-definition member")
        if not isinstance(obj, Rhino.DocObjects.InstanceObject):
            add_error(
                state, "root_not_instance_object",
                "VisualARQ persistence root is not a Rhino InstanceObject")
        elif not isinstance(geometry, rg.InstanceReferenceGeometry):
            add_error(
                state, "root_geometry_not_instance_reference",
                "InstanceObject has no InstanceReferenceGeometry")
        else:
            response["applicable"] = True
            definition = obj.InstanceDefinition
            definition_id = definition_identity(definition)
            parent_definition_id = None
            try:
                if geometry.ParentIdefId != Guid.Empty:
                    parent_definition_id = str(geometry.ParentIdefId)
            except Exception as error:
                add_error(
                    state, "root_parent_definition_unreadable",
                    va_text(error))
            response["root_definition_id"] = definition_id
            response["root_parent_definition_id"] = parent_definition_id
            response["root_parent_matches"] = definition_id is not None and \
                parent_definition_id == definition_id
            if not response["root_parent_matches"]:
                add_error(
                    state, "root_parent_definition_mismatch",
                    "ParentIdefId does not match InstanceDefinition.Id")
            visit_definition(definition, [], 0, state)

    definitions = sorted(
        state["definitions"],
        key=lambda item: item["definition_id"])
    root_summary = state["definition_by_id"].get(
        response["root_definition_id"])
    response.update({
        "root_definition": root_summary,
        "definition_count": len(state["seen_definitions"]),
        "definitions": definitions,
        "node_count": state["node_count"][0],
        "leaf_count": state["leaf_count"][0],
        "valid_leaf_count": state["valid_leaf_count"][0],
        "max_depth": state["max_depth"][0],
        "system_definition_count": state["system_definition_count"][0],
        "empty_definition_count": state["empty_definition_count"][0],
        "zero_member_definition_count":
            state["zero_member_definition_count"][0],
        "error_count": state["error_count"][0],
        "errors": state["errors"],
        "errors_truncated":
            state["error_count"][0] > len(state["errors"]),
        "limits": {
            "max_depth": max_depth,
            "max_nodes": max_nodes,
            "max_definitions": max_definitions,
        },
    })
    response["pass"] = response["applicable"] is True and \
        response["root_is_definition_member"] is False and \
        response["root_parent_matches"] is True and \
        response["definition_count"] >= 1 and \
        response["leaf_count"] >= 1 and \
        response["valid_leaf_count"] == response["leaf_count"] and \
        response["system_definition_count"] == 0 and \
        response["empty_definition_count"] == 0 and \
        response["zero_member_definition_count"] == 0 and \
        response["error_count"] == 0
    return response

modified_before = bool(sc.doc.Modified)
object_count_before = int(sc.doc.Objects.Count)
definition_count_before = int(sc.doc.InstanceDefinitions.Count)
objects = []
root_definition_owners = {}
for requested_id in params["ids"]:
    object_id = Guid(requested_id)
    obj = sc.doc.Objects.FindId(object_id)
    semantics = semantic_probe(object_id)
    persistence = persistence_probe(obj)
    item_ready = semantics["pass"] is True and \
        persistence["pass"] is True
    failures = []
    if semantics["pass"] is not True:
        failures.append("visualarq_semantics_unverified")
    if persistence["pass"] is not True:
        failures.append("rhino_persistence_root_unready")
    item = {
        "id": requested_id,
        "exists": obj is not None,
        "ready": item_ready,
        "visualarq_semantics": semantics,
        "rhino_persistence_root": persistence,
        "failures": failures,
    }
    objects.append(item)
    root_definition_id = persistence.get("root_definition_id")
    if root_definition_id is not None:
        owners = root_definition_owners.get(root_definition_id, [])
        owners.append(requested_id)
        root_definition_owners[root_definition_id] = owners

modified_after = bool(sc.doc.Modified)
object_count_after = int(sc.doc.Objects.Count)
definition_count_after = int(sc.doc.InstanceDefinitions.Count)
state_guard = {
    "modified_before": modified_before,
    "modified_after": modified_after,
    "object_count_before": object_count_before,
    "object_count_after": object_count_after,
    "instance_definition_count_before": definition_count_before,
    "instance_definition_count_after": definition_count_after,
}
state_guard["pass"] = modified_before == modified_after and \
    object_count_before == object_count_after and \
    definition_count_before == definition_count_after
ready_count = len([item for item in objects if item["ready"]])
shared_root_definitions = [
    {"definition_id": definition_id, "object_ids": owner_ids}
    for definition_id, owner_ids in root_definition_owners.items()
    if len(owner_ids) > 1
]
shared_root_definitions.sort(key=lambda item: item["definition_id"])
result = {
    "status": "success",
    "ready": ready_count == len(objects) and state_guard["pass"],
    "requested_ids": list(params["ids"]),
    "requested_count": len(objects),
    "ready_count": ready_count,
    "not_ready_count": len(objects) - ready_count,
    "objects": objects,
    "shared_root_definitions": shared_root_definitions,
    "state_guard": state_guard,
    "contract": {
        "read_only": True,
        "visualarq_semantics":
            "exact IsProduct(Guid) -> Boolean",
        "rhino_persistence_root":
            "recursive non-system non-empty InstanceDefinition graph",
        "save_or_reload_performed": False,
    },
}
"""


def _normalize_ids(ids: List[str]) -> List[str]:
    if not isinstance(ids, list) or not ids:
        raise ValueError("ids must be a non-empty list of GUID strings")
    if len(ids) > _MAX_IDS:
        raise ValueError(f"ids must contain at most {_MAX_IDS} GUIDs")
    normalized: List[str] = []
    seen = set()
    for index, value in enumerate(ids):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"ids[{index}] must be a valid non-empty GUID")
        try:
            parsed = UUID(value.strip().strip("{}"))
        except (AttributeError, TypeError, ValueError):
            raise ValueError(
                f"ids[{index}] must be a valid non-empty GUID"
            ) from None
        if parsed.int == 0:
            raise ValueError(f"ids[{index}] must not be the empty GUID")
        canonical = str(parsed)
        if canonical in seen:
            raise ValueError(f"ids contains duplicate GUID: {canonical}")
        seen.add(canonical)
        normalized.append(canonical)
    return normalized


def _require_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"Malformed persistence result: {field}")
    return value


def _validate_result_contract(
    result: Dict[str, Any], requested_ids: List[str]
) -> None:
    """Fail closed if Rhino returns an optimistic or incomplete envelope."""
    if not isinstance(result, dict) or result.get("status") != "success":
        raise ValueError("Malformed persistence result: missing success status")
    if result.get("requested_ids") != requested_ids:
        raise ValueError("Malformed persistence result: requested_ids mismatch")
    requested_count = _require_int(
        result.get("requested_count"), "requested_count")
    ready_count = _require_int(result.get("ready_count"), "ready_count")
    not_ready_count = _require_int(
        result.get("not_ready_count"), "not_ready_count")
    objects = result.get("objects")
    if (
        requested_count != len(requested_ids)
        or not isinstance(objects, list)
        or len(objects) != requested_count
        or ready_count + not_ready_count != requested_count
    ):
        raise ValueError("Malformed persistence result: aggregate counts")

    state_guard = result.get("state_guard")
    if not isinstance(state_guard, dict) or type(state_guard.get("pass")) is not bool:
        raise ValueError("Malformed persistence result: state_guard")
    for field in (
        "modified_before",
        "modified_after",
    ):
        if type(state_guard.get(field)) is not bool:
            raise ValueError(f"Malformed persistence result: state_guard.{field}")
    for field in (
        "object_count_before",
        "object_count_after",
        "instance_definition_count_before",
        "instance_definition_count_after",
    ):
        _require_int(state_guard.get(field), f"state_guard.{field}")
    expected_state_pass = (
        state_guard["modified_before"] == state_guard["modified_after"]
        and state_guard["object_count_before"]
        == state_guard["object_count_after"]
        and state_guard["instance_definition_count_before"]
        == state_guard["instance_definition_count_after"]
    )
    if state_guard["pass"] is not expected_state_pass:
        raise ValueError("Malformed persistence result: state_guard.pass")

    calculated_ready_count = 0
    for index, (item, requested_id) in enumerate(zip(objects, requested_ids)):
        if not isinstance(item, dict) or item.get("id") != requested_id:
            raise ValueError(
                f"Malformed persistence result: objects[{index}].id"
            )
        if type(item.get("exists")) is not bool or type(item.get("ready")) is not bool:
            raise ValueError(
                f"Malformed persistence result: objects[{index}] booleans"
            )
        failures = item.get("failures")
        semantics = item.get("visualarq_semantics")
        persistence = item.get("rhino_persistence_root")
        if (
            not isinstance(failures, list)
            or not isinstance(semantics, dict)
            or not isinstance(persistence, dict)
            or type(semantics.get("pass")) is not bool
            or type(persistence.get("pass")) is not bool
            or not isinstance(semantics.get("errors"), list)
            or not isinstance(persistence.get("errors"), list)
        ):
            raise ValueError(
                f"Malformed persistence result: objects[{index}] evidence"
            )
        method_shape = semantics.get("method_shape")
        if (
            not isinstance(method_shape, dict)
            or type(method_shape.get("verified")) is not bool
            or type(semantics.get("is_product")) not in (bool, type(None))
        ):
            raise ValueError(
                f"Malformed persistence result: objects[{index}] semantics"
            )
        expected_semantic_pass = (
            method_shape["verified"] is True
            and semantics["is_product"] is True
            and not semantics["errors"]
        )
        if semantics["pass"] is not expected_semantic_pass:
            raise ValueError(
                f"Malformed persistence result: objects[{index}] semantic pass"
            )

        for field in (
            "definition_count",
            "leaf_count",
            "valid_leaf_count",
            "system_definition_count",
            "empty_definition_count",
            "zero_member_definition_count",
            "error_count",
        ):
            _require_int(
                persistence.get(field),
                f"objects[{index}].rhino_persistence_root.{field}",
            )
        if type(persistence.get("applicable")) is not bool:
            raise ValueError(
                f"Malformed persistence result: objects[{index}] applicable"
            )
        if persistence["error_count"] < len(persistence["errors"]):
            raise ValueError(
                f"Malformed persistence result: objects[{index}] error_count"
            )
        if persistence["pass"]:
            root_definition = persistence.get("root_definition")
            definitions = persistence.get("definitions")
            if (
                persistence["applicable"] is not True
                or persistence.get("root_is_definition_member") is not False
                or persistence.get("root_parent_matches") is not True
                or not isinstance(persistence.get("root_definition_id"), str)
                or persistence.get("root_parent_definition_id")
                != persistence.get("root_definition_id")
                or not isinstance(root_definition, dict)
                or not isinstance(root_definition.get("definition_id"), str)
                or not root_definition["definition_id"]
                or root_definition["definition_id"]
                != persistence["root_definition_id"]
                or not isinstance(root_definition.get("name"), str)
                or not root_definition["name"].strip()
                or root_definition["name"].strip().upper().startswith(
                    "*EMPTYDEFINITION"
                )
                or root_definition.get("is_system") is not False
                or root_definition.get("is_deleted") is not False
                or root_definition.get("is_valid") is not True
                or root_definition.get("table_resident") is not True
                or type(root_definition.get("object_count")) is not int
                or root_definition["object_count"] < 1
                or type(root_definition.get("member_count")) is not int
                or root_definition["member_count"] < 1
                or not isinstance(definitions, list)
                or len(definitions) != persistence["definition_count"]
                or persistence["definition_count"] < 1
                or persistence["leaf_count"] < 1
                or persistence["valid_leaf_count"] != persistence["leaf_count"]
                or persistence["system_definition_count"] != 0
                or persistence["empty_definition_count"] != 0
                or persistence["zero_member_definition_count"] != 0
                or persistence["error_count"] != 0
            ):
                raise ValueError(
                    f"Malformed persistence result: objects[{index}] "
                    "optimistic persistence pass"
                )
            for definition in definitions:
                if (
                    not isinstance(definition, dict)
                    or not isinstance(definition.get("definition_id"), str)
                    or not definition["definition_id"]
                    or not isinstance(definition.get("name"), str)
                    or not definition["name"].strip()
                    or definition["name"].strip().upper().startswith(
                        "*EMPTYDEFINITION"
                    )
                    or definition.get("is_system") is not False
                    or definition.get("is_deleted") is not False
                    or definition.get("is_valid") is not True
                    or definition.get("table_resident") is not True
                    or type(definition.get("object_count")) is not int
                    or definition["object_count"] < 1
                    or type(definition.get("member_count")) is not int
                    or definition["member_count"] < 1
                ):
                    raise ValueError(
                        f"Malformed persistence result: objects[{index}] "
                        "optimistic nested definition pass"
                    )
        expected_ready = semantics["pass"] and persistence["pass"]
        if item["ready"] is not expected_ready:
            raise ValueError(
                f"Malformed persistence result: objects[{index}].ready"
            )
        if item["ready"]:
            calculated_ready_count += 1

    if ready_count != calculated_ready_count:
        raise ValueError("Malformed persistence result: ready_count")
    expected_ready = ready_count == requested_count and state_guard["pass"]
    if type(result.get("ready")) is not bool or result["ready"] is not expected_ready:
        raise ValueError("Malformed persistence result: ready")
    if not isinstance(result.get("shared_root_definitions"), list):
        raise ValueError(
            "Malformed persistence result: shared_root_definitions"
        )
    contract = result.get("contract")
    if (
        not isinstance(contract, dict)
        or contract.get("read_only") is not True
        or contract.get("save_or_reload_performed") is not False
    ):
        raise ValueError("Malformed persistence result: contract")


@mcp.tool()
def va_validate_persistence_readiness(
    ctx: Context,
    ids: List[str],
) -> str:
    """Validate whether VisualARQ products are safe to persist as Rhino blocks.

    This read-only validator deliberately separates VisualARQ semantic identity
    from the Rhino instance-definition graph that must survive SaveAs and a new
    Rhino process.  It rejects ``*EmptyDefinition``, every system definition,
    zero-member definitions, bad ParentIdefId links, cycles, invalid leaves and
    non-definition-owned members.  ``ready: true`` is a pre-save gate only; a
    SaveAs/new-process/reload readback remains mandatory artifact proof.

    Parameters:
    - ids: 1..200 unique, non-empty Rhino object GUIDs.
    """
    try:
        requested_ids = _normalize_ids(ids)
        rhino = get_rhino_connection()
        warm_va(rhino)
        result = run_va(
            rhino,
            _PERSISTENCE_READINESS_BODY,
            {"ids": requested_ids},
        )
        if result.get("runner_failure") == "missing_result_marker":
            result = run_va(
                rhino,
                _PERSISTENCE_READINESS_BODY,
                {"ids": requested_ids},
            )
            result["bootstrap_retry_attempted"] = True
            result["bootstrap_retry_reason"] = "missing_result_marker"
        if va_unavailable(result):
            return json.dumps(from_exception(
                RuntimeError(
                    "VisualARQ is unavailable; run va_status after loading "
                    "the plugin"
                ),
                code=ErrorCode.RHINO_ERROR,
            ))
        if result.get("status") == "error":
            code = (
                ErrorCode.SCRIPT_ERROR
                if result.get("code") == "SCRIPT_ERROR"
                else ErrorCode.VERIFICATION_FAILED
            )
            return json.dumps(from_exception(
                RuntimeError(
                    result.get(
                        "message", "VisualARQ persistence validation failed"
                    )
                ),
                code=code,
            ))
        try:
            _validate_result_contract(result, requested_ids)
        except ValueError as error:
            return json.dumps(from_exception(
                error, code=ErrorCode.VERIFICATION_FAILED
            ))
        return json.dumps(ok(
            message=(
                f"{result['ready_count']}/{result['requested_count']} "
                "VisualARQ product(s) are persistence-ready"
            ),
            data=result,
        ))
    except ValueError as error:
        return json.dumps(from_exception(error, code=ErrorCode.INVALID_PARAMS))
    except Exception as error:
        logger.error("Error validating VisualARQ persistence readiness: %s", error)
        return json.dumps(from_exception(error, code=ErrorCode.RHINO_ERROR))
