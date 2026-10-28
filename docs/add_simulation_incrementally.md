# OpenBench 在已有评估结果中增量添加实验

本文记录如何在已有 OpenBench 评估结果的基础上，只计算一个新实验，并复用旧实验的指标生成新的多实验对比。

以下示例基于：

- 原配置：`SA_streamflow_D_B.yaml`
- 原结果：`output/Streamflow_SA_D_B`
- 已有实验：`SA_D_0p1`、`SA_ctl_0p10`、`SA_B_0p1`
- 新增实验：`SA_L_0p1`
- 新实验数据：`/share/home/dq134/wzx/CoLM/cases/SA_L_0p1/history`

## 为什么不直接修改原配置后普通运行

该项目默认使用：

```yaml
project:
  unified_mask: true
```

当同一变量下新增一个没有缓存的实验时，普通运行可能把该变量的旧实验也重新排队。`--resume` 主要用于恢复兼容的预处理结果，不能保证只运行新增实验。

最小重跑方案分为两步：

1. 使用“仅包含新实验”的临时配置，只评估新实验。
2. 使用包含全部实验的配置，通过 `--comparison-only` 复用已有指标并重建对比。

不要使用 `--force`，否则会绕过增量缓存。

## 第一步：创建只包含新实验的配置

复制原配置：

```bash
cd /share/home/dq134/wzx/openbench/openbench_1015
cp SA_streamflow_D_B.yaml SA_streamflow_L_only.yaml
```

在 `SA_streamflow_L_only.yaml` 中保持原来的项目名不变：

```yaml
project:
  name: Streamflow_SA_D_B
```

保持相同项目名可以让新实验的评估结果直接加入已有目录：

```text
output/Streamflow_SA_D_B
```

将整个 `simulation:` 部分替换为新实验：

```yaml
simulation:
  SA_L_0p1:
    model: CoLM2024
    root_dir: /share/home/dq134/wzx/CoLM/cases/SA_L_0p1/history
    data_type: grid
    tim_res: Day
    grid_res: 0.1
    data_groupby: Month
    variables:
      Inundation_Fraction:
        prefix: 'SA_L_0p1_hist_unitcat_'
        suffix:
      Streamflow:
        prefix: 'SA_L_0p1_hist_unitcat_'
        suffix:
```

为了避免第一步生成只有一个实验的临时对比和报告，建议同时设置：

```yaml
project:
  name: Streamflow_SA_D_B
  generate_report: false

comparison:
  enabled: false
```

原有的年份、空间范围、参考数据、时间分辨率、指标和评分项目必须保持不变，否则新旧结果可能不具备可比性。

## 第二步：只评估新实验

先检查配置：

```bash
openbench check SA_streamflow_L_only.yaml
```

确认无误后运行：

```bash
openbench run SA_streamflow_L_only.yaml
```

这一阶段应只出现如下任务：

```text
Streamflow / GRDC_Daily / SA_L_0p1
```

运行结束后，至少检查以下两个文件：

```text
output/Streamflow_SA_D_B/metrics/Streamflow_stn_GRDC_Daily_SA_L_0p1_evaluations.csv
output/Streamflow_SA_D_B/scores/Streamflow_stn_GRDC_Daily_SA_L_0p1_evaluations.csv
```

可以使用：

```bash
ls -lh \
  output/Streamflow_SA_D_B/metrics/Streamflow_stn_GRDC_Daily_SA_L_0p1_evaluations.csv \
  output/Streamflow_SA_D_B/scores/Streamflow_stn_GRDC_Daily_SA_L_0p1_evaluations.csv
```

## 第三步：创建包含全部实验的配置

再复制一份原配置：

```bash
cp SA_streamflow_D_B.yaml SA_streamflow_D_B_L.yaml
```

在 `SA_streamflow_D_B_L.yaml` 的 `simulation:` 下保留原来的三个实验，并加入：

```yaml
  SA_L_0p1:
    model: CoLM2024
    root_dir: /share/home/dq134/wzx/CoLM/cases/SA_L_0p1/history
    data_type: grid
    tim_res: Day
    grid_res: 0.1
    data_groupby: Month
    variables:
      Inundation_Fraction:
        prefix: 'SA_L_0p1_hist_unitcat_'
        suffix:
      Streamflow:
        prefix: 'SA_L_0p1_hist_unitcat_'
        suffix:
```

