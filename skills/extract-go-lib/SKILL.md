---
name: extract-go-lib
description: 把已有（往往是公司的）Go 项目里的通用能力，抽取成独立、可开源发布的 Go module 仓库；也覆盖更轻的场景——把整个内网项目复制成一份自己留存的干净副本、把已有仓迁移到新路径。含通用性判定清单、去环境绑定清单、建仓结构与工程文件模板、go.mod 版本收敛、适配层的真实传输验证、发布到 GitHub 的完整流程（模块路径对齐 / noreply 署名 / tag 与 Release / 外部 go get 验证），以及一份经过验证的验证清单。触发词：抽取 Go 库、独立成仓、开源 Go module、去公司化、extract go lib、把这块抽出来、给库加 gRPC/HTTP 适配、推送到 GitHub、把脚手架自己留一份、留个副本、去公司痕迹、迁移仓库、移动到新路径。
version: "1.7.2"
license: MIT
display_name: 抽取独立 Go 库
display_name_en: Extract a Standalone Go Library
description_zh: 把已有 Go 项目里的通用能力抽取成独立可发布的 Go module 仓库，含判定清单、脱敏清单、建仓模板与验证步骤。
description_en: Extract general-purpose capabilities from an existing Go project into a standalone, publishable Go module repository, with checklists for generality, de-identification, repo scaffolding and verification.
---

# 抽取独立 Go 库

**判据一句话**：抽出来的包，能不能被一个不用原项目任何东西的工程 `go get` 之后跑起来？
不能就不是"抽取"，只是"复制"。

## 何时用

- 用户说"把 X 抽出来 / 独立成仓 / 做成我自己的项目 / 开源出去"
- 要把散在业务仓里的基建（错误码、日志、链路、鉴权、配置）产品化
- 注意：**先确认原项目是否有职务作品约束**，提醒用户"重写机制"而非搬运 git 历史

## 变体：只想要「一份自留副本」（不抽库、不发布）

用户说"我只是想把 XX 自己留一份"时，**不要自动升级成抽库 / 多 module / 开源品牌**——
先复制整仓 + 去痕量即可。这种仓往往本来就接近中立（因为作者已经是照着"能对外"来写的）。

先跑体检表，别凭印象：

```bash
head -3 go.mod                          # 模块路径是否已中性（不是 company.com/xxx）
grep -rn -iE "AK=|SK=|secretkey|password[=:]" --include="*.yaml" --include="*.example" .   # 真实凭证
grep -rn -E "公司域名|内网IP|真实实例ID|真实项目名" .                                        # 痕量
git remote -v && git log -1 --format='%an <%ae>'   # 来源与署名
```

行尾**必须用字节数**——`awk '/\r/'` 在 Windows 上会静默失效（文本模式吞掉 CR，永远返回 0），
`grep -c $'\r'` 反而可用：

```bash
python -c "import pathlib;b=pathlib.Path('Makefile').read_bytes();print('CRLF=',b.count(b'\r\n'))"
```

内网项目常见**混合行尾**（Makefile/tpl 是 CRLF、Go 源码是 LF）。
统一成 LF 是改进（CRLF 的 Makefile 在 WSL/Linux/CI 上会报 missing separator），
但这会改到几十个文件——**做了就要能说清楚**。

统一之后**还可能被自己弄回去**：Python 的 `Path.write_text()` / `open(...,'w')` 默认
`newline=None`，在 Windows 上把 `\n` 翻译成 `\r\n`——一个批量改注释的脚本就能让
整文件回到 CRLF，然后 `gofmt -l` 报「文件未格式化」，看起来像缩进问题。
**脚本化批量编辑一律用二进制**：

```python
b = p.read_bytes()
p.write_bytes(b.replace(old_bytes, new_bytes))
```

收尾再扫一次：

```bash
python -c "
import pathlib
for p in pathlib.Path('.').rglob('*'):
    if p.is_file() and '.git' not in p.parts and b'\r\n' in p.read_bytes():
        print('CRLF:', p)"
```

自留动作（最小集，原目录**只读不动**）：

1. 复制后**核对文件数**——`cp -r src dst` 在 dst 已存在时会变成 `dst/src/` 嵌套
2. 删 `.git`（不带原仓历史，其提交署名常是公司邮箱）。
   **但目标路径若已是个空仓**（`git init` + `origin` 都配好了，等你推），别删——见 9.1
3. 泛化痕量。分四类查，**后两类最容易被漏**：

   | 类别 | 例子 | 查法 |
   |---|---|---|
   | 云资源 | 真实 MQ 实例 ID、SLS project、云账号 UID | `grep -rn -E "rmq-cn-[a-z0-9]+-|<\d{12,}>"` |
   | 身份 | 公司域名、模块路径、真实人名 | `grep -rn -iE "<公司域名>|@<公司域名>"` |
   | **他仓引用** | `<模块域名>/<兄弟仓名>`（同组织的其他仓） | `grep -rn -E "[a-z0-9.-]+\.(com|cn)/[a-z-]+"` |
   | **内部文档引用** | `方案 §4.3`、`任务书`、`§9.12 检查项 #1–#7` | `grep -rn "§\|任务书\|需求文档\|评审"` |

   后两类在自留副本里是**纯噪声 + 来源指纹**：文档和兄弟仓都不在手上，
   读者只会困惑。统一改成自描述措辞（`// 强制顺序：` 而不是 `// 按方案 §4.3 强制顺序：`）。

4. 加 `.gitattributes`（`* text=auto eol=lf`）
5. **`.gitignore` 补上 AI 助手工作区**：`.workbuddy/`、`.cursor/` 会记录来源路径与会话记忆，
   属于痕量。仓库若本来就是给 AI 用的（脚手架 / 模板），这条尤其常被漏
