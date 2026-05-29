from __future__ import annotations

from simcore.sampler.grid_search_sampler import GridSearchSampler


class OpenScenarioNativeSampler(GridSearchSampler):
    """Run the concrete sample series defined by an OpenSCENARIO parameter file."""
