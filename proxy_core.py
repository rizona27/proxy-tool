"""代理核心操作：注册表读写、代理类型格式化、绕过列表构建、归属地辅助

纯标准库实现（winreg / ctypes / socket / json），无第三方依赖。
"""
import ipaddress
import json
import re
import socket
import winreg

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

# ── 私有 / 内网地址段 ──
# 说明：<local> 的准确含义是「不含点号的单标签主机名」(NetBIOS)，
#      它 **不包含任何 IP 字面量**。所以 127.0.0.1、192.168.x.x 等
#      必须显式写成通配符才会绕过代理。
_IPV4_BYPASS_SEGMENTS = (
    # RFC1918 私有段
    ["10.*"]
    + [f"172.{i}.*" for i in range(16, 64)]     # 16-31 标准，32-63 企业内网常见
    + ["192.168.*"]
    # 回环
    + ["127.*"]
    # CGNAT / 运营商级 NAT —— Tailscale、ZeroTier 等组网工具大量使用
    + [f"100.{i}.*" for i in range(64, 128)]
    # 链路本地 (APIPA)
    + ["169.254.*"]
    # 组播 / 保留
    + ["224.*", "239.*"]
)

_IPV6_BYPASS_ITEMS = ("::1", "[::1]", "fc00::/7", "fd00::/8", "fe80::/10", "*.local")


def build_bypass(bypass_private_ip: bool = True,
                 extra_hosts: list | None = None) -> str:
    """构建 ProxyOverride 值。

    Args:
        bypass_private_ip: 是否加入全部私有 IP 段
        extra_hosts: 额外要绕过的域名/主机（如 NAS 公网域名），
                     会自动同时加入精确匹配与其子域通配
    Returns:
        分号分隔的 ProxyOverride 字符串
    """
    rules: list[str] = []

    if bypass_private_ip:
        rules.append("<local>")
        rules.append("localhost")
        rules.extend(_IPV4_BYPASS_SEGMENTS)
        rules.extend(_IPV6_BYPASS_ITEMS)

    for host in extra_hosts or []:
        host = (host or "").strip().lower()
        if not host:
            continue
        # 去掉用户可能误填的协议前缀、路径和端口
        host = re.sub(r"^[a-z]+://", "", host).split("/")[0]
        if host.count(":") == 1:
            host = host.split(":")[0]
        if not host:
            continue
        if host not in rules:
            rules.append(host)
        # 子域名通配（*.example.com）
        if host.count(".") >= 1 and not host.startswith("*."):
            wildcard = f"*.{host}"
            if wildcard not in rules:
                rules.append(wildcard)

    seen: set[str] = set()
    ordered: list[str] = []
    for r in rules:
        if r not in seen:
            seen.add(r)
            ordered.append(r)
    return ";".join(ordered)


# ── 注册表操作 ──

def _open_reg(write: bool = False):
    access = winreg.KEY_READ | (winreg.KEY_WRITE if write else 0)
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, access)


def _query(key, name: str):
    try:
        return winreg.QueryValueEx(key, name)[0]
    except (FileNotFoundError, OSError):
        return None


def get_current_proxy():
    """获取当前系统代理设置 -> (enabled: bool, status_str: str, server_str: str)"""
    try:
        with _open_reg() as key:
            enabled = bool(_query(key, "ProxyEnable"))
            server = _query(key, "ProxyServer")
            if server is None:
                server = "未设置"
            status = "已启用" if enabled else "已禁用"
            return enabled, status, server
    except (FileNotFoundError, PermissionError, OSError) as e:
        return False, "未知", f"无法获取 ({e})"


def _safe_read(name: str):
    try:
        with _open_reg() as key:
            return _query(key, name)
    except OSError:
        return None


def read_proxy_override():
    """读取当前 ProxyOverride 原始值，未设置返回 None"""
    return _safe_read("ProxyOverride")


def read_autoconfig_url():
    """读取当前 PAC 脚本地址，未设置返回 None"""
    val = _safe_read("AutoConfigURL")
    return val if val else None


def snapshot_proxy_settings() -> dict:
    """快照当前代理相关注册表项，用于关闭代理时精确还原"""
    return {
        "ProxyEnable": _safe_read("ProxyEnable"),
        "ProxyServer": _safe_read("ProxyServer"),
        "ProxyOverride": _safe_read("ProxyOverride"),
        "AutoConfigURL": _safe_read("AutoConfigURL"),
    }