6. `git init` + 设个人身份 + 一次提交。
   身份用 **`git config`（本仓）而非 `--global`**——源仓继承来的 `user.email` 常是公司邮箱，
   本仓覆盖即可，别顺手改掉用户其他仓的全局身份。
   推到个人 GitHub 的用 `<数字ID>+<login>@users.noreply.github.com`（`gh api user` 可取 ID）
7. **任何脚本化批量编辑之后，重跑一遍 CRLF 扫描**（见下）
8. **必须验证能跑**：`go build ./... && go vet ./... && APP_ENV=dev go test ./...`

判据：一份干净副本 = 无原仓历史 + 无公司标识 + **无内部文档/他仓引用** + **能编译能测**。
（若用户要的是可复用的"产品"而非副本，才回到下面的抽库流程。）

## 步骤

### 1. 先盘点，再动手（不要跳过）

只读原实现，产出一张表：包 → 解决什么问题 → 接口形态 → 依赖了谁 → 通用度（高/中/低）。
并行读多个仓时用 Explore 子代理，自己只精读真正要抽的那几个包。

**依赖是判定通用度的硬指标**：一个包 import 了某个框架（`go-zero/core/logx`、`gin`），
不代表它不通用——如果那是薄适配层，剥掉即可。但如果核心逻辑本身依赖框架类型，就是真绑定。

### 2. 列"可直接带走 / 必须剥离"两张清单

| 可直接带走（机制层） | 必须剥离（环境层） |
|---|---|
| 算法、接口抽象、错误码规则、脱敏正则、并发模型、探针语义 | 公司模块域名、内网地址、云厂商 endpoint 常量、内网 Git 服务、SSO 提供商、业务种子数据、审批人姓名 |

**默认值最容易被漏掉**：`cn-shenzhen`、`172.16.0.0/16`、`pay.aliyuncs.com` 这种写在常量里的
地域/网段/实例名，比 import 路径更隐蔽，必须逐个 grep 掉或参数化。

### 3. 重写，而不是搬运

抽取时**主动修掉原实现的设计缺陷**——这是"你的项目"和"抄来的代码"的分界。

常见可修项：
- **映射分散**：同一份规则在两个地方各写一个 `switch`（如 HTTP 与 gRPC 各自解析错误类型位）→ 收敛成单一中间层，另一侧只做一一对照
- **特例硬编码**：`if code == 某常量 { return 403 }` → 改成可注册的覆盖表
- **全局可变态无保护**：普通 map 被并发写 → 改写时复制快照（读路径退化为一次原子加载）
- **nil 处理**：方法对 nil 接收者 panic → 全部改为安全返回，支持"可能为 nil 的错误变量"写法
- **不可注入的横切依赖**：硬 import 宿主项目的 trace/logger → 改成 `Config{ TraceID func(ctx) string }` 形式的接入点

### 3.5 命名验证（建仓前必做，改名成本随时间指数上升）

名字一旦推送就是 go module path，改名 = force push + 所有引用失效 + 使用者迁移。
**最危险的撞名往往不在 GitHub 的 Go 仓库里**，而在其他语言生态（Rust/npm）和产品官网。

```bash
# 1) 同名 Go 仓库及星数：>50★ 且同类 = 放弃
gh api "search/repositories?q=<name>+in:name+language:go&sort=stars&per_page=3" \
  --jq '[.items[] | "\(.stargazers_count)★ \(.full_name)"] | join("   ")'
# 2) 跨生态同名包：crates.io / pypi / npm
# 3) 泛网络搜 "<name> platform framework service" 找同类产品官网
# 4) gh api users/<name> / orgs/<name> 看账号占用
```

**两类名字必然撞车，别浪费时间验**：

| 类型 | 实例 | 原因 |
|---|---|---|
| **通用功能词** | `blueprint`（8954★ 的 `go-blueprint` 就是 Go 脚手架生成器）、`observe`、`errors`、`authz` | 能描述功能的名字，做同一件事的人都会想到 |
| **基础设施隐喻** | `plinth`（plinth-dev）、`socle`（Rust crate）、`corbel`（Rust MCP server）——三个全被占，且全是「服务底座」类项目 | AI 时代做底座的人最容易想到「承重构件」词域 |

**好名字**：独特造词（`bizerr` = biz + err），或短小普通名词（`zap` / `chi` / `cobra`）。
品牌力来自项目本身，不来自词义——**含义越准，越容易撞**。

验证清单（每个候选都要过）：同类同名 Go 仓库 > 50★ → 弃；crates.io/pypi/npm 有同类同名包 → 弃；
有定位重合的产品官网 → 弃；拼写与常见词近似易混（如 `craton`/`carton`）→ 记为风险并告知用户。

### 4. 建仓

```
<name>/
├── go.mod            模块路径用个人命名空间，不用原公司的
├── README.md         产品门面，见第 6 步
├── LICENSE           可从同作者已有仓复制（Apache 2.0 是纯样板，无归属信息）
├── Makefile          仅 POSIX；另配 scripts/dev.ps1 给 Windows（本机常常没 make）
├── scripts/          一键启动（dev-up.sh / dev-up.ps1）+ 隧道联调（cloud/，见下）
├── .gitattributes    * text=auto eol=lf —— 必须加，否则 Makefile 检出成 CRLF 会报 missing separator
├── .gitignore
├── .github/workflows/ci.yml   gofmt 校验 + vet + test + 单独一个 -race job
├── doc.go            包级文档，写清"解决什么"与"不做什么"
└── <sub>/            子包适配层
```

