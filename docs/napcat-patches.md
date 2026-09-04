# napcat 插件补丁记录（面向 QQ 真机接入）

本仓库（hermes-alive）通过 [napcat](https://github.com/landamao/hermes-qq-onebot) 插件（MIT，作者 懒大猫）接入 QQ。原版插件存在两处会在真实部署环境立刻暴露的问题，本文记录我们打的两处补丁的根因与修法，供同样在容器/代理环境下部署的用户参考。**补丁尚未回馈上游**，若你遇到同样问题可直接参考此处自行修改。

> 补丁针对的 napcat 版本：3.1.0（`plugin.yaml` version）。

## 补丁一：HTTP 通道被环境代理劫持（本机地址绕行）

**现象**

容器部署常见 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量（出网代理）。napcat 插件的 HTTP API 调用（`napcat_http.py`）与媒体下载（`tools.py`）使用裸 `urllib.request.urlopen` —— 该函数读取环境代理变量，于是**连本机 NapCat 的请求（`http://127.0.0.1:3000/...`）也被送进代理**，被代理以 502 拒绝。接真实 NapCat 后：HTTP 通道全灭、图片下载全灭。

**根因**

- `urlopen` 默认 opener 继承 `HTTP(S)_PROXY` 环境变量
- 本机回环地址（127.0.0.1 / localhost / ::1）不应该走任何代理

**修法**

1. `napcat_http.py`：模块级构建专用 opener，所有对 NapCat HTTP API 的调用改走它：

```python
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
```

2. `tools.py`：媒体下载按目标地址**分流**——本机地址绕代理，外网 CDN 维持默认（走代理出网，否则容器内无法访问外网媒体）：

```python
def _是本机地址(地址: str) -> bool:
    # hostname ∈ {127.*, localhost, ::1, 0.0.0.0} 视为本机
    ...

opener = _NO_PROXY_OPENER if _是本机地址(地址) else urllib.request.build_opener()
# HEAD 预检与流式下载两处 urlopen → opener.open
```

**验证**

同一请求走修复 opener 得到 `status=ok`；对照组用原生 `urlopen` 复现 502。媒体下载链（图片/语音）在 `file_size` 正确时完成落盘。

## 补丁二：超时措辞触发网关错误兜底（英文残骸 + 重复投递）

**现象**

反向 WS 下某次发送的响应丢失（如 NapCat 卡死、网络断帧）时，插件在 120s 超时后返回失败。网关侧 `send_with_retry` 随后做了两件错事：

1. 把这次失败当作"格式失败"，给用户发了一条 **`(Response formatting failed, plain text:)` 英文残骸**；
2. 兜底重发 —— 但首条消息**可能已经送达**，用户收到重复消息。

**根因**

网关的超时分类器 `_is_timeout_error()` 只识别英文 token（`timed out` / `readtimeout` / `writetimeout`），而插件的超时措辞是纯中文「超时未响应」——两头不沾，落进"非网络/非超时"分支，触发纯文本兜底。

**修法**

1. `ws.py` 超时措辞改为携带分类 token（一行）：

```python
# 网关按超时语义处理：不重试（防重复投递）、不触发纯文本兜底
return {"status": "failed",
        "msg": "WebSocket timed out: 「{动作}」超时未响应（消息可能已送达）"}
```

2. `main.py` 图片发送 WS 回退路径的超时判定同步统一（原 `"timeout" in 错误.lower()` 对中文措辞恒不命中，属死代码）：

```python
if any(p in 错误.lower() for p in ("timeout", "timed out")) or "超时" in 错误:
```

**验证**

- 功能级：真触发 `wait_for` 超时 + 网关真实分类器断言（超时类 → 不重试、不兜底）
- E2E：模拟"吞响应"故障 → 恰 120.0s 超时 → 网关无兜底消息、无重复投递

## 复现环境说明

两处问题均在**高保真协议模拟器**上首次暴露（响应包装/echo/超时/断链行为逐字段对齐 NapCatQQ 源码），无需真实 QQ 账号即可复现与验证。相关思想：先模拟协议端再接真机，能把"接入即翻车"类问题清在接入之前。