def has_restorable_snapshot(snapshot: dict | None) -> bool:
    """快照里是否存在需要还原的项"""
    if not snapshot:
        return False
    return bool(snapshot.get("ProxyOverride") or snapshot.get("AutoConfigURL"))


def _set_str(key, name: str, value: str):
    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def _set_dword(key, name: str, value: int):
    winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)


def _del_value(key, name: str):
    try:
        winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass


def enable_proxy_registry(host: str, port: str, bypass_override: str | None,
                          disable_pac: bool = True) -> str:
    """写入注册表启用代理，返回写入的 ProxyServer 值。

    Args:
        bypass_override: ProxyOverride 值；None 表示删除该项
        disable_pac: 是否临时清除 AutoConfigURL（PAC 优先级高于手动代理，
                     不清除会导致「显示已启用但实际不生效」）
    """
    proxy_server = format_proxy_server(host, port)
    with _open_reg(write=True) as key:
        _set_dword(key, "ProxyEnable", 1)
        _set_str(key, "ProxyServer", proxy_server)
        if bypass_override:
            _set_str(key, "ProxyOverride", bypass_override)
        else:
            _del_value(key, "ProxyOverride")
        if disable_pac:
            _del_value(key, "AutoConfigURL")
    return proxy_server


def disable_proxy_registry(restore: dict | None = None):
    """禁用代理。

    Args:
        restore: enable 前的快照（来自 snapshot_proxy_settings）。
                 传入时会还原用户原有的 ProxyOverride / AutoConfigURL，
                 而不是粗暴删除 —— 避免破坏用户已有配置。
    """
    with _open_reg(write=True) as key:
        _set_dword(key, "ProxyEnable", 0)

        if restore is None:
            # 无快照：保守起见只清掉本工具可能写入的绕过列表
            _del_value(key, "ProxyOverride")
            return

        # 还原用户原始绕过列表
        orig_override = restore.get("ProxyOverride")
        if orig_override:
            _set_str(key, "ProxyOverride", orig_override)
        else:
            _del_value(key, "ProxyOverride")

        # 还原 PAC
        orig_pac = restore.get("AutoConfigURL")
        if orig_pac:
            _set_str(key, "AutoConfigURL", orig_pac)
        else:
            _del_value(key, "AutoConfigURL")


def refresh_system():
    """通过 WinInet API 刷新系统代理设置"""
    import ctypes
    INTERNET_OPTION_SETTINGS_CHANGED = 39
    INTERNET_OPTION_REFRESH = 37
    try:
        wininet = ctypes.windll.Wininet
        wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
    except (AttributeError, OSError):
        pass


# ── 代理服务器格式 ──

def format_proxy_server(host: str, port: str) -> str:
    """构建注册表 ProxyServer 值（统一走 HTTP 代理）"""
    return f"{host}:{port}"


def _split_host_port(value: str):
    """拆分 host:port，兼容 IPv6 方括号写法 [::1]:7890"""
    value = (value or "").strip()
    if value.startswith("["):
        idx = value.find("]")
        if idx > 0:
            host = value[1:idx]
            rest = value[idx + 1:]
            return host, rest[1:] if rest.startswith(":") else ""
    if value.count(":") == 1:
        host, port = value.rsplit(":", 1)
        return host, port
    return value, ""


def parse_proxy_server(server_str: str):
    """解析注册表 ProxyServer 值 -> (host, port, type)

    支持：ip:port / host:port / [::1]:port / proto=host:port;...
    """
    if not server_str or server_str == "未设置":
        return "", "", "HTTP"

    if "=" in server_str:
        parts = {}
        for chunk in server_str.split(";"):
            if "=" in chunk:
                proto, value = chunk.split("=", 1)
                parts[proto.strip().lower()] = value.strip()
        for proto in ("http", "https", "socks", "socks5"):
            if proto in parts:
                host, port = _split_host_port(parts[proto])
                ptype = "SOCKS5" if proto.startswith("socks") else "HTTP"
                return host, port, ptype

    host, port = _split_host_port(server_str)
    return host, port, "HTTP"


# ── 地址判定与校验 ──