**分层原则**：核心包零外部依赖；重依赖（grpc、各云 SDK）放独立子包。
Go 模块图裁剪会让不用子包的消费者不引入那些依赖——这是可以写进 README 的卖点。

**「一键启动」脚本值得单列**，它与 `make dev` 的差别是关键而非装饰：**先等依赖真正就绪
再往下走**（compose 后轮询 `pg_isready` / 探测端口），否则库刚起、还没 ready 时 migrate
必然失败。另加：无 `.env` 自动从 `.env.example` 复制、可选 `--migrate` / `--skip-compose`、
缺失工具自动安装。bash 与 PowerShell 各一份。

**若项目跑在云上，补一份「跳板机隧道」脚本**：云库在内网、本机直连不通，用
`ssh -N -L <本地>:<远端>` 把端口映射到本地，业务连接串不用改。三条安全要求：
① 拓扑**全走环境变量**（`JUMP_HOST`/`*_HOST`），脚本里不写主机名；
② 这些值过**字符白名单**（如 `^[A-Za-z0-9._:-]+$`）再拼进 `ssh` 命令行，防注入；
③ 口令**走 stdin** 喂远端 psql（`IFS= read -r PGPASSWORD`），**不进 argv、不进脚本正文**
—— argv 在进程列表里可见、argv/history 都是泄露面。
另配一个「只杀命令行含 `-L <本地端口>:` 的进程」的停止脚本，避免误伤普通 ssh 会话。

**别以为「必须拆多 module 才能隔离依赖」——已实测（Go 1.26，同 module 内的两个包）**：

| 消费者 import | 其 go.mod 多出的依赖 | go.sum 行数 |
|---|---|---|
| 只有根包 | 无（仅本库一行） | 2 |
| 根包 + 依赖 grpc 的子包 | grpc + genproto + protobuf + x/net/x/sys/x/text | 16 |

结论：**依赖隔离与 module 划分无关，只与「是否 import 该子包」有关**。单仓单 module 多包也能做到零负担引入。
真正必须拆 module 的场景只有一个：**各能力要独立演进版本**（否则改一个包就要动全仓版本号）。

### 5. go.mod 版本收敛

`go mod tidy` 会把 `go` 指令顶到本机 toolchain 版本、并拉依赖的最新版。**必须手工降回来**：

```bash
# 先看依赖的可用版本（优先用本地模块缓存里的，可离线）
ls "$(go env GOMODCACHE)/cache/download/<module>/@v/" | grep '\.info$'
```

选一个 `go` 指令 ≥ 目标版本的依赖版本，把 `go 1.26.0` → `go 1.22`、依赖降到稳定版，再 tidy。

### 6. README 范式（照抄这个骨架）

1. 一句话定位 + 一行可运行示例
2. **解决什么** —— 说清"不是 X、是 Y"，划清边界
3. 特性列表（每条都是一个可验证的行为，不是形容词）
4. 安装 / 快速开始（按使用场景分小节，含非目标框架的接法）
5. 规则表（错误码 / 协议映射 / 状态推导）
6. **API 表**：构造 / 判定 / 包装 / 诊断分组列出
7. **配置表**：字段 → 默认值 → 说明
8. **设计契约**：编号列出不可破坏的承诺（"变更视为破坏性修改"）
9. 依赖表：哪个包需要什么外部依赖
10. 开发命令 + License

第 8 步的"契约"是关键差异化——它不是功能清单，是**行为承诺**，例如：
"非法错误码一律按系统错误处理，不猜测类型位"、"原始 error 绝不进响应体"。

### 7. 测试

- 表驱动覆盖：输入→输出的纯函数优先
- **锁住承诺**：README 里每条契约都要有对应测试（渲染失败不 panic、原始 error 不出现在响应里）
- 文档示例用 `Example*` 写，Go 会验证它们的输出，比 README 里的代码块可靠
- 全局注册表要有并发测试（并发注册 + 查询），在 CI 的 `-race` job 里真正生效
- `TestMain` 里静默诊断日志，否则被测的 warn 会污染测试输出

#### 7.1 适配层必须有真实传输的 E2E

适配层（HTTP / gRPC / MQ / 各云 SDK）用 fake 只能验证"逻辑被调用了"，验证不了
"线上格式对不对"。**必须有真实传输的端到端测试**：

- Go + gRPC：`google.golang.org/grpc/test/bufconn`（内存连接，无网络、无端口、CI 友好）。
  服务端 `grpc.NewServer(grpcx.ServerOptions()...)` + `RegisterService`；
  客户端 `grpc.NewClient("passthrough:///bufnet", grpc.WithContextDialer(lis.DialContext), grpc.WithTransportCredentials(insecure.NewCredentials()), ...)`。
  用 `grpcx.DialOptions()` 这类导出 API 组链，**外部测试包 `package foo_test`** 顺带验证了公共 API 够用。
- 不想生成 `.proto`：手工声明 `grpc.ServiceDesc`（`HandlerType: (*空接口)(nil)` 即可，
  `reflect` 检查会被空接口满足），用 `wrapperspb.StringValue` 当载荷，`dec(&in)` 照常可用。
- E2E 要验的清单：线上状态码、**`ErrorInfo.Reason`（跨语言通道）**、trailer、
  客户端还原后的类型与文案、流式错误、语言/链路元数据透传、内部细节不泄漏。

**注释里的承诺 = 待验证的假设。** 例：「流结束时写 trailer 仍然有效」这种时序断言，
不跑在真实连接上就只是猜测（gRPC 里恰好成立：trailer 由 transport 在拦截器返回后才发出）。
凡是注释里写了"仍然""避免""不会"的地方，都补一条测试。

