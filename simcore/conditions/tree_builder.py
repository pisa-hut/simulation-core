import importlib

from .condition_registry import CONDITION_REGISTRY
from .logical_nodes import AndNode, OrNode


def load_condition_class(type_name: str):
    try:
        module_path = CONDITION_REGISTRY[type_name]
    except KeyError as exc:
        raise ValueError(f"Unknown condition type: {type_name}") from exc

    module_name, class_name = module_path.rsplit(".", 1)
    try:
        module = importlib.import_module(module_name)
        return getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise ValueError(
            f"Invalid condition registry entry for type '{type_name}': '{module_path}'"
        ) from exc


def build_condition_tree(config: dict):
    if not isinstance(config, dict):
        raise ValueError(f"Condition config must be a mapping, got: {config!r}")
    if "type" not in config:
        raise ValueError(f"Condition config must have 'type', got: {config}")

    node_type = config["type"].lower()

    if node_type == "and":
        children = [build_condition_tree(child) for child in config.get("children", [])]
        return AndNode(config, children)

    if node_type == "or":
        children = [build_condition_tree(child) for child in config.get("children", [])]
        return OrNode(config, children)

    if node_type in CONDITION_REGISTRY:
        condition_class = load_condition_class(node_type)
        return condition_class(config)

    raise ValueError(f"Unknown condition type: {node_type}")
