# A Two Column Paper About Visibility Nowcasting

- 源文件：`two_column.pdf`（3 页）
- 作者：C. Writer, D. Writer
- 单位：未识别
- 版式：2col 3 页
- 解析耗时：0.1s；锚点通过率：1.0

> 段落前的 `[p.N]` 是**物理页码**，用于回查原文；`¶` 表示该段与上一段是同一段被排版切断。

## 摘要

Visibility forecasting at airports is a hard problem because low-visibility events are rare, strongly stratified, and driven by interactions between radiative cooling, turbulence and advection that numerical models resolve only partially. Statistical post-processing offers a practical alternative. Instead of resolving the microphysics, it learns a mapping from predictors that are already available from the numerical model to the probability of the target event, using a long archive of historical observations as the training signal.

## 结构目录

- 1 Introduction（第 1 页）
- 2 Results（第 2 页）
- 3 Results（第 3 页）

## 正文

### 1 Introduction

[p.1] Visibility forecasting at airports is a hard problem because low-visibility events are rare, strongly stratified, and driven by interactions between radiative cooling, turbulence and advection that numerical models resolve only partially.

[p.1] Statistical post-processing offers a practical alternative. Instead of resolving the microphysics, it learns a mapping from predictors that are already available from the numerical model to the probability of the target event, using a long archive of historical observations as the training signal.

[p.1] The predictor set matters more than the learning algorithm in most published comparisons. Ceiling, runway visual range, dew point depression and boundary layer height carry most of the signal, while radiation terms add skill only during the evening transition when the boundary layer collapses rapidly.

[p.1] We therefore fit separate models for each forecast step rather than one model with the lead time as a feature, because the error structure changes with horizon and a single model tends to compromise between regimes that behave quite differently.

[p.1] Statistical post-processing offers a practical alternative. Instead of resolving the microphysics, it learns a mapping from predictors that are already available from the numerical model to the probability of the target event, using a long archive of historical observations as the training signal.

[p.1] The predictor set matters more than the learning algorithm in most published comparisons. Ceiling, runway visual range, dew point depression and boundary layer height carry most of the signal, while radiation terms add skill only during the evening transition when the boundary layer collapses rapidly.

[p.1] We therefore fit separate models for each forecast step rather than one model with the lead time as a feature, because the error structure changes with horizon and a single model tends to compromise between regimes that behave quite differently.

[p.1] Calibration is checked with reliability diagrams and the Brier decomposition. A model that is sharp but poorly calibrated is worse than a well calibrated model with the same area under the curve, because the operational decision threshold depends on the user.

### 2 Results

[p.2] The predictor set matters more than the learning algorithm in most published comparisons. Ceiling, runway visual range, dew point depression and boundary layer height carry most of the signal, while radiation terms add skill only during the evening transition when the boundary layer collapses rapidly.

[p.2] We therefore fit separate models for each forecast step rather than one model with the lead time as a feature, because the error structure changes with horizon and a single model tends to compromise between regimes that behave quite differently.

[p.2] Calibration is checked with reliability diagrams and the Brier decomposition. A model that is sharp but poorly calibrated is worse than a well calibrated model with the same area under the curve, because the operational decision threshold depends on the user.

[p.2] Missing predictors are imputed from the previous analysis cycle and flagged, so that the downstream consumer can decide whether a given forecast should be trusted at all.

[p.2] We therefore fit separate models for each forecast step rather than one model with the lead time as a feature, because the error structure changes with horizon and a single model tends to compromise between regimes that behave quite differently.

[p.2] Calibration is checked with reliability diagrams and the Brier decomposition. A model that is sharp but poorly calibrated is worse than a well calibrated model with the same area under the curve, because the operational decision threshold depends on the user.

[p.2] Missing predictors are imputed from the previous analysis cycle and flagged, so that the downstream consumer can decide whether a given forecast should be trusted at all.

[p.2] Visibility forecasting at airports is a hard problem because low-visibility events are rare, strongly stratified, and driven by interactions between radiative cooling, turbulence and advection that numerical models resolve only partially.

### 3 Results

[p.3] Calibration is checked with reliability diagrams and the Brier decomposition. A model that is sharp but poorly calibrated is worse than a well calibrated model with the same area under the curve, because the operational decision threshold depends on the user.

[p.3] Missing predictors are imputed from the previous analysis cycle and flagged, so that the downstream consumer can decide whether a given forecast should be trusted at all.

[p.3] Visibility forecasting at airports is a hard problem because low-visibility events are rare, strongly stratified, and driven by interactions between radiative cooling, turbulence and advection that numerical models resolve only partially.

[p.3] Statistical post-processing offers a practical alternative. Instead of resolving the microphysics, it learns a mapping from predictors that are already available from the numerical model to the probability of the target event, using a long archive of historical observations as the training signal.

[p.3] Missing predictors are imputed from the previous analysis cycle and flagged, so that the downstream consumer can decide whether a given forecast should be trusted at all.

[p.3] Visibility forecasting at airports is a hard problem because low-visibility events are rare, strongly stratified, and driven by interactions between radiative cooling, turbulence and advection that numerical models resolve only partially.

[p.3] Statistical post-processing offers a practical alternative. Instead of resolving the microphysics, it learns a mapping from predictors that are already available from the numerical model to the probability of the target event, using a long archive of historical observations as the training signal.

[p.3] The predictor set matters more than the learning algorithm in most published comparisons. Ceiling, runway visual range, dew point depression and boundary layer height carry most of the signal, while radiation terms add skill only during the evening transition when the boundary layer collapses rapidly.