#### 7.2 第三方框架的集成断言，去源码里核实

README / 注释里一旦写出"X 满足此接口""加了这行就生效"这类话，**必须在依赖源码里确认**，
不能靠记忆或推测。模块缓存就是现成的源码库：

```bash
F=$(ls -d "$(go env GOMODCACHE)"/github.com/<org>/<repo>@*/<subpkg> | head -1)
grep -rn "func .*Add.*Interceptors" "$F"
```

顺带会挖出文档里查不到的行为差异——例如 go-zero 的 `zrpc` 在 `MustNewServer` 内**先**注册自己的
tracer/recover/stat，`Add*Interceptors` 是追加，所以外部链位于**内侧**（直接决定了 panic 由谁接住、
上报什么内容）。这类顺序依赖差异，只读官方文档是发现不了的。

### 8. 验证清单（逐条跑，别凭感觉）

```bash
gofmt -l .                    # 必须为空
go build ./... && go vet ./...  # vet 会抓出锁复制（atomic 类型按值返回）这类真问题
go test ./... -cover          # 覆盖率目标 ≥ 85%
make all                      # 或 scripts/dev.ps1 all
```

- `-race` 在 **windows/386 上不可用**（`-race is not supported on windows/386`）——本地跳过，靠 CI
- **要验证声明的 Go 最低版本，不必装第二个 Go**：`GOTOOLCHAIN=go1.22.12 go build ./...`
  会自动下载并切换到该工具链再执行。本地默认 Go 与 CI/`go.mod` 的 `go` 指令常常差好几个
  大版本（本例：本机 1.26.4 vs `go 1.22`），不实测就是盲区 —— 新依赖很可能悄悄把
  最低版本顶上去：
  ```bash
  GOTOOLCHAIN=go1.22.12 go build ./... && GOTOOLCHAIN=go1.22.12 go vet ./...
  GOTOOLCHAIN=go1.22.12 APP_ENV=test go test ./... -count=1
  ```
- `make` 本机常常没有（PortableGit 不带）⇒ **Makefile 改动没有 make 兜底**。
  别只靠肉眼查缩进，用这招**等价复跑**（能验续行、引号、退出码，不只是 TAB）：

  ```python
  # 抽某个目标的 recipe，按 make 规则展开后直接 sh 执行
  import re, pathlib
  lines = pathlib.Path('Makefile').read_text(encoding='utf-8').split('\n')
  i = next(k for k, l in enumerate(lines) if l.startswith('check-routes:'))  # 换成目标名
  body, k = [], i + 1
  while k < len(lines) and lines[k].startswith('\t'):
      body.append(lines[k][1:]); k += 1
  txt = re.sub(r'(?m)^@', '', '\n'.join(body)).replace('$$', '$')   # @ 不回显；$$ → $
  pathlib.Path('recipe.sh').write_text(txt + '\n', encoding='utf-8', newline='\n')
  ```

  然后 `sh recipe.sh; echo exit=$?`（`newline='\n'` 是防 CRLF）。
  另用 `grep -cP '^\t' Makefile` 粗查配方行缩进。
  **门禁类目标必须正反两例都跑**：正例 exit 0；再人为破坏一次，确认真的 exit 1
  且提示可读 —— 然后**还原并 `git diff --quiet` 复核**，否则会把实验现场留在源码里。
- Windows 上 `GOTMPDIR` 指到 `%TEMP%` 时，`go test` 偶发
  `fork/exec ...\<pkg>.test.exe: Access is denied.`（杀软/沙箱拦截），换个目录（如
  仓库内 `output/.gotmp`）即好 —— **别当成代码失败**去改测试。
- **Windows 脚本的编码是硬要求，不是风格问题**：
  - `.ps1` **必须带 UTF-8 BOM**。写成无 BOM 时 PowerShell 5.1 按 **ANSI(GBK)** 读取，
    中文被错误解码 → **引号解析错位** → 报 `字符串缺少终止符` / `数组索引表达式丢失`
    这类**看似语法错、实为编码错**的报错。实例：一行 `Write-Host "  停止: Ctrl+C"`
    变成 `"  鍋滄: Ctrl+C"`，解析器在此处断开、后续语句全被算成缺 `}`。
    **排查顺序**：报"字符串没结束"时，先 `sed -n 'Np' file | cat -A` 看那行的真实字节，
    再怀疑 `"@` 缩进之类的语法问题 —— 否则会像本次一样先改错方向。
    加 BOM：`path.write_bytes(b'\xef\xbb\xbf' + b)`（先确认原文件是合法 UTF-8 再追加）。
  - `.sh` / `.md` / `.go` 保持**无 BOM**；全部 LF（`.gitattributes` 已锁）。
  - 校验 `.ps1` 语法**不执行**：`[System.Management.Automation.Language.Parser]::ParseFile()`
    取 `$errs[].Extent.StartLineNumber` 定位；**不要**从 Bash 调 `powershell.exe`（被拦），
    用 PowerShell 工具。本机执行策略常禁止直接跑 `.ps1`，做行为验证要加
    `-ExecutionPolicy Bypass`。
