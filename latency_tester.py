"""TCP 连接 + HTTP 代理出口延迟 + 出口归属地检测线程"""
import json
import time
import socket
import urllib.request
import urllib.error
from PyQt5.QtCore import QThread, pyqtSignal


class LatencyTester(QThread):
    # tcp_ms:       TCP 连接到代理的延迟 (负数=失败)
    # egress_ms:    通过代理访问公网的往返延迟 (负数=失败/超时/不支持)
    # egress_geo:   出口 IP 归属地 dict (country, city, isp, query)
    # error:        错误消息
    result_ready = pyqtSignal(float, float, dict, str)

    def __init__(self, host: str, port: int, proxy_type: str = "HTTP",
                 timeout: int = 5, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self.proxy_type = proxy_type
        self.timeout = timeout
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        if self._is_cancelled:
            return

        tcp_ms = self._test_tcp()

        egress_ms = -1.0
        egress_geo = {}
        if self.proxy_type.upper() == "HTTP" and tcp_ms > 0 and not self._is_cancelled:
            egress_ms, egress_geo = self._test_egress()

        if not self._is_cancelled:
            self.result_ready.emit(tcp_ms, egress_ms, egress_geo, "")

    def _test_tcp(self) -> float:
        """TCP 连接到代理，返回延迟 ms"""
        try:
            start = time.monotonic()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect((self.host, self.port))
            sock.close()
            return (time.monotonic() - start) * 1000
        except socket.timeout:
            return -1.0
        except ConnectionRefusedError:
            return -2.0
        except OSError:
            return -3.0
        except Exception:
            return -4.0

    def _test_egress(self):
        """通过 HTTP 代理请求 ip-api.com，同时测量延迟和获取出口归属地。
        返回 (latency_ms, geo_dict)"""
        proxy_url = f"http://{self.host}:{self.port}"
        proxy_handler = urllib.request.ProxyHandler({
            'http': proxy_url,
            'https': proxy_url,
        })
        opener = urllib.request.build_opener(proxy_handler)

        # 请求 ip-api.com（不带 IP 参数 = 返回出口 IP 的归属地）
        test_url = "http://ip-api.com/json/?fields=status,country,city,isp,query&lang=zh-CN"
        req = urllib.request.Request(test_url)

        try:
            start = time.monotonic()
            resp = opener.open(req, timeout=self.timeout)
            raw = resp.read()
            resp.close()
            elapsed_ms = (time.monotonic() - start) * 1000

            data = json.loads(raw.decode("utf-8"))
            if data.get("status") == "success":
                return elapsed_ms, data
            return elapsed_ms, {}
        except (urllib.error.URLError, socket.timeout):
            return -5.0, {}
        except (json.JSONDecodeError, Exception):
            return -7.0, {}