确保对比功能开启，例如：

```yaml
comparison:
  enabled: true
  items:
    - Taylor_Diagram
    - HeatMap
    - Portrait_Plot_seasonal
    - Diff_Plot
```

## 第四步：只重建四实验对比

先验证全部实验所需的指标和评分文件都存在：

```bash
openbench check SA_streamflow_D_B_L.yaml --comparison-only
```

然后只运行对比阶段：

```bash
openbench run SA_streamflow_D_B_L.yaml --comparison-only
```

`--comparison-only` 会跳过：

- 原始模拟数据预处理；
- 站点匹配和提取；
- metrics 和 scores 的重新计算。

它会读取四个实验已有的评估 CSV，并更新 `output/Streamflow_SA_D_B/comparisons/` 下的对比结果。

## 如果还需要更新 HTML 报告

`--comparison-only` 不会重新生成 HTML 报告。如果需要让报告也包含新实验，可在四实验配置中设置：

```yaml
project:
  name: Streamflow_SA_D_B
  only_drawing: true
  generate_report: true
```

然后不带 `--comparison-only` 运行：

```bash
openbench run SA_streamflow_D_B_L.yaml
```

`only_drawing: true` 会复用已有评估产物，重新绘图和生成报告，不重新执行数值评估。完成后建议把它改回 `false` 或重新注释掉，避免以后误用绘图模式。

## 重要注意事项

### 1. 第一阶段会清理旧对比和报告

只要普通运行中存在需要评估的新任务，OpenBench 会清理旧的 `comparisons/` 和 `reports/`，防止旧图被误认为当前结果。新实验成功后，应立即执行完整配置的 `--comparison-only`；如需报告，再执行 `only_drawing`。

### 2. 不要改动可比性相关配置

新旧实验应使用完全一致的：

- `project.years`
- `project.lat_range` 和 `project.lon_range`
- `project.tim_res` 和 `project.grid_res`
- reference 数据源
- metrics 和 scores
- `time_alignment` 和 `unified_mask`

若这些选项发生改变，旧评估结果不应直接与新结果混用。

### 3. 不要使用 `--force`

以下命令会强制重算配置中的所有评估任务，不适合增量添加实验：

```bash
openbench run SA_streamflow_D_B_L.yaml --force
```

### 4. 不建议直接用完整配置普通运行

以下命令在 `unified_mask: true` 时可能重新运行旧实验：

```bash
openbench run SA_streamflow_D_B_L.yaml
```

除非已明确设置 `only_drawing: true`，否则应使用本文的两阶段方法。

## 通用复用模板

以后新增任意实验 `NEW_CASE` 时：

1. 从原配置复制 `CASE_only.yaml`，保持原 `project.name`。
2. `simulation:` 中只保留 `NEW_CASE`。
3. 保持年份、区域、参考数据、指标和评分设置不变。
4. 设置 `comparison.enabled: false` 和 `project.generate_report: false`。
5. 运行 `openbench check CASE_only.yaml`。
6. 运行 `openbench run CASE_only.yaml`，只生成新实验结果。
7. 创建完整配置，在 `simulation:` 中加入 `NEW_CASE`。
8. 运行 `openbench check FULL.yaml --comparison-only`。
9. 运行 `openbench run FULL.yaml --comparison-only`。
10. 如需完整报告，使用 `project.only_drawing: true` 再运行完整配置。

## 完成检查清单

- [ ] 新实验的 metrics CSV 存在且可读。
- [ ] 新实验的 scores CSV 存在且可读。
- [ ] 完整配置中列出了全部旧实验和新实验。
- [ ] `--comparison-only` 检查通过。
- [ ] Taylor Diagram 包含新实验。
- [ ] HeatMap 包含新实验。
- [ ] Portrait Plot 包含新实验。
- [ ] Diff Plot 生成了涉及新实验的成对差异结果。
- [ ] 如有需要，HTML report 已通过 `only_drawing` 更新。