- 若本机装不了 golangci-lint，**不要**塞一份没验证过的配置文件进仓；让 lint 目标检测到就用、没有就说明跳过
- **lint / CI 配置的语义必须实测，禁止推理**。这类配置的分层映射反直觉，读文档不出来的坑：
  - golangci-lint 把上游 staticcheck 拆成**三个独立 linter**：`staticcheck`(SA\*)、
    `gosimple`(S\*)、`stylecheck`(ST\*)。只 enable `staticcheck` 时，写
    `linters-settings.staticcheck.checks: ["all"]` **不会**打开 ST\*——
    于是「包缺注释会触发 ST1000」这类推论是错的。一条命令就能证伪：

    ```bash
    # 只 staticcheck → 无输出；把 stylecheck 也加进 enable → 立刻冒 ST1000
    golangci-lint run -c .golangci.yml ./somepkg/...
    ```
  - golangci-lint 默认 `max-same-issues: 3` 会**截断**重复问题。用 `--no-config` 试跑看到的
    条数会被严重低估（实测 13 vs 真实 66），务必把 `max-same-issues: 0` 一起配上再数。
  - 把 lint 从「找不到工具就 `go vet`」改成**硬失败**之前，先跑一遍拿到真实账单并分类。
    内网项目的真实账单常常全是误报：框架自己的 tag DSL（go-zero 的 `json:",default=3s"`
    → `SA5008`）、故意传 nil ctx 的测试（`SA1012`）、惯用写法（`govet shadow`）。
    「让 lint 必过」如果不同时加 `issues.exclude-rules`，等于让主干永久变红。
  - **把账单清到 0 的三种手段，按优先级用**（实测 66 → 0 条）：
    1. **分析器本就不该开** → 进 `linters-settings` 的 `disable`。`govet` 开 `enable-all`
       会带上 `shadow`，而它**不在 go vet 默认集合内**（官方认为误报率高），
       `if err := ...` 会被逐条报成「遮蔽外层 err」。
    2. **工具与框架 DSL 冲突** → `issues.exclude-rules` 加 **path + linters + text**。
    3. **规则本身合理、只是这一处例外** → 同样用 exclude-rule，但把 `path` 收窄到文件。
    收尾必须**对账**：豁免条数 + disable 掉的条数应恰好等于基线总数（本例 47+7+7 = 61 条
    exclude + 5 条 shadow 被 disable = 66）。对得上才说明没有误伤或漏网。
  - **exclude-rules 的 `path` 正则必须用 `[\\/]` 写路径分隔符**。Windows 上报出的路径是
    `internal\config\config.go`（反斜杠），只写 `internal/config/` 会在**本机失配、CI 才生效**
    ——反过来就是「本机绿、CI 红」这类最难查的假象。例：
    ```yaml
    - path: (^|[\\/])internal[\\/]config[\\/]
      linters: [staticcheck]
      text: SA5008
    ```
  - `golangci-lint@v1.55.x` **无法用 Go ≥1.25 构建**（它拉 `x/tools v0.14.0`，后者用
    `var _ [-delta*delta]int` 断言 `token.FileSet` 布局，Go 1.25 改了布局）：
    `invalid array length -delta * delta`。换 `@v1.64.8` 可构建。
  - 32 位工具链（`windows/386`）跑 golangci-lint 全仓会 **OOM**（用户态上限 2GB，
    爆在 `gcexportdata.Read`）；加 `-j 1 GOGC=30` 可跑完。
    另：`GOCACHE`/`GOTMPDIR` 若指向沙箱外的 `D:\go_temp`，会 `Access is denied`，
    先指到可写目录。
  - Makefile 里**把会因 Go 版本构建失败的装包步骤排在最后**（如 golangci-lint）：
    make 遇错即停，它排前面会把后面 `protoc-gen-*` 之类必备工具一起带走。
- **改了一处规则表述，必须回扫全仓同义表述**。同一规则常同时写在 README 表格、
  规范文档、代码注释三处，只改一处比不改更糟——读者会默认 README 才是权威。
  实例：`fail-closed` 语义已在 `error-code-spec.md` 更正为「只有**形非法**的码降级 500，
  形合法未登记的码仍按类型位推导 HTTP」，而 README 表格里的旧说法「未登记的码一律 500」
  还留着，与同仓派生规则表、`errors_test.go` 三方矛盾。做法：用**关键词**（不是整句）
  跨 `*.md`/`*.go`/`*.yaml` 全扫一遍，别只搜你刚改的那处。
- **文档核对靠抽标识符，不靠通读**。把文档里的反引号标识符与行为性断言逐条落到代码/配置
  验证，一次能抓到「未导出函数被写成 `pkg.Func`」「提到的目录不存在」「make 目标名写错」；
  反向也能发现该记而没记的（启动了框架错误处理器却没写进文档）：

  ```bash
  grep -oE '`[A-Za-z_][A-Za-z0-9_./:-]*`' README.md | sort -u      # 抽出全部标识符
  diff -q internal/handler/routes.go scripts/handwritten/routes.go.in  # 文档声称「须保持同步」的两份
  ```
- **验证某 API 是否存在，别只 `grep '^func Name'`**：不少库的选项是**包级变量**
  （go-zero 的 `WithTransportCredentials = internal.WithTransportCredentials`），
  用 `^func` 会漏判成「不存在」而误删正确文档。改用 `grep -n "\bName\b"`。
- **收敛「同一规则两处实现」之后，补一条不变式测试把它钉住**。改了结构却没改注册表
  （或反过来）是静默失效，编译期与运行期都不报错——只有测试能发现。
  例子：热更注册表登记了 `RpcClient.Targets`，而 `Config` 上还没有 `RpcClient` 字段，
  于是含该键的配置只会打到「不在白名单」。用反射逐条校验注册表的路径能落到结构体字段上：

  ```go
  typ := reflect.TypeOf(Config{})
  for _, f := range hotFields {
      // Anonymous 字段要递归（嵌入的 RestConf 里有 Log/Timeout）
      assert.True(t, structHasPath(typ, f.Path), "%s 找不到对应字段", f.Key)
  }
  ```

  同理，跨进程的错误码/元数据契约要有一条**真实传输**的 E2E（bufconn 即可），
  别只测单侧的映射函数——两侧各自"通过"但线上语义已经断掉是常见结局。

