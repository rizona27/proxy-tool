"""代理核心操作：注册表读写、代理类型格式化、归属地辅助"""
import json
import winreg
import ctypes
from PyQt5.QtCore import QUrl
from PyQt5.QtNetwork import QNetworkRequest

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


# ── 注册表操作 ──

def get_current_proxy():
    """获取当前系统代理设置 -> (status_str, server_str)"""
    try:
        reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH)
        enabled, _ = winreg.QueryValueEx(reg_key, "ProxyEnable")
        status = "已启用" if enabled else "已禁用"
        try:
            server, _ = winreg.QueryValueEx(reg_key, "ProxyServer")
        except FileNotFoundError:
            server = "未设置"
        winreg.CloseKey(reg_key)
        return status, server
    except (FileNotFoundError, PermissionError, OSError) as e:
        return "未知", f"无法获取 ({e})"


def enable_proxy_registry(ip: str, port: str, proxy_type: str) -> str:
    """写入注册表启用代理，返回写入的 ProxyServer 值"""
    proxy_server = format_proxy_server(ip, port, proxy_type)
    reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_WRITE)
    winreg.SetValueEx(reg_key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
    winreg.SetValueEx(reg_key, "ProxyServer", 0, winreg.REG_SZ, proxy_server)
    winreg.CloseKey(reg_key)
    return proxy_server


def disable_proxy_registry():
    """写入注册表禁用代理"""
    reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_WRITE)
    winreg.SetValueEx(reg_key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
    winreg.CloseKey(reg_key)


def set_bypass_local(enabled: bool):
    """设置是否绕过本地地址 (ProxyOverride = <local>)"""
    reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_WRITE)
    if enabled:
        winreg.SetValueEx(reg_key, "ProxyOverride", 0, winreg.REG_SZ, "<local>")
    else:
        try:
            winreg.DeleteValue(reg_key, "ProxyOverride")
        except FileNotFoundError:
            pass
    winreg.CloseKey(reg_key)


def get_bypass_local() -> bool:
    """读取当前是否绕过本地地址"""
    try:
        reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH)
        try:
            val, _ = winreg.QueryValueEx(reg_key, "ProxyOverride")
            winreg.CloseKey(reg_key)
            return val == "<local>"
        except FileNotFoundError:
            winreg.CloseKey(reg_key)
            return False
    except (FileNotFoundError, PermissionError, OSError):
        return False


def refresh_system():
    """通过 WinInet API 刷新系统代理设置"""
    INTERNET_OPTION_SETTINGS_CHANGED = 39
    INTERNET_OPTION_REFRESH = 37
    internet_set_option = ctypes.windll.Wininet.InternetSetOptionW
    internet_set_option(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
    internet_set_option(0, INTERNET_OPTION_REFRESH, 0, 0)


# ── 代理服务器格式转换 ──

def format_proxy_server(ip: str, port: str, proxy_type: str) -> str:
    """构建注册表 ProxyServer 值"""
    if proxy_type.upper() == "SOCKS5":
        return f"socks={ip}:{port}"
    return f"{ip}:{port}"


def parse_proxy_server(server_str: str):
    """解析注册表 ProxyServer 值 -> (ip, port, type)"""
    if not server_str:
        return "", "", "HTTP"

    # protocol=host:port 格式 (如 socks=1.2.3.4:1080)
    if "=" in server_str:
        parts = server_str.split(";")
        for part in parts:
            part = part.strip()
            if "=" not in part:
                continue
            proto, server = part.split("=", 1)
            proto = proto.strip().upper()
            server = server.strip()
            if proto in ("SOCKS", "SOCKS5"):
                if ":" in server:
                    ip, port = server.rsplit(":", 1)
                    return ip, port, "SOCKS5"
                return server, "", "SOCKS5"
            elif proto in ("HTTP", "HTTPS"):
                if ":" in server:
                    ip, port = server.rsplit(":", 1)
                    return ip, port, "HTTP"

    # 纯 ip:port 格式 (默认 HTTP)
    if ":" in server_str:
        ip, port = server_str.rsplit(":", 1)
        return ip, port, "HTTP"

    return server_str, "", "HTTP"


# ── 归属地查询 ──

def is_private_ip(ip: str) -> bool:
    """判断是否为私有/内网/回环地址"""
    try:
        parts = [int(p) for p in ip.split(".")]
        if len(parts) != 4:
            return False
        if parts[0] == 10:
            return True
        if parts[0] == 172 and 16 <= parts[1] <= 31:
            return True
        if parts[0] == 192 and parts[1] == 168:
            return True
        if parts[0] == 127:
            return True
        return False
    except (ValueError, IndexError):
        return False


def make_geo_request(ip: str) -> QNetworkRequest:
    """构建 ip-api.com 归属地查询请求"""
    url = QUrl(f"http://ip-api.com/json/{ip}?fields=status,country,city,isp,org,query&lang=zh-CN")
    req = QNetworkRequest(url)
    req.setAttribute(QNetworkRequest.FollowRedirectsAttribute, True)
    return req


def parse_geo_response(raw_data: bytes) -> dict:
    """解析 ip-api.com JSON 响应 -> dict"""
    return json.loads(raw_data.decode("utf-8"))
