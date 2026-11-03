# 05: Open Targets 接入

**What to build:** 文献检索阶段在检索文献之外，查询 Open Targets 的疾病-靶点关联与靶点-药物关联，使「共病 → 通路 → 靶点」的推导有结构化证据。假设生成阶段产出的靶点假设可以引用 Open Targets 证据，报告的证据链中可见这些证据。

**Blocked by:** 04

**Status:** resolved

- [x] Open Targets 作为外部来源接口的第四个适配器接入，复用 04 的本地缓存机制
- [x] 靶点假设可同时引用 PMID 与 Open Targets 证据，两者在报告中区分显示
- [x] 引用校验同样适用于 Open Targets 证据：只能引用本轮实际查询到的条目
- [x] 靶点假设写明在数据中检验所用的代理指标（例如作用于该靶点的现有药物暴露）

## Comments

- 2026-11-03 已实现并在 Mac 上调试通过。使用 Open Targets GraphQL：disease.associatedTargets 与 target.drugAndClinicalCandidates。