#### 8.1 CI 落地（GitHub Actions）

**先确认 CI 到底跑在哪**。这是最容易被忽略的「假 CI」：仓里躺着 `.gitlab-ci.yml`，
而 `git remote -v` 指向 GitHub ⇒ **实际零 CI**，本地全绿也只是本地全绿。
判据：看远端域名 vs `.github/workflows/` 是否存在，而不是看「有没有 CI 文件」。

三个**并行** job 就够，全部做成必过门禁：

| job | 内容 | 要点 |
|-----|------|------|
| `lint` | `gofmt -l` + 版本门禁 + golangci-lint | 用官方 `golangci-lint-action`（下**预编译二进制**） |
| `test` | `go test -race -covermode=atomic -coverprofile` | `-race` 本机跑不了时，这是唯一能跑它的地方 |
| `build` | 宿主 `make build` + 按 Dockerfile 同参（`CGO_ENABLED=0`）跨架构 | 验证 Dockerfile 而非「能编译」 |

```yaml
on:
  push: { branches: [main] }   # 只在 main 上跟 push，避免与 PR run 重复触发
  pull_request:
  workflow_dispatch:
concurrency:                    # 同分支新 push 取消旧 run：省额度、避免旧结果覆盖新状态
  group: ci-${{ github.ref }}
  cancel-in-progress: true
permissions: { contents: read } # 最小权限
```

- **Go 版本用 `go-version-file: go.mod`，不要写死**：`go.mod` 的 `go` 指令就是声明的最低
  版本，写死必然与它漂移。
- **lint 不要用 `go install golangci-lint@x` 装**：那会把「golangci-lint 能否被当前 Go 编译」
  变成 CI 的失败点（v1.55.2 在 Go ≥1.25 上根本构建不出来）。官方 action 下预编译二进制，
  与「本机装不上」这件事彻底解耦 —— 于是 `make setup-lint` 可以按本机 Go 选版本，
  不必再为了迁就 CI 而钉在旧版。
- **`-race` 与 `-covermode=atomic` 是官方搭配**（默认 `set` 模式在并发下计数不准），
  且带 `-coverprofile` 时必须 `-count=1`（多轮计数会串）。
- 顺手加 `.github/dependabot.yml`，但 **`package-ecosystem` 只写 `github-actions`**：
  gomod 若被自动升级，会和「框架版本被门禁钉死」（`check-<framework>-version` 之类）打架。
  并且要给**主版本与本仓工具链绑定**的 action 加 `ignore`（`version-update:semver-major`）：
  典型是 `golangci-lint-action` —— ≥ v7 只支持 golangci-lint **v2**，若本仓还钉在 v1
  （`.golangci.yml` 还是 v1 schema），自动升级必然产出一个**永远红**的 PR，而且它每次都回来。
  实测报错：`invalid version string 'v1.64.8', golangci-lint v1 is not supported by
  golangci-lint-action >= v7`。这类「必挂 PR」要**关掉 + 加 ignore 并写清理由**，
  别留在那里当噪音（关掉时把根因和后续路径写进评论，将来迁移时好找）。
- 把 CI 命令**收进 Makefile 目标**（如 `make test-race`），本地与 CI 共用一条命令，
  免得两边参数悄悄分叉。
- **「真源 + 生成物」双份维护的仓，值得加一条漂移门禁**。这类仓常有「`X.in` 是真源，
  生成命令会拿它覆盖 `X`」的约定（实例：`scripts/handwritten/routes.go.in` →
  `internal/handler/routes.go`），而那句 `cp` 是**无条件**的 ⇒ 只改生成物的人，改动会在
  下次跑生成时被**静默抹掉**（不报错、无提示），是这类仓唯一会无声丢代码的路径。
  加一条 `diff -u X.in X` 门禁，**并入既有的 check 步骤**（不新增 job、无网络依赖 ⇒ 不会假红）。
  关键取舍：**选「检出即失败」，不要写「自动同步」** —— 漂移时无法判断该保留哪一边，
  自动 `cp` 必然静默丢掉一边，那正是要防的事；报错并给出两条修法，由人决定。
- 条件触发的 job（`paths:` 过滤那类）**不能进分支保护的 required 名单**：
  被跳过时 check 不上报，PR 会永久 pending —— 与「check 名写错」是同一类静默永挂。
- 换 CI 平台是**不可逆的对外动作**（会删掉别人的流水线）：先问用户。

#### 8.2 分支保护（main）

用 classic protection API 一次配好（比在网页上点更可复现）：

```bash
gh api -X PUT repos/{owner}/{repo}/branches/main/protection --input bp.json
gh api repos/{owner}/{repo}/branches/main --jq .protected     # => true
```

`bp.json` 的关键字段：`allow_force_pushes=false`、`allow_deletions=false`、
`required_status_checks.contexts=[三个 job 名]`、`required_pull_request_reviews=null`
（不强制 PR，保留直推 main 的日常用法）。**PUT 是整体替换**，改单项也要带全字段。

**两个必踩的坑**：

1. **`enforce_admins` 必须是 `false`**（如果你还要直推 main）。
   `enforce_admins=true` 与 `required_status_checks` 叠加后，**连管理员也不许直推** ——
   新提交不可能「已经」带上那些 check，于是 push 直接被拒：

   ```
   remote: - 3 of 3 required status checks are expected.
   ! [remote rejected] main -> main (protected branch hook declined)
   ```

   `false` **不等于没保护**：非管理员仍被硬约束；管理员的绕过会被 GitHub 显式回显并记录
   （push 时输出 `Bypassed rule violations for refs/heads/main`），可在审计日志追溯。
