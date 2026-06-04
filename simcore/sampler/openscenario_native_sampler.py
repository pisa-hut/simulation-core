from __future__ import annotations

from simcore.sampler.grid_search_sampler import GridSearchSampler


class OpenScenarioNativeSampler(GridSearchSampler):
    """Run the concrete sample series defined by an OpenSCENARIO parameter file."""

    def __init__(self, *args, **kwargs):
        kwargs["output_parameters"] = []
        super().__init__(*args, **kwargs)
