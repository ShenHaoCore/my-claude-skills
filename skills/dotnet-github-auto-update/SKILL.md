---
name: dotnet-github-auto-update
description: 给 .NET（WPF/WinForms）桌面应用接入以 GitHub Releases 为通道的应用内自动升级：Autoupdater.NET 接 GitHub API JSON（不托管 AppCast XML）、tag 驱动的版本号、启动静默检查 + 手动检查双路径、以及无需点界面的验证方法。触发词：自动升级、自动更新、应用内更新、Autoupdater.NET、AutoUpdater.Start、AppCast、GitHub Releases 升级、auto update、check for updates、软件升级配置。
agent_created: true
---

# .NET 桌面应用 + GitHub Releases 自动升级

## 适用场景

桌面应用（WPF/WinForms，含单文件自包含发布）需要「检查新版本 → 下载 → 就地覆盖 → 重启」，
且用 GitHub Releases 当发布通道（私有服务器/CDN 不需要）。

## 一、决策：别自己造轮子，也别硬凑 XML

- **下载 + 覆盖安装**用 `Autoupdater.NET.Official`（NuGet，MIT）。它会把 `<url>` 指向的 **zip 解压覆盖程序目录**，
  自带 `ZipExtractor.exe`（先等同名进程退出，再解压，再重启）。
- **AppCast 别去托管 XML**：订阅 `AutoUpdater.ParseUpdateInfoEvent`，在回调里解析任意格式（这里是 GitHub JSON），
  直接指向 `https://api.github.com/repos/{owner}/{repo}/releases/latest`。

```csharp
AutoUpdater.ParseUpdateInfoEvent += args =>
{
    // args.RemoteData 是接口返回的原始文本
    if (!TryParse(args.RemoteData, out var release, out _)) return;  // 留空 = 按检查失败处理（ReportErrors=false 时静默）
    args.UpdateInfo = new UpdateInfoEventArgs
    {
        CurrentVersion = release.Version.ToString(),   // string！库内部 new Version(CurrentVersion) 再比较
        DownloadURL = release.DownloadUrl,
        ChangelogURL = release.ChangelogUrl,
        Mandatory = new Mandatory { Value = false }
    };
};
```

订阅了该事件后，库**不再**走内置 XmlSerializer；**处理器不设 `args.UpdateInfo` 会抛 `MissingFieldException`**。

## 二、必备配置（少一条就踩坑）

```csharp
AutoUpdater.InstalledVersion = typeof(MyAppService).Assembly.GetName().Version; // 单文件发布下显式给版本更稳
AutoUpdater.AppTitle = "MyApp";
AutoUpdater.HttpUserAgent = "MyApp-Updater/1.0";  // GitHub 不带 UA 直接 403（库里是 Headers[UserAgent]=null 会移除该头）
AutoUpdater.RunUpdateAsAdmin = false;             // 默认 true → 每次升级弹 UAC；装用户目录时不需要
AutoUpdater.PersistenceProvider = new JsonFilePersistenceProvider(path);  // 默认写注册表；这样「跳过/稍后」落在自己的数据目录
```

## 三、双路径：启动静默 + 手动检查（不要都用 `AutoUpdater.Start`）

`AutoUpdater.Start` 有重入与状态守卫：`if (Running || _remindLaterTimer != null) return;`
——用户上次点了「稍后提醒」，或已有一次检查在跑时，它**直接返回且不触发任何回调**，
手动检查会表现为「点了没反应」。所以：

| 路径 | 实现 | 理由 |
|---|---|---|
| 启动静默检查 | `AutoUpdater.Start(apiUrl)`（默认 `ReportErrors=false`，失败静默） | 白拿「稍后提醒 / 跳过此版本」按钮与状态持久化 |
| 手动检查 | 自己的 `HttpClient` 拉同一 URL → 自己解析比较 → 自己弹 WPF 对话框 | 一定能给用户明确答复（最新/有新版本/失败） |
| 下载安装 | 自己构造 `UpdateInfoEventArgs` → `AutoUpdater.DownloadUpdate(args)` → 成功后 `Application.Current.Shutdown()` | 两个入口共用一套下载/解压 |

其他要点：
- `AutoUpdater.Start` **必须在 UI 线程**调用（内部 `Application.EnableVisualStyles()` + STA 判断）；它本身用
  `BackgroundWorker` 异步执行，不会阻塞。