2. **`contexts` 里的名字必须逐字等于 workflow 里 job 的 `name:` 字段** ——
   不是 workflow 名、也不是 `jobs.<id>` 键。写错**不报错**，只是 PR 永远卡着等一个
   不会出现的 check。核对办法（拿真实上报值去填，别手打）：

   ```bash
   gh api repos/{owner}/{repo}/commits/main/check-runs --jq '.check_runs[].name'
   ```

**怎么验证门禁真的在拦**（而不是配了个装饰品）：找一个本该失败的 PR，看它
`mergeStateStatus` 是否变成 `BLOCKED`。dependabot 的 proposal 是现成的靶子。

要临时解除：`gh api -X DELETE repos/{owner}/{repo}/branches/main/protection`。

### 9. 收尾（git）

```bash
git init && git add -A && git status --short
```

**不要直接提交**：本机的 `user.email` 往往是公司邮箱，公开仓库会连带泄露归属。
先走到第 10 步把署名换掉，再 commit。

#### 9.1 把已有仓迁移到新路径（跨盘 move）

用户说"迁移到 X:/path"时，**先看目标是否已存在**——它可能已经是个空仓
（`git init` + `git remote add origin` 都配好了，等你推）。此时别覆盖：

```bash
cat "$DST/.git/config"          # 若有 [remote "origin"]，记下 URL，迁移后要加回来
find "$DST/.git/objects" -type f | wc -l   # 0 个对象 = 空仓，删掉不损失内容
```

`cp -a "$SRC/." "$DST/"` 注意**带 `/.`**——写成 `cp -a "$SRC" "$DST"` 目标已存在时会嵌套成
`$DST/$(basename $SRC)/`。

**校验时不要用"全文件哈希必须全等"当判据**——两处必然不同，别误判为拷贝损坏：

| 必然不同 | 原因 | 怎么证明实质一致 |
|---|---|---|
| `.git/config` | 我加回的 remote | `diff` 应**只有** origin 那几行 |
| `.git/index` | git 重写了 stat 缓存（mtime/inode 变了） | `git ls-files --stage \| sha256sum` 两侧同值 |

再加 `git rev-parse HEAD^{tree}` 与 `git rev-parse HEAD` 两侧同值 → 历史与内容都完整。
然后 `git remote add origin <URL>` + `git config branch.main.remote/merge` 恢复跟踪。

**删除源目录要走两步**（先 `.git` 后目录），见「坑」里的 safe-delete。
删完在**新位置**重跑 `go build` / `go vet` / `go test`——跨盘换路径可能暴露硬编码绝对路径。

### 10. 发布到 GitHub

#### 10.1 推送前必须定死的两件事

**① 模块路径必须与 GitHub 账号大小写完全一致。** 别用本机 Gitea / 内部 git 的用户名当命名空间。
先用 CLI 拿到真实账号：

```bash
gh api user --jq '"id=\(.id) login=\(.login)"'
```

再全量替换模块路径。**注意替换陷阱**：

- `Edit` 的 `old_string` 若**带引号**（`"github.com/old/name"`），只能命中独立的 import 行；
  `"github.com/old/name/sub"` 这种带子包后缀的**会漏**。
- 改用**不带引号的子串 + `replace_all`**，然后**必须再 grep 一次确认零残留**：

```bash
grep -rn "old-namespace/name" . --include="*.go" --include="*.md" --include="*.mod" | grep -v '^\./\.git/'
```

漏了就得 force push 重写历史，成本远高于事前 grep。

**② commit 身份换成 GitHub noreply。** 格式是 `{id}+{login}@users.noreply.github.com`
（`{id}` 来自上面命令），能正确关联贡献图且不暴露真实邮箱：

```bash
git config user.email "<数字ID>+<login>@users.noreply.github.com"
git config user.name  "<login>"
```

提交后用 `git log -1 --format='author: %an <%ae>%ncommitter: %cn <%ce>'` 核对。

#### 10.2 建仓 → tag → Release

```bash
git branch -M main
gh repo create <owner>/<name> --public --source=. --remote=origin --push --description "..."
git tag -a v0.1.0 -m "..." && git push origin v0.1.0
gh release create v0.1.0 --title "v0.1.0" --notes "..."
```

- **必须打语义化 tag**：Go 模块只有 tag 之后才能 `go get @v0.1.0`；没 tag 只能拿伪版本。
- 公开 / 私有**要问用户**——这是不可逆动作，且代码可能源自职务作品。
- push 后确认 CI：`gh run list --repo <owner>/<name> --limit 3`。

#### 10.3 发布后必做：外部 `go get` 真实验证

这是"能不能被别人用"的最终判据，比任何本地测试都硬：

```bash
mkdir -p D:/path/_probe && cd "$_"          # 注意：别放系统 temp 根目录！
go mod init example.com/probe
GOSUMDB=off go get github.com/<owner>/<name>@v0.1.0
# 写 main.go，import 全部公开包并实际调用，go run 看输出
```

- **Go 会拒绝系统 temp 根目录下的 go.mod**（`ignoring go.mod in system temp root`）→
  探测目录放子目录或工作区，不要用 `mktemp -d` 的根。
- `sum.golang.org` 可能返回 **502 Bad Gateway** → 用 `GOSUMDB=off` 绕过校验；
  **下载成功即说明模块本身没问题**，别误判成发布失败。
- 验证完**删掉探测目录**，别留在工作区。

### 11. 多库时的品牌伞

**伞可以早立，但索引仓必须有实质内容**——只列链接的索引仓就是空壳，
点进去发现什么都没有，比用一个窄名字更伤信任。实质内容 = 「这一套的共同取舍」+「设计契约」。

