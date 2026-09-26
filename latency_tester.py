"""延迟检测 + 归属地查询：纯标准库实现（socket / urllib / threading）

不依赖 Qt 或任何第三方库。回调在工作线程中触发，
调用方负责把结果切回主线程（Tkinter 里用 root.after）。
"""
import json
import socket
import threading
import time
import urllib.error
import urllib.request

from proxy_core import build_geo_url, parse_geo_response

# ── 错误码（与 UI 展示共用） ──
ERR_TIMEOUT = -1.0        # TCP 连接超时
ERR_REFUSED = -2.0        # 连接被拒绝
ERR_UNREACHABLE = -3.0    # 网络不可达
ERR_FAILED = -4.0         # 其他失败
ERR_EGRESS_FAILED = -5.0  # 出口请求失败
ERR_EGRESS_BAD = -6.0     # 出口响应无法解析
ERR_CANCELLED = -9.0      # 已取消

_ERR_TEXT = {
    ERR_TIMEOUT: "超时",
    ERR_REFUSED: "拒绝",
    ERR_UNREACHABLE: "不可达",
    ERR_FAILED: "失败",
    ERR_EGRESS_FAILED: "失败",
    ERR_EGRESS_BAD: "解析失败",
    ERR_CANCELLED: "已取消",
}


def error_text(code: float) -> str:
    """把错误码转成中文提示"""
    return _ERR_TEXT.get(code, "失败")


class LatencyTester:
    """在独立线程中执行延迟检测。

    on_result(tcp_ms, egress_ms, egress_geo, error_text) 在工作线程中调用。
    cancel() 可安全中止：socket 使用短超时并轮询取消标志。
    """

    def __init__(self, host: str, port: int, proxy_type: str = "HTTP",
                 timeout: float = 5.0):
        self.host = host
        self.port = port
        self.proxy_type = proxy_type
        self.timeout = timeout
        self._cancelled = threading.Event()
        self._thread = None

    # ── 生命周期 ──

    def start(self, on_result, on_finished=None):
        self._thread = threading.Thread(
            target=self._run, args=(on_result, on_finished), daemon=True)
        self._thread.start()

    def cancel(self):
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ── 主流程 ──

    def _run(self, on_result, on_finished):
        try:
            if self.cancelled:
                return
            tcp_ms = self._test_tcp()
            if self.cancelled:
                return

            egress_ms, egress_geo = ERR_EGRESS_FAILED, {}
            if tcp_ms > 0 and self.proxy_type.upper() == "HTTP":
                egress_ms, egress_geo = self._test_egress()

            if not self.cancelled:
                on_result(tcp_ms, egress_ms, egress_geo, "")
        except Exception as e:            # 兜底，避免线程静默崩溃
            if not self.cancelled:
                on_result(ERR_FAILED, ERR_EGRESS_FAILED, {}, str(e))
        finally:
            if on_finished and not self.cancelled:
                on_finished()

    # ── TCP 到代理 ──

    def _test_tcp(self) -> float:
        """TCP 连接到代理端口，返回毫秒延迟（负数=失败）"""
        deadline = time.monotonic() + 3.0
        family = socket.AF_INET6 if ":" in self.host else socket.AF_INET
        target = (self.host, self.port)
        sock = None
        try:
            start = time.monotonic()
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(0.4)              # 短超时 + 轮询，便于及时取消
            while True:
                if self.cancelled:
                    return ERR_CANCELLED
                try:
                    sock.connect(target)
                    return (time.monotonic() - start) * 1000
                except socket.timeout:
                    if time.monotonic() >= deadline:
                        return ERR_TIMEOUT
                    continue
        except ConnectionRefusedError:
            return ERR_REFUSED
        except socket.gaierror:
            return ERR_UNREACHABLE
        except OSError as e:
            return ERR_UNREACHABLE if getattr(e, "errno", None) in (10051, 101, 113) else ERR_FAILED
        except Exception:
            return ERR_FAILED
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    # ── 出口延迟 + 归属地 ──

    def _test_egress(self):
        """通过 HTTP 代理请求 ip-api.com，返回 (latency_ms, geo_dict)"""
        proxy_host = self.host
        if ":" in proxy_host and not proxy_host.startswith("["):
            proxy_host = f"[{proxy_host}]"       # IPv6 需方括号
        proxy_url = f"http://{proxy_host}:{self.port}"
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))

        req = urllib.request.Request(
            build_geo_url(), headers={"User-Agent": "ProxyTool/3.0"})
        try:
            start = time.monotonic()
            with opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read()
            elapsed_ms = (time.monotonic() - start) * 1000
            if self.cancelled:
                return ERR_CANCELLED, {}
        except (urllib.error.URLError, socket.timeout, OSError):
            return ERR_EGRESS_FAILED, {}
        except Exception:
            return ERR_EGRESS_FAILED, {}

        try:
            data = parse_geo_response(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return ERR_EGRESS_BAD, {}

        if data.get("status") == "success":
            return elapsed_ms, data
        return elapsed_ms, {}


# ── 归属地查询（独立轻量线程） ──

class GeoLookup:
    """查询任意 IP / 主机名的归属地，走直连不受系统代理影响"""

    def __init__(self, ip: str, timeout: float = 5.0):
        self.ip = ip
        self.timeout = timeout

    def start(self, on_result):
        threading.Thread(target=self._run, args=(on_result,), daemon=True).start()

    def _run(self, on_result):
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(
                build_geo_url(self.ip), headers={"User-Agent": "ProxyTool/3.0"})
            with opener.open(req, timeout=self.timeout) as resp:
                on_result(parse_geo_response(resp.read()), "")
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            on_result({}, f"查询失败: {e}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            on_result({}, "响应解析失败")
        except Exception as e:
            on_result({}, f"查询异常: {e}")


class EgressLookup:
    """查询本机直连出口 IP 归属地，走直连不受系统代理影响"""

    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout

    def start(self, on_result):
        threading.Thread(target=self._run, args=(on_result,), daemon=True).start()

    def _run(self, on_result):
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(
                build_geo_url(), headers={"User-Agent": "ProxyTool/3.0"})
            with opener.open(req, timeout=self.timeout) as resp:
                on_result(parse_geo_response(resp.read()), "")
        except Exception as e:
            on_result({}, str(e))
