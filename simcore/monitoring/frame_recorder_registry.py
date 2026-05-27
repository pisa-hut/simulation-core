import importlib

FRAME_RECORDER_REGISTRY = {
    "ego_state": "simcore.monitoring.frame_recorders.ego_state:EgoStateFrameRecorder",
    "pair_ttc": "simcore.monitoring.frame_recorders.pair_ttc:PairTTCFrameRecorder",
}


def load_frame_recorder_class(type_name: str):
    try:
        module_path = FRAME_RECORDER_REGISTRY[type_name]
    except KeyError as exc:
        raise ValueError(f"Unknown frame recorder type: {type_name}") from exc

    if ":" not in module_path:
        raise ValueError(
            f"Invalid frame recorder registry entry for type '{type_name}': '{module_path}'"
        )

    module_name, class_name = module_path.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def build_frame_recorders(configs: list[dict]):
    recorders = []
    for config in configs:
        if not isinstance(config, dict):
            raise ValueError(f"Frame recorder config must be a mapping, got: {config!r}")
        if "type" not in config:
            raise ValueError(f"Frame recorder config must have 'type', got: {config}")
        recorder_class = load_frame_recorder_class(str(config["type"]).lower())
        recorders.append(recorder_class(config))
    return recorders