```
<owner>/<brand>     索引仓：定位 + 共同设计契约 + 库清单导航
<owner>/<lib-a>     各库独立仓，README 顶部加一行家族标识
<owner>/<lib-b>
```

- 索引仓写**为什么有这一套**（差异化取舍、具体的取舍举例），不是罗列功能
- 各库 README 顶部：`> **[<brand>](链接) 系列** — 一句话定位`
- **各库 go.mod 路径保持不变**——品牌是外部标识，不进 module path，否则使用者要迁移
- 顺手 `gh repo edit --description "..." --add-topic a --add-topic b`（多次 `--add-topic`）提高可发现性
- **不要为品牌建 GitHub org**：免费 org 与用户名共享全局命名空间，常见词基本都被占，索引仓足够

**库名与品牌名必须分层**：品牌名统摄，库名各自描述自己。
把所有能力塞进一个名字里，就没法单独引用、单独演进、单独发版。

## 坑

- `go mod tidy` 顶高 `go` 指令 → 手工降回
- `atomic.Pointer` / `sync.Mutex` 成员按值返回 → vet 报 `return copies lock value`，用构造函数返回指针
- `Body.Code` 是 `any` 时，内部塞自定义 string 类型会导致调用方类型断言失败 → 统一塞 `string`
- 用 `testing` 的 example 输出比较会 TrimSpace 两端，多一个换行不影响
- **`grpc.SetTrailer(ctx, md)` 查的是 context 里的 `ServerTransportStream`，不是 `grpc.ServerStream`**
  → 测试替身的 `ServerStream.SetTrailer` 必须委托给它，否则 trailer 断言恒为空。
  且 `ServerStream.SetTrailer` **不返回 error**（`ServerTransportStream.SetTrailer` 才返回），签名抄错会编译不过
- **客户端的 `grpc.Trailer(&md)` 必须靠 `append` 追加 CallOption，但不要就地 append**：
  调用方传进来的切片若有剩余容量，就地追加会写到上层共用数组上 → `opts = append(append([]grpc.CallOption{}, opts...), ...)`
- 服务端返回的是 **status error 而非自定义错误类型**（自有错误类型只在业务代码内部流传），
  测试断言要用 `status.Convert(err).Message()` 读文案，别用 `errors.As` 拿结构体
- 测试替身里别自造 `io.EOF` 常量：包装层比对的是真正的 `io.EOF`，假 EOF 会让测试"通过得莫名其妙"
- 拦截器里的 `info *grpc.UnaryServerInfo` 可能为 nil（手工调用时）→ recover 层触碰它前先判空，
  否则在 recover 里再 panic 一次就是进程级事故
- **Edit 批量替换模块路径时带引号会漏**：`"github.com/a/b"` 不匹配 `"github.com/a/b/sub"`。
  用不带引号的子串 + `replace_all`，替换后 grep 复查
- **`go get` 探测别放系统 temp 根**：Go 会 `ignoring go.mod in system temp root`
- **`sum.golang.org` 502 不代表模块有问题**：下载已成功，加 `GOSUMDB=off` 继续验证即可
- **别用 `status.FromError` 判断「这个 error 是否已是 gRPC status」**：它会经 `errors.As`
  沿 `Unwrap` 链下钻。若自定义错误类型把原始 status 挂在 cause 上（为了保留传输层信息），
  中继场景就会把业务错误误判成「已是 status」而原样过网 → 错误码二次丢失。
  判定要用**直接类型断言**：`err.(interface{ GRPCStatus() *status.Status })`
- **服务端少一个 Error 拦截器，错误码就全丢**：gRPC 对 handler 返回的**非 status error**
  一律降级为 `codes.Unknown`，并把 `err.Error()` 原文塞进 status message。于是
  `*BizError` 过网后变成 `code = Unknown desc = "COM2001: 参数 x 为必填"` ——
  `ErrorInfo.Reason` 与 trailer 双双消失。拦截器放行 `io.EOF` 与已是 status 的错误，
  只翻译其余；放在链的**最内层**（外侧拦截器自己产生的错误不该被改写）
- **go-zero `zrpc` 的拦截器是追加语义**：`MustNewServer` 内部先装自己的
  Trace/Recover/Stat/Prometheus/Breaker/Shedding/Timeout，外部 `Add*Interceptors` 追加，
  所以自有链整体在**内侧**——Breaker/Shedding/Timeout 产生的失败永远不带业务码
- **`zrpc.WithDialOption` 只收单个 `grpc.DialOption`**（非变参），传 `...` 会编译不过：
  `for _, o := range grpcx.DialOptions() { opts = append(opts, zrpc.WithDialOption(o)) }`
- **`zrpc.RpcServer.Stop()` 只调 `logx.Close()`，不停 grpc server**：
  优雅退出走 go-zero `proc` 的 shutdown listener。测试里要收尾只能 `proc.Shutdown()`
  （全局一次性，用完会影响同进程其他用例——权衡后再决定要不要真起 zrpc 集成测）
- **go-zero 缺省是阻塞拨号**：`zrpc.NewClient` 不带 `WithNonBlock()` 时下游没起就起不来。
  网关类进程要默认反转成非阻塞，再给一个显式开关
- **go-zero 的 `conf.LoadFromYamlBytes` 会给 map 值里的 struct 也填 `default=`**
  （实测 confirm），所以 `map[string]SomeConf` 里的 `Middlewares.* default=true` 不会静默变 false。
  但直接把结构体字面量喂给 `zrpc.NewClient` 就没有默认值了——两条路径不一样，别混