def is_private_ip(ip: str) -> bool:
    """判断是否为私有 / 内网 / 回环 / 链路本地地址（含 IPv6）

    注意：Python 标准库的 is_private 不覆盖 CGNAT 100.64.0.0/10
    （Tailscale / ZeroTier 等组网工具大量使用），需单独判断。
    """
    if not ip:
        return False
    ip = ip.strip().strip("[]")
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False

    if isinstance(addr, ipaddress.IPv4Address):
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
            or addr in ipaddress.ip_network("100.64.0.0/10")   # CGNAT
        )

    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def normalize_host(host: str) -> str:
    """清洗用户输入的代理地址（去协议、去路径、去两端空白）"""
    host = (host or "").strip()
    host = re.sub(r"^[a-zA-Z]+://", "", host)
    host = host.split("/")[0]
    return host.strip()


def validate_host(host: str) -> tuple:
    """校验代理地址是合法的 IPv4 / IPv6 / 域名 -> (ok, msg)"""
    host = normalize_host(host)
    if not host:
        return False, "代理地址不能为空"

    # IPv6 带方括号
    if host.startswith("[") and host.endswith("]"):
        try:
            ipaddress.IPv6Address(host[1:-1])
            return True, ""
        except ValueError:
            return False, "IPv6 地址格式无效"

    # 纯 IPv6（无方括号）
    if host.count(":") >= 2:
        try:
            ipaddress.IPv6Address(host)
            return True, ""
        except ValueError:
            return False, "IPv6 地址格式无效"

    # IPv4
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host):
        for seg in host.split("."):
            if not 0 <= int(seg) <= 255:
                return False, "IPv4 每段须在 0-255 之间"
        return True, ""

    # 域名
    if re.fullmatch(
        r"(?=.{1,253}$)"
        r"([a-zA-Z0-9_]([a-zA-Z0-9\-_]{0,61}[a-zA-Z0-9_])?\.)*"
        r"[a-zA-Z0-9_]([a-zA-Z0-9\-_]{0,61}[a-zA-Z0-9_])?\.?",
        host,
    ):
        return True, ""

    return False, "既不是有效的 IP，也不是有效的域名"


def validate_port(port: str) -> tuple:
    """校验端口 -> (ok, msg)"""
    port = (port or "").strip()
    if not port:
        return False, "端口不能为空"
    if not port.isdigit():
        return False, "端口必须是数字"
    if not 1 <= int(port) <= 65535:
        return False, "端口须在 1-65535 之间"
    return True, ""


def looks_like_ipv4(host: str) -> bool:
    """输入的「意图」是否是一串点分十进制数字。

    用于把「192.168.1」这类不完整 IPv4 从域名分支里摘出来单独判错 ——
    否则它会被域名正则当成合法的单标签主机名而放行。
    """
    host = normalize_host(host)
    if not host:
        return False
    # 含字母/冒号/方括号 -> 明确是域名或 IPv6，不按 IPv4 意图处理
    if any(ch.isalpha() or ch in ":[]" for ch in host):
        return False
    return all(ch.isdigit() or ch == "." for ch in host)


def validate_host_live(host: str) -> tuple:
    """实时校验：在 validate_host 之上，额外拦截「像 IPv4 但不完整」的输入。

    返回 (ok, msg)。空串视为未填写（ok=False，但调用方可据此不放行按钮）。
    """
    host = normalize_host(host)
    if not host:
        return False, "代理地址不能为空"
    if looks_like_ipv4(host):
        # 必须是完整的 4 段，且每段 0-255
        if host.count(".") != 3:
            return False, "IPv4 地址须为 4 段，例如 192.168.1.1"
        for seg in host.split("."):
            if seg == "":
                return False, "IPv4 地址不能有空段"
            if len(seg) > 3:
                return False, "IPv4 每段最多 3 位数字"
            if not 0 <= int(seg) <= 255:
                return False, "IPv4 每段须在 0-255 之间"
        return True, ""
    return validate_host(host)


def resolve_host(host: str, timeout: float = 3.0):
    """把主机名解析成 IP（用于展示），失败返回 None"""
    host = normalize_host(host).strip("[]")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    old = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        infos = socket.getaddrinfo(host, None)
        return infos[0][4][0] if infos else None
    except (socket.gaierror, OSError):
        return None
    finally:
        socket.setdefaulttimeout(old)


# ── 归属地查询（纯标准库 urllib） ──

GEO_API = "http://ip-api.com/json/{ip}?fields=status,country,city,isp,org,query&lang=zh-CN"


def build_geo_url(ip: str = "") -> str:
    """构建 ip-api.com 归属地查询 URL（不传 ip 则返回出口 IP 归属地）"""
    return GEO_API.format(ip=ip)


def parse_geo_response(raw: bytes) -> dict:
    """解析 ip-api.com JSON 响应"""
    return json.loads(raw.decode("utf-8"))