- `AutoUpdater.SetOwner(Application.Current?.MainWindow)`（库内部会用 `Wpf32Window` 包装 WPF Window）让弹窗跟随主窗。
- 升级前先探测程序目录可写（一次性探测文件），不可写就别走下载，改为提示并打开 Release 页面。

## 四、版本号：tag 是唯一真相

- csproj 里给一个本地基线 `<Version>0.1.0</Version>`；发布时用 `-p:Version=<tag去掉v>` 覆盖。
- **标签格式固定 `v<major>.<minor>.<patch>`**，workflow 里校验；版本不对就 fail，别等客户端算不明白。
- 解析 tag 时**补齐到 4 段**（`0.2.0` → `0.2.0.0`）：`new Version("0.2.0")` 的 Build=-1，
  与已装的 `0.2.0.0` 比较会判成「更小」，导致刚发布就检测不到更新。

## 五、发版流程：Release 只在推 tag 时跑

两个工作流的触发条件必须分清，否则很容易误以为「CI/Release 没触发」：

| 工作流 | 触发条件 | 说明 |
|---|---|---|
| `.NET CI` | `push: branches:[main]` + PR + `workflow_dispatch` | 推 main 就跑 |
| `Release` | `push: tags:['v*']` | **推 main 永远不跑**，只有打标签才跑 |

「Release 没触发」九成原因是**没打标签**，与改动多少无关。排查：

```bash
gh run list --workflow=release.yml --limit 3 --json headBranch,status,conclusion,event
# headBranch 显示成 tag 名（如 v0.2.0）才说明是标签触发的那一次；显示 main 的必然是 CI
```

⚠️ **Actions 有 5~15 秒注册延迟**：push 完立刻刷新网页会看到空列表，容易误判「没触发」
（实测提交后 8 秒才出现运行条目）。`gh run list --commit <sha>` 在刚 push 时也可能查不到，
拿到 run id 后用 `gh run watch <id>` 更可靠。

**推荐顺序（否则可能把一个 CI 红的版本发布出去）**：

1. 改完 → `git push origin main`
2. 等 CI 绿 → `gh run watch <id>`
3. `git tag -a v0.2.0 -m "..."`（与首发一致用**附注 tag**）
4. `git push origin v0.2.0` → Release 自动跑

csproj 的 `<Version>` 记得同步 bump：它只是**本地构建基线**（发布产物版本由 `-p:Version=<tag>` 注入），
但两者不一致会让本地 build 的版本号落后于线上，排查时容易误判。

### ⚠️ 发行说明别用 `generate_release_notes`

`softprops/action-gh-release` 的 `generate_release_notes: true` **只统计「通过 PR 合并」的改动**。
如果仓库是**直接推 main** 的开发方式，生成的发行说明会**只剩一行 Full Changelog，正文全空**（实测踩过）。
自己读 git 历史生成更可靠，要点：

```powershell
# checkout 必须加 fetch-depth: 0，否则浅克隆下 git describe / git log 拿不到 tag 与历史
$prev = git describe --tags --abbrev=0 --match 'v*' "$tag^" 2>$null   # 失败 = 首个版本
$range = if ($prev) { "$prev..$tag" } else { $tag }
git log $range --no-merges --pretty=format:'- %s (`%h`)' --output=commits.txt
```

- **首个版本没有对比基准，不要倾倒整段仓库历史**（`git log <tag>` 会列出从仓库诞生起的全部提交，
  塞进「本次更新」纯属噪音）——降级成「首个公开版本」+ 一句简述。
- **`--output` 让 git 自己写文件**：在 Windows PowerShell 5.1 里用管道抓原生命令 stdout
  会按控制台代码页解码，**中文提交信息直接乱码**。落盘用 `New-Object System.Text.UTF8Encoding($false)`
  写成**无 BOM** UTF-8，再交给 `body_path`（带 BOM 会在正文开头留个不可见字符）。
- 顺带剔掉「版本号提升 / Bump version」这类对用户无意义的提交。
- 已经发出去的版本可以**立即回填**：`gh release edit <tag> --notes-file notes.md`。
- ⚠️ release.yml 的改动**CI 验不了**（它只认 tag 触发），本地按同样的 cwd 条件跑一遍两种分支再推。

### 发行说明的实际展示位：库弹窗里的「内嵌浏览器」

