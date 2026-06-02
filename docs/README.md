# Documentation

This folder keeps detailed usage and implementation notes out of the root README.

- [Engine](engine/): runner spec, execution lifecycle, outputs, retry/skip behavior.
- [AV and Simulator Wrappers](wrappers/): gRPC lifecycle and wrapper config.
- [Sampler](sampler/): sampler spec, sampler config files, source formats, implemented methods.
- [Monitor](monitor/): stop conditions, logging, result status fields, recorder/condition extension.

Examples live next to the component that uses them:

- [Sampler examples](sampler/examples/)
- [Monitor logging example](monitor/examples/logging_config_example.yaml)
- [Monitor stop condition example](monitor/examples/stop_condition_config_example.yaml)
