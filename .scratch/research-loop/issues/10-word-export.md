# 10: Word 导出

**What to build:** 研究者能把累积报告导出为 Word 文档，用于项目申报和汇报材料。导出内容与 HTML 报告一致，图表以图片形式嵌入。

**Blocked by:** 09

**Status:** resolved

- [x] 一条命令把指定运行目录的报告导出为 Word
- [x] 进展区和每轮章节的结构、表格、图表、结论与 HTML 报告一致
- [x] 文献列表保留英文原题与 PMID

## Comments

- 2026-11-03 已实现并在 Mac 上调试通过。每次渲染报告时自动生成 研究报告.docx，无需单独操作；也可用 agentloop report 重新生成。