`UpdateInfoEventArgs.ChangelogURL` 不是一条链接那么简单——库的 `UpdateForm`（`AutoUpdater.Start`
弹出「发现新版本」的那个窗）会**内嵌浏览器直接加载它**：

```csharp
// UpdateForm.InitializeBrowserControl()
if (string.IsNullOrEmpty(_args.ChangelogURL)) {
    labelReleaseNotes.Hide(); webBrowser.Hide(); webView2.Hide();
    Height -= labelReleaseNotes.Height + webBrowser.Height;   // 没有说明区时弹窗变矮
} else {
    // 优先 WebView2（要求运行时版本 >= 86.0.616.0），否则回退到 IE 版 WebBrowser 控件
    webView2.CoreWebView2.Navigate(_args.ChangelogURL);
    // 回退分支： UseLatestIE(); webBrowser.Navigate(_args.ChangelogURL);
}
```

推论（都很实际）：

1. `ChangelogURL` 指向 Release 页面时，**用户在升级弹窗里看到的就是那个网页**（连同导航栏、下载链接、
   贡献者列表）。所以**发行说明写空 = 弹窗里一片空白**——这正是「发行说明感觉不对」的典型症状。
   回填 `gh release edit` 后立刻生效，不必发新版。
2. `.NET` 侧**没有**「传一段说明文本给弹窗」的口子（`UpdateInfoEventArgs` 无 `ReleaseNotes` 属性）；
   想显示纯文本说明只能自己写弹窗。解析 JSON `body` 存成字段是死数据，别指望库会渲染它。
3. **WebView2 不只是视频要用**：升级弹窗的说明区同样依赖它。缺运行时会回退到 IE 控件，
   现代 GitHub 页面在 IE 里基本渲染不出来（空白，但不崩）。系统要求里要一并写明。
4. 弹窗内嵌浏览器有独立用户数据目录（`Path.GetTempPath()`）并会 `ClearBrowsingDataAsync()`，
   里面点链接走内嵌浏览器而不是系统浏览器。
5. 手动检查路径是我们自己实现的（原生 MessageBox + 本地文案），**不加载任何网页**；
   只有「无法自动升级」的退路才用系统浏览器 `Process.Start` 打开发布页。
6. **别为发行说明另建一个专用网页**（这是常见的直觉，但被其他两个方案夹死）：
   换 URL 不会换掉内嵌浏览器控件，WebView2/IE 依赖、联网、滚动全都在，只多了托管与
   「每版同步两份内容」的漂移风险；而 GitHub Release 页本来就是说明页（标题+正文在顶部，
   且已随发版自动生成）。「换个域名更好访问」也不成立——检查更新本身就要访问
   `api.github.com`，连不上 GitHub 时说明托管在哪都没用。真要提升观感，正确方向是
   **应用内原生渲染**（顺带干掉浏览器依赖，且 `body` 已在同一次 API 响应里，零额外请求），
   代价是自写弹窗 + 轻量 Markdown 渲染；若连启动路径一起换掉，还得自己接管
   「稍后提醒 / 跳过此版本」的持久化（现在白拿库的）。

### 行业参照：同行到底怎么放这段说明

分两族，判据是**「更新是静默的还是用户点了才装」**：

- **事后回顾族（大厂）**：Chrome（`chrome://whats-new`，内置页，更新后开新标签）、
  VS Code（Help → Release Notes，编辑器里开一个标签，`update.showReleaseNotes` 控制）、
  JetBrains（更新到 major 后自动开 "What's New" 面板）。
  它们**没有「要不要升」的弹窗**——更新在后台静默完成，用户没参与，所以事后补一页讲变化。
  内容描述的是**你已经装上的那一版**，因此可以随应用打包。
- **事前预告族（Sparkle 血统）**：macOS Sparkle / WinSparkle / **AutoUpdater.NET（本库）** /
  Obsidian / 多数 Electron 应用。有确认弹窗，说明讲的是「你将得到的这一版」。
  官方给两种内容来源：`sparkle:releaseNotesLink`（**外部 HTML**，框架用 WebView 渲染）
  或 **appcast 内联**（`<description>` CDATA，Sparkle 支持 HTML / 纯文本 / 2.9 起支持 markdown）。
  内联那一路「无网络请求、无 JS」，是官方更推荐的方向。

两个**实测过的坑**（来自 Sparkle 生态的真实 issue，transferable）：

