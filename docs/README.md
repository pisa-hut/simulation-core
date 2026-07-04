# Documentation

This folder keeps detailed usage and implementation notes out of the root README.

- [Engine](engine/): runner spec, execution lifecycle, outputs, retry/skip behavior.
- [AV and Simulator Wrappers](wrappers/): gRPC lifecycle and wrapper config.
- [Sampler](sampler/): sampler spec, sampler config files, source formats, implemented sampler names.
- [Monitor](monitor/): stop conditions, logging, result status fields, recorder/condition extension.
- [Runtime data contracts](data-contracts/): normative simulator, AV, sim-core, and monitor
  conventions for identity, coordinates, units, timestamps, and actor geometry.
- [Observation identity migration](observation-identity-migration/): coordinated breaking contract
  and implementation prompts for pisa-api, simulator wrappers, and AV wrappers.

Examples live next to the component that uses them:

- [Sampler examples](sampler/examples/)
- [Monitor logging example](monitor/examples/logging_config_example.yaml)
- [Monitor stop condition example](monitor/examples/stop_condition_config_example.yaml)
