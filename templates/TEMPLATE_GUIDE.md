# OpenBench YAML 模板说明

## 推荐：用脚本生成

项目现在提供两份固定模板：

- `streamflow_template.yaml`：只评估 `Streamflow`；
- `inundation_template.yaml`：同时评估 `Inundation_Fraction` 和 `Inundation_Area`。

生成时指定一个区域、变量类型和实验。脚本会自动加入该区域的 `ctl`：

```bash
python templates/generate_evaluation_yaml.py \
  --region amazon \
  --variable streamflow \
  --experiment D
```

默认生成：

```text
generated_configs/amazon_streamflow_D_vs_ctl.yaml
```

可用区域为 `amazon`、`lower_mississippi`、`mekong`、`missouri`；可用实验为
`D`、`L`、`B`、`DB`、`DLB`。不是每个区域都已有全部实验数据，脚本会列出所选区域
当前可用的实验，不会生成带无效路径的配置。

默认年份为 2001–2005，可覆盖年份和输出位置：

```bash
python templates/generate_evaluation_yaml.py \
  --region missouri \
  --variable inundation \
  --experiment DLB \
  --start-year 2002 \
  --end-year 2004 \
  --output generated_configs/custom.yaml
```

已有输出默认不会被覆盖；确认需要替换时添加 `--force`。生成成功后继续运行脚本打印的
`openbench check` 命令。

区域边界、mask 和实验路径集中维护在 `evaluation_catalog.yaml`。添加新实验时：

1. 在相应区域的 `experiments` 下添加实验键；
2. 明确填写 `case_name`、history `root_dir` 和文件 `prefix`；
3. 确认目录中至少存在一个 `<prefix>*.nc` 文件；
4. 运行生成器测试和 `openbench check`。

## 快速使用

```bash
cp templates/openbench_config_template.yaml my_case.yaml
# 修改所有“【必改】”字段后检查
openbench check my_case.yaml
# 检查通过后运行
openbench run my_case.yaml
```

模板是根据项目根目录的 18 个运行配置归纳的。`conda/`、`.github/`、
`src/openbench/data/` 和 `tests/` 中的 YAML 分别属于打包、CI、内置注册表/绘图和测试，
不是用户运行配置，因此没有混入模板。

## 固定结构与变化规律

所有运行配置都使用相同的 8 个顶层段落：

1. `project`：项目名、年份、目标时空分辨率、区域和运行选项。
2. `evaluation.variables`：本次评估变量。
3. `reference`：每个评估变量对应的参考数据集。
4. `simulation`：一个或多个模拟 case；case 名是动态键。
5. `metrics`：原始评价指标。
6. `scores`：归一化评分。
7. `comparison`：多模拟对比图。
8. `statistics`：独立统计分析。

日常新建配置时，通常只需修改：

- `project.name`、`years`、`tim_res`、`grid_res`、经纬度范围和 `basin_mask`；
- `evaluation.variables` 以及 `reference` 中同名变量；
- 每个 simulation 的 case 名、`root_dir`、原始分辨率、`data_groupby`；
- 每个变量的 `prefix` 和 `suffix`；
- 按评估类型选择指标和评分。

`evaluation.variables` 中的每个变量都应在 `reference` 中出现，也应能从模型注册表
或 `simulation.<case>.variables` 中解析。多个 simulation 的结构通常完全相同，只改变 case
标签、目录和文件前缀。

## 两种最常见配置

### 淹没面积/比例（grid 对 grid）

模板默认就是此类型：

- 目标分辨率通常为 `Month`、`0.25`；
- 变量为 `Inundation_Fraction`、`Inundation_Area`；
- 参考数据通常为 `GIEMS_MC_LowRes`；
- 常用 scores 包含相位、年际、空间和季节性评分。

### 径流（grid 模拟对 station 参考）

在模板基础上改为：

```yaml
project:
  tim_res: Day
  grid_res: 0.1

evaluation:
  variables: [Streamflow]

reference:
  Streamflow: GRDC_Daily  # 或 OpenBench_Streamflow_Daily

# 每个 simulation.variables 只保留：
# Streamflow:
#   prefix: CASE_hist_unitcat_
#   suffix: null

metrics: [RMSE, correlation, percent_bias, NSE, KGE, KGESS, MFM]
scores: [Overall_Score]
```

## 容易出错的地方

- YAML 大小写敏感。现有文件同时出现过 `month`/`Month`，新文件统一建议使用 `Month`。
- `project.name` 决定输出子目录，应和实验含义一致。
- simulation 的动态键、`root_dir` 和 `prefix` 应指向同一个 case。
- `grid_res` 有两层：`project.grid_res` 是评估目标网格，simulation 下的是原始模拟网格。
- 空后缀建议明确写成 `suffix: null`，比留空更清楚。
- `statistics.enabled: false` 时使用 `items: []`，避免空列表被解析成 `null`。

样本中还存在几处可能由复制产生的命名不一致，创建新文件时不要照抄：

- `Amazon_streamflow_B.yaml` 的 `project.name` 仍为 `Amazon_Streamflow_D`，且首个 case 仍为 `SA_D_0p1`；
- `Mekong_streamflow__D.yaml` 文件名有两个下划线；
- 部分 `USA_ctl_0p10` 的目录实际写作 `USA_ctl_0p1`；这可能是有意的目录名，使用前应核对。

每次修改后先执行 `openbench check CONFIG.yaml`。它不仅检查 YAML 结构，还会检查注册表、
数据路径和文件可用性，比只做 YAML 语法检查更可靠。