1. **说明区默认禁用 JavaScript**（Sparkle 2 的安全设计：feed 被劫持也不能在宿主里执行脚本）。
   所以把说明指向一个**靠 JS 渲染**的页面 = 永远白屏。真实案例：Qtraktor #61 把
   `releaseNotesLink` 指向自家营销站 `/#changelog`（该页客户端 fetch GitHub API），
   用户只看到永久停住的 "Fetching latest release…"，而下载/安装一切正常——纯观感故障，
   却「是唯一一个能告诉用户为什么值得升的界面，结果它什么也没说」。他们的修复=发布时
   把 changelog **内联进 appcast**。
   → 推论：**指向外部页时务必确认该页不依赖 JS**。GitHub Release 页是服务端渲染的，安全。
2. **指向 `/latest` 之类地址会造成「说明与所装版本不符」**：弹窗里的说明永远描述「最新版」，
   而不是用户正要装的那一版。**应指向版本专属地址**（如 `/releases/tag/v0.2.0`）。
   本库接 `/releases/latest` 取的是 `html_url`，天然是版本专属 URL，这一点是安全的。

补充细节：Sparkle 会给说明 HTML 注入 `sparkle-installed-version` class（标记用户当前已装版本），
配 CSS 就能把已装版本淡化或隐藏——成熟实现在「累积更新日志里哪几条与你有关」上是有讲究的。

## 六、资产匹配：宁可不更新，也不装错包

release workflow 里 zip 名字固定成 `<App>-<tag>-win-x64.zip`，客户端按后缀匹配。
**不要退化成「任意 zip 都行」**：实测多资产仓库（如 ripgrep）会把 aarch64 包排在前面，
宽松兜底会把 aarch64 装进 x64 程序。稳妥策略：

1. 名字以 `-win-x64.zip` 结尾 → 直接用；
2. 否则名字同时含 `win-x64` 且以 `.zip` 结尾 → 备选；
3. 都没有 → 报「该版本没有提供安装包」。

### ⚠️ 库判断「zip 还是安装器」用的是重定向后的响应文件名 —— GitHub 资产全靠 Content-Disposition

`DownloadUpdateDialog` 里 zip 判定是：

```csharp
string fileName = string.IsNullOrEmpty(contentDisposition?.FileName)
    ? Path.GetFileName(_webClient.ResponseUri.LocalPath)   // 兜底：看最终 URL 的路径
    : contentDisposition.FileName;                          // 优先：看 Content-Disposition
...
if (Path.GetExtension(tempPath).Equals(".zip", OrdinalIgnoreCase)) { /* ZipExtractor 覆盖 */ }
else if (... ".msi") { /* msiexec */ }
// 其它一切后缀 → 落到默认分支：Process.Start 直接运行下载的文件（裸 exe 只会起个新实例，不替换文件）
```

GitHub Releases 资产是 **302 → `release-assets.githubusercontent.com/...`（Azure blob）**，
最终 URL 的路径里**没有 `.zip` 后缀** —— 所以 zip 判定**完全依赖 `Content-Disposition`**。
实测（`curl -sSIL`）GitHub 会回：

```
Content-Disposition: attachment; filename=DotaInsight-v0.1.0-win-x64.zip
```

因此**不要在 release 里额外上传裸 `.exe` 当「方便用户」的第二个资产**：那不仅是 207MB（zip 后 85MB）的浪费，
更会让任何按名字/后缀取资产的逻辑变得含糊；升级**必须**走 zip。
自查方法：`curl -sSIL <资产直链>` 看最终 200 响应的 `Content-Disposition` 是否有 `.zip` 文件名。
（另外库对 `RunUpdateAsAdmin=false` 不会给下载文件加 `runas`，装用户目录时正好。）

## 七、验证（不需要点界面，也不需要真发版就能验一大半）

1. **解析逻辑单测**：手写 GitHub payload（含 `tag_name` / `html_url` / `body` / `draft` / `assets[]`），
   覆盖：正常、缺 zip、跨架构 zip、draft、脏 JSON、tag 无 `v`、版本比较边界（相等不算更新）。
