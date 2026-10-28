#!/usr/bin/env python3
"""生成包含“指定实验 + ctl”的 OpenBench YAML 配置。

基本用法（请在 OpenBench 项目根目录执行）：

    .venv/bin/python templates/generate_evaluation_yaml.py \
      --region amazon \
      --variable streamflow \
      --experiment D

上面的命令默认生成：

    generated_configs/amazon_streamflow_D_vs_ctl.yaml

参数取值：

    --region       amazon | lower_mississippi | mekong | missouri
    --variable     streamflow | inundation
                   inundation 会同时评估 Inundation_Fraction 和 Inundation_Area
    --experiment   D | L | B | DB | DLB
                   ctl 不需要指定，脚本会自动加入对应区域的 ctl

指定评估年份：

    .venv/bin/python templates/generate_evaluation_yaml.py \
      --region mekong \
      --variable inundation \
      --experiment L \
      --start-year 2001 \
      --end-year 2004

指定输出文件：

    .venv/bin/python templates/generate_evaluation_yaml.py \
      --region missouri \
      --variable streamflow \
      --experiment DLB \
      --output generated_configs/my_case.yaml

脚本默认不覆盖已有文件。确认需要覆盖时添加 --force：

    .venv/bin/python templates/generate_evaluation_yaml.py \
      --region amazon \
      --variable streamflow \
      --experiment D \
      --force

生成成功后，按终端提示检查配置：

    .venv/bin/openbench check generated_configs/amazon_streamflow_D_vs_ctl.yaml

如果所选区域没有对应实验、history 目录不存在或没有匹配的 NetCDF 文件，
脚本会报错且不会生成 YAML。区域、实验路径和文件前缀统一维护在同目录下的
evaluation_catalog.yaml 中。
"""

from __future__ import annotations

import argparse
import copy
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PROJECT_ROOT / "templates"
CATALOG_PATH = TEMPLATE_DIR / "evaluation_catalog.yaml"
TEMPLATE_PATHS = {
    "streamflow": TEMPLATE_DIR / "streamflow_template.yaml",
    "inundation": TEMPLATE_DIR / "inundation_template.yaml",
}
REGIONS = ("amazon", "lower_mississippi", "mekong", "missouri")
VARIABLES = tuple(TEMPLATE_PATHS)
EXPERIMENTS = ("D", "L", "B", "DB", "DLB")


class GenerationError(ValueError):
    """A requested config cannot be generated safely."""


def _load_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise GenerationError(f"Cannot read YAML {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GenerationError(f"YAML root must be a mapping: {path}")
    return value


def _validate_choice(value: str, choices: tuple[str, ...], label: str) -> str:
    if value not in choices:
        raise GenerationError(f"Unknown {label} {value!r}; choose one of: {', '.join(choices)}")
    return value


def _validate_case(case: dict[str, Any], region: str, experiment: str) -> None:
    required = ("case_name", "root_dir", "prefix")
    missing = [key for key in required if not case.get(key)]
    if missing:
        raise GenerationError(f"Catalog entry {region}/{experiment} is missing: {', '.join(missing)}")

    root_dir = Path(case["root_dir"])
    if not root_dir.is_dir():
        raise GenerationError(f"History directory does not exist for {region}/{experiment}: {root_dir}")
    if not any(root_dir.glob(f"{case['prefix']}*.nc")):
        raise GenerationError(
            f"No NetCDF files match {case['prefix']}*.nc for {region}/{experiment} in {root_dir}"
        )


def build_config(
    region: str,
    variable: str,
    experiment: str,
    start_year: int = 2001,
    end_year: int = 2005,
    *,
    catalog_path: Path = CATALOG_PATH,
    template_paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Build and validate the in-memory configuration mapping."""
    region = _validate_choice(region.lower(), REGIONS, "region")
    variable = _validate_choice(variable.lower(), VARIABLES, "variable")
    experiment = _validate_choice(experiment.upper(), EXPERIMENTS, "experiment")
    if start_year > end_year:
        raise GenerationError(f"start year {start_year} must be <= end year {end_year}")

    catalog = _load_mapping(catalog_path)
    region_data = (catalog.get("regions") or {}).get(region)
    if not isinstance(region_data, dict):
        raise GenerationError(f"Catalog has no region entry: {region}")
    settings = (region_data.get("settings") or {}).get(variable)
    if not isinstance(settings, dict):
        raise GenerationError(f"Catalog has no settings for {region}/{variable}")

    cases = region_data.get("experiments") or {}
    if experiment not in cases:
        available = [name for name in EXPERIMENTS if name in cases]
        raise GenerationError(
            f"Experiment {experiment} is unavailable for {region}; available: {', '.join(available) or 'none'}"
        )
    if "ctl" not in cases:
        raise GenerationError(f"Catalog has no ctl experiment for region: {region}")

    selected = cases[experiment]
    control = cases["ctl"]
    _validate_case(selected, region, experiment)
    _validate_case(control, region, "ctl")

    paths = template_paths or TEMPLATE_PATHS
    config = copy.deepcopy(_load_mapping(paths[variable]))
    display_name = region_data.get("display_name") or region.title()
    config["project"].update(
        {
            "name": f"{display_name}_{variable.title()}_{experiment}_vs_ctl",
            "years": [start_year, end_year],
            "lat_range": settings["lat_range"],
            "lon_range": settings["lon_range"],
            "basin_mask": settings["basin_mask"],
        }
    )

    defaults = catalog.get("simulation_defaults") or {}
    variables = config["evaluation"]["variables"]
    simulations: dict[str, dict[str, Any]] = {}
    for case in (selected, control):
        entry = copy.deepcopy(defaults)
        entry["root_dir"] = case["root_dir"]
        entry["variables"] = {
            name: {"prefix": case["prefix"], "suffix": None} for name in variables
        }
        simulations[case["case_name"]] = entry
    config["simulation"] = simulations
    return config


def write_config(config: dict[str, Any], output: Path, *, force: bool = False) -> Path:
    """Atomically write a config after OpenBench schema validation."""
    if output.exists() and not force:
        raise GenerationError(f"Output already exists (use --force to replace it): {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".yaml", dir=output.parent, delete=False
        ) as handle:
            yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)
            temp_path = Path(handle.name)

        src_dir = PROJECT_ROOT / "src"
        if str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))
        from openbench.config.loader import load_config

        load_config(temp_path)
        os.replace(temp_path, output)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise
    return output


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--region", required=True, choices=REGIONS)
    parser.add_argument("--variable", required=True, choices=VARIABLES)
    parser.add_argument("--experiment", required=True, type=str.upper, choices=EXPERIMENTS)
    parser.add_argument("--start-year", type=int, default=2001)
    parser.add_argument("--end-year", type=int, default=2005)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output or (
        PROJECT_ROOT
        / "generated_configs"
        / f"{args.region}_{args.variable}_{args.experiment}_vs_ctl.yaml"
    )
    try:
        config = build_config(
            args.region, args.variable, args.experiment, args.start_year, args.end_year
        )
        written = write_config(config, output, force=args.force)
    except GenerationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: generated config failed validation: {exc}", file=sys.stderr)
        return 2

    print(f"Generated: {written}")
    print(f"Next: openbench check {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
