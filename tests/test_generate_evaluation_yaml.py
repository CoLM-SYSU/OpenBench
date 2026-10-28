from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).parents[1] / "templates" / "generate_evaluation_yaml.py"
SPEC = importlib.util.spec_from_file_location("generate_evaluation_yaml", SCRIPT)
assert SPEC and SPEC.loader
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


@pytest.mark.parametrize(
    ("region", "variable", "expected_lat", "expected_mask"),
    [
        ("amazon", "streamflow", [-22.0, 11.0], "amazon_basin.nc"),
        ("lower_mississippi", "inundation", [28.0, 40.0], "mississippi_cairo_to_mouth_added_catchments_basin.nc"),
        ("mekong", "streamflow", [9.0, 34.0], "mekong_basin.nc"),
        ("missouri", "inundation", [37.0, 50.0], "missouri_basin.nc"),
    ],
)
def test_region_settings_are_injected(region, variable, expected_lat, expected_mask):
    config = generator.build_config(region, variable, "D")

    assert config["project"]["lat_range"] == expected_lat
    assert config["project"]["basin_mask"].endswith(expected_mask)
    assert len(config["simulation"]) == 2


def test_streamflow_template_and_year_override():
    config = generator.build_config("amazon", "streamflow", "B", 2002, 2004)

    assert config["project"]["years"] == [2002, 2004]
    assert config["evaluation"]["variables"] == ["Streamflow"]
    assert config["reference"] == {"Streamflow": "GRDC_Daily"}
    assert config["scores"] == ["Overall_Score"]
    assert list(config["simulation"]) == ["SA_B_0p1", "SA_ctl_0p10"]


def test_inundation_template_contains_only_evaluated_variable_overrides():
    config = generator.build_config("mekong", "inundation", "L")

    variables = ["Inundation_Fraction", "Inundation_Area"]
    assert config["evaluation"]["variables"] == variables
    assert config["project"]["tim_res"] == "Month"
    assert set(config["scores"]) >= {"nPhaseScore", "nSpatialScore", "nSeasonalityScore"}
    for simulation in config["simulation"].values():
        assert list(simulation["variables"]) == variables


@pytest.mark.parametrize("experiment", ["D", "L", "B", "DB", "DLB"])
def test_all_usa_experiments_generate(experiment):
    config = generator.build_config("missouri", "streamflow", experiment)

    assert len(config["simulation"]) == 2
    assert list(config["simulation"])[-1] == "USA_ctl_0p10"


def test_unavailable_experiment_is_rejected():
    with pytest.raises(generator.GenerationError, match="unavailable.*available"):
        generator.build_config("mekong", "streamflow", "DLB")


def test_invalid_years_are_rejected():
    with pytest.raises(generator.GenerationError, match="start year"):
        generator.build_config("amazon", "streamflow", "D", 2005, 2001)


@pytest.mark.parametrize(
    ("region", "variable", "experiment", "message"),
    [
        ("unknown", "streamflow", "D", "Unknown region"),
        ("amazon", "unknown", "D", "Unknown variable"),
        ("amazon", "streamflow", "ctl", "Unknown experiment"),
    ],
)
def test_invalid_choices_are_rejected(region, variable, experiment, message):
    with pytest.raises(generator.GenerationError, match=message):
        generator.build_config(region, variable, experiment)


def test_write_validates_and_does_not_overwrite(tmp_path):
    output = tmp_path / "result.yaml"
    config = generator.build_config("amazon", "streamflow", "D")

    generator.write_config(config, output)
    parsed = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert parsed["project"]["name"] == "Amazon_Streamflow_D_vs_ctl"

    with pytest.raises(generator.GenerationError, match="already exists"):
        generator.write_config(config, output)

    config["project"]["years"] = [2003, 2004]
    generator.write_config(config, output, force=True)
    assert yaml.safe_load(output.read_text(encoding="utf-8"))["project"]["years"] == [2003, 2004]


def test_missing_history_does_not_create_output(tmp_path):
    catalog = yaml.safe_load(generator.CATALOG_PATH.read_text(encoding="utf-8"))
    catalog["regions"]["amazon"]["experiments"]["D"]["root_dir"] = str(tmp_path / "missing")
    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")

    with pytest.raises(generator.GenerationError, match="does not exist"):
        generator.build_config("amazon", "streamflow", "D", catalog_path=catalog_path)
    assert not list(tmp_path.glob("result*.yaml"))
