# -*- coding: utf-8 -*-
"""memory.embedding — v2.4 §22 向量路（1:1 复刻 vector 模式的 embedding 依赖）。

OpenAI 兼容 /embeddings 协议（openai/硅基流动/智谱/ollama+base_url 均可用）；
容器代理劫持防护（ProxyHandler({})）；api_key 空则向量路整体关闭；
失败容错（不阻塞其余三路检索）。
"""
import json
import urllib.request

_T = None  # 延迟注入的超时函数（便于单测）


def _post_embeddings(base_url, api_key, model, texts, timeout=15):
    # 容错：用户把完整端点（含 /embeddings 尾巴）填进 base_url 时剥离
    if base_url.rstrip("/").endswith("/embeddings"):
        base_url = base_url.rstrip("/")[: -len("/embeddings")]
    body = json.dumps({"model": model, "input": texts}).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/embeddings", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    # OpenAI 兼容返回 {"data":[{"embedding":[...],"index":0},...]}
    return [d["embedding"] for d in sorted(data["data"], key=lambda x: x["index"])]


def cosine(a, b) -> float:
    """余弦相似度（零依赖；dim 为 0 时返回 -1 表示无效）。"""
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na <= 0 or nb <= 0:
        return -1.0
    return dot / (na * nb)


class EmbeddingClient:
    """插件侧 embedding 客户端（配置驱动，api_key 空即 disabled）。"""

    def __init__(self, cfg: dict):
        self.provider = str(cfg.get("embedding_provider") or "")
        self.model = str(cfg.get("embedding_model") or "")
        self.api_key = str(cfg.get("embedding_api_key") or "")
        self.base_url = str(cfg.get("embedding_base_url") or "")
        self.dim = int(cfg.get("embedding_dim") or 0)
        # 可写普通属性（测试/运行时可临时切换；api_key 空=向量路关闭）
        self.enabled = bool(self.api_key and self.model and
                            (self.base_url or self.provider))

    def _default_base(self) -> str:
        return {"openai": "https://api.openai.com/v1",
                "siliconflow": "https://api.siliconflow.cn/v1",
                "zhipu": "https://open.bigmodel.cn/api/paas/v4",
                "ollama": "http://127.0.0.1:11434/v1"}.get(self.provider, "")

    def embed(self, texts) -> list:
        """批量向量化（失败抛异常，调用方容错）。"""
        if not self.enabled or not texts:
            return []
        base = self.base_url or self._default_base()
        return _post_embeddings(base, self.api_key, self.model,
                                [str(t)[:2000] for t in texts])
