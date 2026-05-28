# MkDocs + Material 文档网站搭建指南

> 最后更新日期：2026-05-28

---

## 1. 方案概览

本方案基于 **MkDocs** + **Material for MkDocs** 主题，为 `hllrcon` 构建静态文档网站，并托管于 **GitHub Pages**。文档内容与源码仓库同步，通过 GitHub Actions 实现推送即部署（Push-to-Deploy）。

**选型理由**：
- **MkDocs** 是 Python 生态标准文档生成器，与项目技术栈天然契合。
- **Material 主题** 提供现代化 UI、响应式布局、搜索、暗色模式与代码高亮，开箱即用。
- **GitHub Pages** 免费、免运维，与现有 GitHub Actions CI 无缝集成。
- **uv** 管理依赖与构建命令，保持与现有开发工作流一致。

---

## 2. 目录结构预览

```text
hllrcon/
├── docs/                        # 新增：文档站点源文件
│   ├── index.md                 # 首页（由 README.md 软链或复制）
│   ├── architecture.md          # 架构文档（由 plans/architecture.md 软链或复制）
│   ├── stylesheets/
│   │   └── extra.css            # 可选：自定义样式
│   └── assets/                  # 可选：图片、Logo 等静态资源
├── mkdocs.yml                   # 新增：MkDocs 配置
├── .github/workflows/
│   └── docs.yaml                # 新增：文档构建与部署工作流
└── pyproject.toml               # 修改：追加 docs 依赖组
```

---

## 3. 分步实施

### 步骤 1：添加依赖

在 `pyproject.toml` 中新增 `docs` dependency group（与现有 `dev` 并列）：

```toml
[dependency-groups]
dev = [
    "aiofiles>=24.1.0",
    "mypy>=1.16.0",
    "pytest>=8.3.5",
    "pytest-asyncio>=1.0.0",
    "pytest-cov>=6.1.1",
    "pytest-mock>=3.14.1",
    "python-dotenv>=1.1.1",
    "ruff>=0.12.0",
    "ty>=0.0.23",
    "types-aiofiles>=24.1.0.20250606",
]
docs = [
    "mkdocs>=1.6.0",
    "mkdocs-material>=9.5.0",
    "pymdown-extensions>=10.8.0",
    "mkdocs-minify-plugin>=0.8.0",
]
```

同步锁文件：

```bash
uv sync --group docs
```

### 步骤 2：创建 MkDocs 配置

在仓库根目录创建 `mkdocs.yml`：

```yaml
site_name: hllrcon
site_description: Asynchronous Python implementation of the Hell Let Loose RCON protocol
site_author: Tim Raaymakers
site_url: https://timraay.github.io/hllrcon/

repo_name: timraay/hllrcon
repo_url: https://github.com/timraay/hllrcon
edit_uri: edit/main/docs/

theme:
  name: material
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: indigo
      accent: indigo
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      primary: indigo
      accent: indigo
      toggle:
        icon: material/brightness-4
        name: Switch to light mode
  features:
    - navigation.instant
    - navigation.tracking
    - navigation.sections
    - navigation.expand
    - navigation.top
    - search.suggest
    - search.highlight
    - content.code.copy
    - content.action.edit
  icon:
    repo: fontawesome/brands/github

plugins:
  - search
  - minify:
      minify_html: true

markdown_extensions:
  - admonition
  - pymdownx.details
  - pymdownx.superfences
  - pymdownx.highlight:
      anchor_linenums: true
      line_spans: __span
      pygments_lang_class: true
  - pymdownx.inlinehilite
  - pymdownx.snippets
  - pymdownx.tabbed:
      alternate_style: true
  - tables
  - toc:
      permalink: true

extra_css:
  - stylesheets/extra.css

nav:
  - Home: index.md
  - Architecture: architecture.md

watch:
  - docs
```

> **说明**：
> - `site_url` 需替换为你的 GitHub Pages 实际地址（`https://<user>.github.io/<repo>/`）。
> - `nav` 当前仅包含首页与架构文档；后续可扩展 API Reference、Changelog 等页面。

### 步骤 3：准备文档源文件

创建 `docs/` 目录并纳入现有文档：

```bash
mkdir -p docs/stylesheets docs/assets

# 方式 A：软链接（推荐，单源 truth）
# Windows Git Bash / WSL / Linux / macOS
ln -s ../README.md docs/index.md
ln -s ../plans/architecture.md docs/architecture.md

# 方式 B：复制（若 CI 或 Pages 构建环境不支持 symlink）
# cp README.md docs/index.md
# cp plans/architecture.md docs/architecture.md
```

创建自定义样式文件 `docs/stylesheets/extra.css`（可选）：

```css
/* 示例：调整代码块字体 */
code {
  font-feature-settings: "liga" 1;
}
```

### 步骤 4：本地预览

```bash
# 启动开发服务器，监听文件变更并自动刷新
uv run mkdocs serve

# 访问 http://127.0.0.1:8000/hllrcon/ 预览
```

若使用方式 B（复制文件），建议在 `scripts/generate_sync_commands.py` 同级增加一个本地同步脚本，或在 CI 中执行复制步骤，避免文档与源文件不同步。

### 步骤 5：创建 GitHub Actions 工作流

