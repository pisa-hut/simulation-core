import importlib

RECORDER_REGISTRY = {
    "ego_state": "simcore.monitoring.recorders.ego_state:EgoStateRecorder",
    "agent_states": "simcore.monitoring.recorders.agent_states:AgentStatesRecorder",
    "collision_events": "simcore.monitoring.recorders.collision_events:CollisionEventsRecorder",
}


def load_recorder_class(type_name: str):
    try:
        module_path = RECORDER_REGISTRY[type_name]
    except KeyError as exc:
        raise ValueError(f"Unknown recorder type: {type_name}") from exc

    if ":" not in module_path:
        raise ValueError(f"Invalid recorder registry entry for type '{type_name}': '{module_path}'")

    module_name, class_name = module_path.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def build_recorders(configs: list[dict]):
    recorders = []
    for config in configs:
        if not isinstance(config, dict):
            raise ValueError(f"Recorder config must be a mapping, got: {config!r}")
        if "type" not in config:
            raise ValueError(f"Recorder config must have 'type', got: {config}")
        recorder_class = load_recorder_class(str(config["type"]).lower())
        recorders.append(recorder_class(config))
    return recorders
