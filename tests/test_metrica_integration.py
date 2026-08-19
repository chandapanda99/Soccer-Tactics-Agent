from __future__ import annotations

import os

import pytest

from soccer_tactics.data import MetricaDataService


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("RUN_METRICA_INTEGRATION"), reason="set RUN_METRICA_INTEGRATION=1")
def test_all_three_upstream_matches_ingest():
    matches = MetricaDataService().sync()
    assert [match.match_id for match in matches] == ["sample-game-1", "sample-game-2", "sample-game-3"]
