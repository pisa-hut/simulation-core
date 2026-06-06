import importlib

SUMMARY_RECORDER_REGISTRY = {
    "basic_summary": "simcore.monitoring.summary_recorders.basic_summary:BasicSummaryRecorder",
    "max_speed": "simcore.monitoring.summary_recorders.max_speed:MaxSpeedSummaryRecorder",
    "min_ttc": "simcore.monitoring.summary_recorders.min_ttc:MinTTCSummaryRecorder",
    "numeric_summary": (
        "simcore.monitoring.summary_recorders.numeric_summary:NumericSummaryRecorder"
    ),
}


def load_summary_recorder_class(type_name: str):
    try:
        module_path = SUMMARY_RECORDER_REGISTRY[type_name]
    except KeyError as exc:
        raise ValueError(f"Unknown summary recorder type: {type_name}") from exc

    if ":" not in module_path:
        raise ValueError(
            f"Invalid summary recorder registry entry for type '{type_name}': '{module_path}'"
        )

    module_name, class_name = module_path.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def build_summary_recorders(configs: list[dict]):
    recorders = []
    for config in configs:
        if not isinstance(config, dict):
            raise ValueError(f"Summary recorder config must be a mapping, got: {config!r}")
        if "type" not in config:
            raise ValueError(f"Summary recorder config must have 'type', got: {config}")
        recorder_class = load_summary_recorder_class(str(config["type"]).lower())
        recorders.append(recorder_class(config))
    names = [recorder.name for recorder in recorders]
    duplicate_names = sorted({name for name in names if names.count(name) > 1})
    if duplicate_names:
        raise ValueError(
            "Summary recorder names must be unique; duplicate(s): "
            + ", ".join(duplicate_names)
        )
    return recorders
