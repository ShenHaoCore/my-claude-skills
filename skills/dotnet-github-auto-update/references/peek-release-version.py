"""只下载发布资产的一小部分，就读出 exe 里被 tag 注入的版本号。

为什么需要它
------------
自动升级最致命的隐患是「发布产物的版本号与 tag 不一致」——客户端静默永不更新，
或者装上新版后仍被反复提示升级（死循环）。核对它本来要下完整个 zip，而
GitHub 资产直链在国内/本机常常 40 分钟都下不完 85MB。

原理
----
Release 资产是 zip，里面只有一个 deflate 压缩的 exe（约 1:2 膨胀）。
把**已下载的压缩前缀**喂给 zlib 的流式解压器，就能拿到 exe 开头的十几 MB，
足够覆盖 PE 头与 `.rsrc` 段（Win32 版本资源就在 `.rsrc` 里）。
再按 UTF-16LE 搜索 StringFileInfo 里的 `FileVersion` 字符串即可。

用法
----
    # 1) 只下前 10MB（curl 一定要带 --ssl-no-revoke，本机 schannel 吊销检查不可用）
    curl -sS --ssl-no-revoke -L -r 0-10485759 -o partial.zip <资产直链>

    # 2) 解出前缀并打印所有版本资源块
    python peek-release-version.py partial.zip DotaInsight

注意
----
单文件产物会把 .NET 运行时组件也嵌进去，`.rsrc` 里有**十几个**版本资源块
（`Microsoft® .NET`、`Microsoft Edge Embedded Browser WebView Loader` …）。
所以必须按 `ProductName == 自己的应用名` 过滤，不能取第一个匹配。
另外 StringFileInfo 按字母序排列，`FileVersion` 位于 `ProductName` **之前**，
需要从 ProductName 的位置**向前**回看才能配对。

⚠️ **只对 `PublishSingleFile` 的产物好用**：single-file 会把托管负载**追加在 PE 段之后**，
因此 `.rsrc`（约 1.5MB）落在文件开头的 ~4% 处（实测 216MB 产物中偏移 0x7E0200），
下 10% 就够。**普通原生 exe / 框架依赖的 apphost 不适用**——它们的 `.rsrc` 往往压在文件末尾，
按比例截断根本到不了（实测 Debug apphost 的 `.rsrc` 占文件 57%，`curl.exe` 的在 97% 处），
这种情况脚本会明确提示「超出前缀，需要多下一点」，不会给出错误结论。

验证方式（离线夹具，不必等慢速下载）：用 CI 同款命令本地 publish 出单文件 exe，
打成 deflate zip 后截断到 10% 再喂给本脚本——实测能读到 `ProductName='DotaInsight'`
`FileVersion='0.2.0.0'`，与线上产物行为一致。
"""
import re
import struct
import sys
import zlib


def utf16(s: str) -> bytes:
    return s.encode("utf-16-le")


def read_value_after(raw: bytes, end: int) -> str:
    """VS_VERSIONINFO 的字符串值：紧跟 key 之后、4 字节对齐、UTF-16 到 NUL 结束。"""
    p = end + (-end) % 4
    return raw[p:p + 96].decode("utf-16-le", "ignore").split("\x00")[0].strip()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    app_name = sys.argv[2] if len(sys.argv) > 2 else None

    with open(path, "rb") as f:
        buf = f.read()
    print(f"已下载压缩数据：{len(buf):,} B")

    # ---- 解析 zip 第一个本地文件头 ----
    if buf[:4] != b"PK\x03\x04":
        print("不是 zip 本地文件头（是不是下载失败了？）")
        return 1
    method, = struct.unpack_from("<H", buf, 8)
    csize, = struct.unpack_from("<I", buf, 18)
    usize, = struct.unpack_from("<I", buf, 22)
    fnlen, = struct.unpack_from("<H", buf, 26)
    xlen, = struct.unpack_from("<H", buf, 28)
    print(f"条目={buf[30:30 + fnlen].decode('utf-8', 'replace')}  "
          f"压缩方式={method}  压缩后={csize:,} B  原始={usize:,} B")
    if method != 8:
        print("该条目不是 deflate，无法流式解压前缀")
        return 1

    # ---- 流式解压出前缀 ----
    # 分块喂入：即使中途字节损坏，已解出的前面若干块也不会丢。
    # （注意：输入只是被「截断」而非损坏时，zlib 不报错，只是解到哪算哪。）
    d = zlib.decompressobj(-15)
    data = buf[30 + fnlen + xlen:]
    chunks = []
    step = 1 << 20
    try:
        for i in range(0, len(data), step):
            chunks.append(d.decompress(data[i:i + step]))
    except zlib.error as e:
        have = sum(len(c) for c in chunks)
        print(f"解压在中途出错（{e}）——保留已解出的 {have:,} B 继续判定")
    raw = b"".join(chunks)
    if not raw:
        print("没解出任何数据，需要多下一点再试")
        return 1
    print(f"解出原始前缀：{len(raw):,} B（占完整 exe 的 {len(raw) / usize * 100:.1f}%）")

    # ---- 确认 .rsrc（版本资源所在段）在前缀之内 ----
    if raw[:2] != b"MZ":
        print("前缀不是有效 PE（缺 MZ）")
        return 1
    e_lfanew, = struct.unpack_from("<I", raw, 0x3C)
    if raw[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        print("PE 签名不匹配")
        return 1
    nsec, = struct.unpack_from("<H", raw, e_lfanew + 6)
    opt_size, = struct.unpack_from("<H", raw, e_lfanew + 20)
    sec0 = e_lfanew + 24 + opt_size
    rsrc_ready = False
    for i in range(nsec):
        off = sec0 + i * 40
        name = raw[off:off + 8].rstrip(b"\0").decode("ascii", "replace")
        _vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", raw, off + 8)
        if name == ".rsrc":
            rsrc_ready = raddr + rsize <= len(raw)
            print(f".rsrc RVA=0x{vaddr:X} 大小={rsize:,} 文件偏移=0x{raddr:X} "
                  f"{'✓ 已在前缀内' if rsrc_ready else '✗ 超出前缀，需要多下一点'}")
    if not rsrc_ready:
        return 1

    # ---- 列出所有版本资源块（ProductName ← 向前回看 FileVersion）----
    print("\n=== .rsrc 中的版本资源块 ===")
    hit = False
    for m in re.finditer(re.escape(utf16("ProductName")) + b"(?:\x00\x00)*", raw, re.I):
        name = read_value_after(raw, m.end())
        win_start = max(0, m.start() - 1600)
        hits = list(re.finditer(re.escape(utf16("FileVersion")) + b"(?:\x00\x00)*",
                                raw[win_start:m.start()], re.I))
        ver = read_value_after(raw, win_start + hits[-1].end()) if hits else None
        mark = ""
        if app_name and name == app_name:
            mark = "   <== 本应用"
            hit = True
        print(f"  ProductName = {name!r:<48} FileVersion = {ver!r}{mark}")

    print()
    if app_name:
        if hit:
            print(f"判定：产物中 {app_name} 的版本资源已读到（对照 tag 是否一致）")
            return 0
        print(f"未找到 ProductName == {app_name} 的块——可能前缀还不够，或多下一点再试")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
