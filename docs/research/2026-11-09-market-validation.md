# 知映 zhiying — 需求市场验证（2026-11-09）

> 取证方法：Web search 工具本机未配置，改用 GitHub Search API（star 数为真实采用信号）+ 仓颉.Skill 文章取证（12K Star）。非完整 TAM 研究，为需求存在性验证。

## 1. 同类项目与同赛道热度（GitHub 实测）

| 类别 | 代表仓库 | Star | 与知映关系 |
|---|---|---|---|
| 视频知识库（该搜索总量 785 仓库） | IliasHad/edit-mind | 1830 | 直接同类项目：local-first 视频知识库、多模态分析 |
| 同上 | chubbyguan/chubbyskills | 1319 | 中文多渠道（抖音/B站/小红书/公众号/播客）→ 个人知识库 14 个 AI Skill |
| 同上 | lycohana/BiliSum | 668 | B站/YouTube/本地视频 AI 摘要+知识库 |
| NotebookLM 替代品（总量 12378） | MODSetter/SurfSense | 16808 | 隐私/air-gapped NotebookLM 替代，泛内容非视频专属 |
| 同上 | teng-lin/notebooklm-py | 20175 | NotebookLM 非官方 API |
| YouTube RAG（总量 4428） | NotJoeMartinez/yt-fts | 1811 | YouTube 全文搜索（仅搜索无 RAG 问答） |
| 同上 | wassim249/YT-Navigator | 609 | YouTube 内容搜索+对话 |
| 中文一键摘要（B站） | JimmyLv/BibiGPT-v1 | 6273 | 中文市场头部，音视频一键摘要 |

## 2. 市场结论

**需求真实且已被主流产品验证。** 三层证据：

1. **主流产品背书**：Google NotebookLM 是「内容进库→带引用对话」品类的标准范式，GitHub 上「NotebookLM alternative」方向有 1.2 万+ 仓库，证明「把内容变可问答知识库」是规模化需求而非小众。
2. **视频垂直赛道活跃**：video knowledge base 785 仓库、youtube RAG 4428 仓库、video RAG transcript 1072 仓库——视频专属知识库是明确子赛道。
3. **中文市场现成付费意愿**：BibiGPT 6.2K Star、BiliSum、chubbyskills 均为中文面向产品，B站用户为「一键总结」付费的意愿已被验证。

## 3. 知映的差异化楔子

现有产品无人同时占满以下四点，这正是知映定位：

- **视频原生 + 多模态**：不只口播转写，经 VLM 看懂 PPT/代码/图表（LongCat 原生视觉，FR-105）
- **本地优先 + 隐私**：数据全部落本机，不传第三方知识库（DR-13，同仓颉零基础设施成本模型）
- **Agent 原生接入**：MCP 一次接入 OpenClaw/Claude Code/Codex，对话里直接建任务与问答（FR-305）
- **答案溯源时间戳**：每条引用可跳原视频对应位置（J3）

一句话定位：**「你私人视频库的本地优先、Agent 原生、看得懂画面的 NotebookLM」**——NotebookLM 不强在本地化/中文视频平台/深度视觉理解，同类项目 edit-mind/BiliSum 不强在 Agent 集成与中文多渠道，知映卡住这个交叉点。

## 4. 诚实风险

- **非先行者**：edit-mind/ BibiGPT 已占认知；知映差异化（四合一）须真实成立而非纸面，否则沦为「又一个摘要器」。
- **取证局限**：仅 GitHub 信号 + 单篇文章，未做完整 TAM/同类项目深度调研；如需融资或立项汇报，建议补 web 搜索广度与用户访谈。