创建 `.github/workflows/docs.yaml`：

```yaml
name: Documentation

on:
  push:
    branches: [master]
    paths:
      - "docs/**"
      - "mkdocs.yml"
      - "README.md"
      - "plans/architecture.md"
      - ".github/workflows/docs.yaml"
  pull_request:
    branches: [master]
    paths:
      - "docs/**"
      - "mkdocs.yml"
      - "README.md"
      - "plans/architecture.md"
      - ".github/workflows/docs.yaml"

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version-file: "pyproject.toml"

      # 若采用复制方式（非 symlink），取消下面注释
      # - name: Sync docs
      #   run: |
      #     cp README.md docs/index.md
      #     cp plans/architecture.md docs/architecture.md

      - name: Build site
        run: uv run mkdocs build --strict

      - name: Upload artifact
        if: github.event_name == 'push'
        uses: actions/upload-pages-artifact@v3
        with:
          path: site/

  deploy:
    if: github.event_name == 'push'
    needs: build
    runs-on: ubuntu-latest
    permissions:
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

> **关键设计**：
> - `paths` 过滤：仅在文档相关文件变更时触发构建，避免浪费 CI 时间。
> - `--strict`：MkDocs 遇到警告即失败，防止断链或导航错误被静默忽略。
> - `concurrency: group: pages`：防止多个推送同时部署导致 Pages 状态竞争。

### 步骤 6：启用 GitHub Pages

1. 打开仓库 **Settings** → **Pages**。
2. **Source** 选择 **GitHub Actions**。
3. 无需手动创建分支，工作流会自动处理 `gh-pages` 分支的部署。

### 步骤 7：验证与提交

```bash
git add pyproject.toml mkdocs.yml docs/ .github/workflows/docs.yaml
# 若使用复制方式而非 symlink，确保提交的是实际文件
git commit -m "docs: setup MkDocs with Material theme and GitHub Pages deploy"
git push origin master
```

推送后，在 **Actions** 标签页查看 `Documentation` 工作流执行情况。成功后访问 `https://<user>.github.io/hllrcon/` 即可查看在线文档。

---

## 4. 后续扩展建议

| 扩展项 | 说明 | 依赖 |
|--------|------|------|
| **API Reference** | 自动从代码 Docstring 生成 API 文档 | `mkdocstrings[python]` |
| **Changelog** | 从 Git 提交或 Release 自动生成变更日志 | `mkdocs-git-revision-date-localized-plugin` |
| **多版本文档** | 同时展示多个版本的文档（如 `latest` + `stable`） | `mike` |
| **Mermaid 图表** | 本架构文档中的 Mermaid 图需插件支持渲染 | `mkdocs-mermaid2-plugin` |
| **搜索增强** | Material 主题已内置搜索，无需额外配置 | — |

### 接入 mkdocstrings 示例

在 `pyproject.toml` 追加：

```toml
docs = [
    "mkdocs>=1.6.0",
    "mkdocs-material>=9.5.0",
    "pymdown-extensions>=10.8.0",
    "mkdocs-minify-plugin>=0.8.0",
    "mkdocstrings[python]>=0.25.0",
]
```

在 `mkdocs.yml` 追加：

```yaml
plugins:
  - search
  - minify:
      minify_html: true
  - mkdocstrings:
      default_handler: python
      handlers:
        python:
          paths: [hllrcon]
          options:
            docstring_style: google
            show_source: true
            show_root_heading: true
```

在 `nav` 中新增：

```yaml
nav:
  - Home: index.md
  - Architecture: architecture.md
  - API Reference:
      - Client: api/client.md
```

创建 `docs/api/client.md`：

```markdown
# Client API

::: hllrcon.rcon.Rcon
```

---

## 5. 故障排查

| 现象 | 排查步骤 |
|------|---------|
| `mkdocs serve` 报 `FileNotFoundError` | 检查 `docs/index.md` / `docs/architecture.md` 是否存在（ symlink 是否正确解析）。 |
| GitHub Actions 构建成功但 Pages 404 | 确认仓库 **Settings → Pages → Source** 已切换为 **GitHub Actions**；检查 `site_url` 是否与 Pages 实际地址一致。 |
| 部署冲突 / 排队 | `concurrency` 已配置；若仍出现，手动取消旧的 Actions run 后重试。 |
| 代码块无高亮 | 确认 `pymdownx.highlight` 已加入 `markdown_extensions`，且 `pygments` 已随依赖安装。 |
| Mermaid 图不渲染 | 需安装并配置 `mkdocs-mermaid2-plugin`；或改用本地图片替代。 |

---

## 6. 最小可运行配置清单

若需最快速上线，仅需以下 3 个文件改动即可：

1. `pyproject.toml` → 追加 `docs` dependency group。
2. `mkdocs.yml` → 如步骤 2 所示。
3. `.github/workflows/docs.yaml` → 如步骤 5 所示。

然后执行：

```bash
mkdir -p docs
cp README.md docs/index.md
cp plans/architecture.md docs/architecture.md
uv sync --group docs
uv run mkdocs serve   # 本地验证
git add . && git commit -m "docs: init MkDocs site" && git push
```

GitHub Actions 将自动完成构建与部署。