2. **确认真实 payload 的字段名**：`GET /repos/{o}/{r}/releases/latest` 直接把 JSON 打出来核对（别凭记忆写字段）。
3. **在离屏工具里跑真实链路**并订阅 `CheckForUpdateEvent` 拦下弹窗：
   - 手动路径：直接调自己的 `CheckAsync`（`Task.Run(...).GetAwaiter().GetResult()`）。
   - 启动路径：`AutoUpdater.Start(apiUrl)`，然后**一边 `Dispatcher.PushFrame` 泵消息一边轮询回调结果**——
     库的回调 post 到 UI 线程，`ManualResetEventSlim.Wait` 会把主线程堵死 → 假超时。
   - 想验「有更新」分支：把 `AutoUpdater.InstalledVersion` 设成更低的版本号即可（不必真装旧版）。
4. 没有 release 时接口返回 404：确认这条分支给的是友好提示而不是异常弹窗。
5. **首次发布后再验一遍「有更新」正分支（真实网络 + 真实资产）**：
   - `UiHarness.exe <out> updatecheck 0.1.0` —— 第二个参数**直接模拟「已装旧版」**，不必改 csproj 或重编译；
     期望「有更新=True」且下载/变更日志 URL 正确。再跑 `updatecheck`（不传参 = 真实程序集版本）
     期望「有更新=False」，确认无假阳性。
   - **务必核对发布产物的版本号**（本机制最致命的隐患：产物版本号错 → 客户端静默永不更新；
     若产物报的版本低于 tag，装上新版的用户还会被反复提示升级，形成死循环）。
   - 元数据核对用 `gh api repos/{owner}/{repo}/releases/latest`：比 curl 省事，且走 gh 自带 TLS
     不受本机 schannel 问题影响；核对 `tag_name`、`draft`/`prerelease`、`assets[].name` 是否符合后缀匹配规则。
   - **产物版本号不必下完整个 zip**（85MB 在本机 40 分钟都下不完）。资产直链慢，但**前 ~10MB 就够**：
     zip 里只有一个 `DotaInsight.exe`（deflate），把已下载的压缩字节喂给 `zlib.decompressobj(-15)`
     流式解出**前缀**（约 1:2 膨胀，10MB 压缩 → 20MB 原始，足够覆盖 PE 头与 `.rsrc` 段），
     再到解出的数据里按 UTF-16LE 找 `FileVersion` / `ProductName` 字符串。
     ⚠️ **单文件产物内嵌了 .NET 运行时组件，`.rsrc` 里有十几个版本资源块**——必须按
     `ProductName == 自己的应用名` 过滤，别取第一个匹配（第一个永远是 `Microsoft® .NET`）；
     `StringFileInfo` 按字母序排列，`FileVersion` 在 `ProductName` **之前**，要向前回看。
     可直接复用 `references/peek-release-version.py`（参数：zip 路径 + 应用名）。
     ⚠️ **只对 `PublishSingleFile` 的产物好用**：single-file 把托管负载追加在 PE 段之后，
     `.rsrc` 落在文件开头约 4% 处（216MB 产物里偏移 0x7E0200），下 10% 就够；
     普通原生 exe / 框架依赖 apphost 的 `.rsrc` 压在文件末尾，按比例截断到不了，脚本会明确提示「超出前缀」。
     不想等慢速下载时，可用 CI 同款 `dotnet publish` 命令本地产出单文件 exe 造夹具离线验证。

## 八、剩下的只能真机验

下载 + 解压覆盖 + 重启这三步无法离线验证：需要仓库里真的有一个 release。
第一次真升级时要看：程序退出后 exe 是否真被替换（版本号变化）、应用是否自动重启、
数据目录（%LocalAppData%）是否完好。

## 九、本机环境备注（Windows 沙箱）

- `curl` 访问 github.com 常报 `schannel: CRYPT_E_NO_REVOCATION_CHECK`（本机 schannel 无法做吊销检查）；
  加 `--ssl-no-revoke` 可绕过。**更省事的做法是改用 `gh api` / `gh release view`**——它们走 gh 自带 TLS，
  完全不受这个问题影响，纯元数据核对一律优先用 gh。
- **GitHub release 资产直链在本机极慢/易 502**（85MB 单文件产物下了 40+ 分钟未完）。
  需要大产物时优先 `gh release download`，并准备好重试；纯元数据核对用 API 即可，不必下整包；
  实在要验产物内容就用上面「只解压前缀」的办法。
- `gh` CLI 用 Git Credential Manager 里那份 `gho_` 令牌，通常可直接用（见用户级 MEMORY.md 的自救法）。
