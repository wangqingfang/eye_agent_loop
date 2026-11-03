# 04: 文献来源接入与引用校验

**What to build:** 文献检索阶段围绕本轮表型发现，真实检索 PubMed、Europe PMC 和 ClinicalTrials.gov。结果按 PMID（或各来源唯一 ID）本地缓存，先取摘要，对排名前 k 且开放获取的文献再取全文。假设进入审稿前，剔除引用了本轮检索结果之外 PMID 的部分，并在报告中标注被剔除的引用及原因。

**Blocked by:** 01

**Status:** resolved

- [x] 三个来源各有适配器，统一实现外部来源接口
- [x] 同一 PMID 第二次请求命中本地缓存，不发起网络请求
- [x] 只对开放获取文献取全文，其余只用摘要
- [x] 主接缝测试：引用了本轮检索结果之外 PMID 的假设部分被剔除，报告中可见剔除记录
- [x] 外部来源请求失败时，本阶段记录失败并继续，不中断研究轮次
- [x] 报告中文献保留英文原题与 PMID

## Comments

- 2026-11-03 已实现并在 Mac 上调试通过。在当前网络下 PubMed E-utilities 返回 302（被 NCBI 拒绝），已按失败记录并继续；Europe PMC 限定 SRC:MED，仍能拿到 PMID。可在配置中填 NCBI_API_KEY。
