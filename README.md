# Journal Daily Tracker

每日自动抓取顶刊文章，过滤出**电池、电子显微镜、二维材料、材料科学**相关论文，用 GLM-4-Flash 生成双语摘要，推送到 GitHub 并同步 Obsidian。

## 覆盖期刊

| 系列 | 期刊 |
|------|------|
| Nature | Nature · Nature Chemistry · Nature Materials · Nature Physics · Nature Energy · Nature Nanotechnology · Nature Synthesis · Nature Communications · Nature Sustainability · Nature Water |
| Science | Science · Science Advances |
| ACS | JACS · Nano Letters · ACS Energy Letters |
| Wiley | Angewandte Chemie · Advanced Materials |

## 功能

- 每日 09:00（北京时间）自动运行 GitHub Actions
- RSS 优先抓取当日文章，若无则用 CrossRef API 向前查找（最多 30 天）
- 每个期刊**至少保证 1 篇**相关文章（使用近期精选作为兜底）
- GLM-4-Flash 生成：中文标题、核心价值、关键词、双语对照摘要
- Markdown 存入本仓库 `output/{year}/{date}.md`
- 同步推送至 Obsidian vault 仓库 `10_Journals/daily-papers/{year}/{date}.md`

## 快速开始

### 1. Fork 或创建仓库

将本项目推送到你的 GitHub（例如 `hugl2030/journal-daily-tracker`）。

### 2. 配置 Secrets

在 GitHub 仓库 Settings → Secrets and variables → Actions 中添加：

| Secret | 说明 |
|--------|------|
| `ZHIPUAI_API_KEY` | 智谱 AI 的 API Key（[申请地址](https://open.bigmodel.cn/)） |
| `OBSIDIAN_SYNC_TOKEN` | GitHub Personal Access Token（需要 `repo` 权限） |
| `OBSIDIAN_REPO` | Obsidian vault 仓库名，如 `hugl2030/my-obsidian-vault` |

### 3. 本地测试

```bash
cp .env.example .env
# 填写 .env 中的 ZHIPUAI_API_KEY

pip install -r requirements.txt

# 抓取昨天的文章
python main.py

# 指定日期
python main.py --date 2026-04-18

# 不调用 LLM（快速测试）
python main.py --no-llm --verbose
```

### 4. Obsidian 同步

Workflow 会自动将生成的 Markdown 推送到 `OBSIDIAN_REPO`，路径为：

```
10_Journals/
└── daily-papers/
    ├── latest.md          ← 最新一期（方便 Obsidian 快速打开）
    └── 2026/
        ├── 2026-04-18.md
        └── 2026-04-19.md
```

在 Obsidian 中开启 `Obsidian Git` 插件自动 pull 即可实时同步。

## 自定义

- **修改关键词**：编辑 `config.yaml` 中的 `topics` 部分
- **调整期刊列表**：编辑 `config.yaml` 中的 `journals` 部分
- **修改推送时间**：编辑 `.github/workflows/daily_journal.yml` 中的 cron 表达式
- **每刊文章数量**：修改 `main.py` 中 `selected = matched_today[:2]` 的数字
