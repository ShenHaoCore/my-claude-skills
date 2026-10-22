# my-claude-skills

个人自研的通用型 AI Agent Skills，通过 [CC Switch](https://github.com/farion1231/cc-switch) 的技能仓库机制在多台电脑间同步与更新。

本仓库只收录**与具体公司/组织无关**的通用技能。涉及内部业务、内部文档、内部系统标识的技能不放在这里。

## 技能列表

| 技能 | 说明 |
| --- | --- |
| [`skills/extract-go-lib`](skills/extract-go-lib) | 把已有 Go 项目里的通用能力抽取成独立、可开源发布的 Go module 仓库；含通用性判定清单、去环境绑定清单、建仓结构模板、发布与验证清单。 |
| [`skills/dotnet-github-auto-update`](skills/dotnet-github-auto-update) | 给 .NET（WPF/WinForms）桌面应用接入以 GitHub Releases 为通道的应用内自动升级。 |

## 在 CC Switch 中使用

### 方式一：一键添加仓库（推荐）

在装了 CC Switch 的电脑上，用浏览器打开这个链接：

```
ccswitch://v1/import?resource=skill&repo=ShenHaoCore/my-claude-skills&branch=main
```

CC Switch 会弹出导入确认框，点「导入」即可把本仓库加进技能仓库列表。**这一步只添加仓库，不会自动安装技能。**

### 方式二：手动添加仓库

1. 打开 **Skills → ⋯ → 仓库管理 → 添加仓库**
2. 仓库填 `ShenHaoCore/my-claude-skills`，分支 `main`，技能路径留空（扫描整个仓库）
3. 切到 **发现** 视图，搜到技能后点「安装」，选择要启用的应用（Claude Code / Codex / …）

安装后技能主副本在 `~/.agents/skills/`，各应用目录通过软链引用。页头「检查更新」即可拉到本仓库的新版本。

> **注意**：若本机已存在同名的本地技能（`local:` 来源），安装会报 `SKILL_DIRECTORY_CONFLICT`。
> 先在「已安装」里卸载旧版本（会自动备份到 `~/.cc-switch/skill-backups/`），再从本仓库安装。

## 目录结构约定

```
skills/<技能名>/SKILL.md
```

CC Switch 递归扫描 `SKILL.md`，并用**末级目录名**作为安装目录名，因此技能目录名一旦发布就不要再改，否则会被视为另一个技能。

## License

MIT，见 [LICENSE](LICENSE)。
