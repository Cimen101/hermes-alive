# -*- coding: utf-8 -*-
"""memory.normalize — 记忆标题归一与检索分词（P1）。

归一规则与兴趣名归一同族（原 `_normalize_interest_name`，自插件入口抽出以便
memory 子模块与入口共用，避免循环依赖）。
"""
import re

# 装饰符剥离集（与兴趣归一保持同一字符集）
TITLE_JUNK = "《》「」『』【】[]“”‘’\"'"

# 中文停用词（自建常量表，代词/助词/高频虚词——检索种子去噪用）
STOPWORDS = frozenset({
    "我", "你", "他", "她", "它", "我们", "你们", "他们", "她们", "它们",
    "自己", "咱", "咱们", "这", "那", "这个", "那个", "这些", "那些",
    "哪", "哪个", "哪些", "谁", "什么", "怎么", "怎样", "多少",
    "的", "了", "着", "过", "地", "得", "是", "在", "有", "和", "与",
    "就", "都", "而", "及", "或", "一个", "一下", "一些", "一下子",
    "不", "没", "没有", "别", "很", "挺", "还", "也", "又", "再", "才",
    "要", "想", "会", "能", "可以", "应该", "需要", "可能", "好像",
    "对", "跟", "和", "被", "把", "让", "给", "向", "从", "到", "上",
    "下", "里", "外", "中", "前", "后", "时", "时候", "现在", "今天",
    "明天", "昨天", "最近", "然后", "但是", "因为", "所以", "如果",
    "虽然", "还是", "就是", "比如", "例如", "等等", "之类", "一下",
    "啊", "吧", "呢", "吗", "呀", "哈", "嗯", "哦", "啦", "嘛",
})


def normalize_title(raw) -> str:
    """记忆标题归一：剥装饰符、压空白、截 30 字（与兴趣名归一同一规则）。"""
    s = "".join(ch for ch in str(raw or "") if ch not in TITLE_JUNK)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:30]


def extract_tokens(text: str) -> set:
    """检索分词：正则切段（剔标点/空格）+ 段内 2-gram + 停用词过滤。

    中文零依赖分词方案；段整词也收录（两字词与短词精确命中）。
    bigram 过滤只剔"双停用字"组合（的了/了吧）与整词停用——原"任一字为
    停用字即丢"的规则误杀真词（前端/上班/中餐），E2E 实证：查"前端"
    找不到"做前端开发"（单停用字组合如"球和"有轻度噪声，但节点侧噪声
    不参与交集惩罚，查询侧稀释可接受，换来真词召回）。
    v2.4 §21：不再复用 normalize_title 的 30 字标题截断——经历条目/节点
    content 是长文本，30 字截断把后半内容全截没（实测"健身房办卡"被截
    成"健"致检索 miss）；分词自清洗，400 字上限防极端长文。
    """
    s = "".join(ch for ch in str(text or "") if ch not in TITLE_JUNK)
    s = re.sub(r"\s+", " ", s).strip()[:400]
    if not s:
        return set()
    tokens = set()
    for seg in re.findall(r"[0-9A-Za-z\u4e00-\u9fff]+", s):
        if len(seg) <= 2:
            if seg not in STOPWORDS:
                tokens.add(seg)
            continue
        if seg not in STOPWORDS:
            tokens.add(seg)
        for i in range(len(seg) - 1):
            g = seg[i:i + 2]
            if g in STOPWORDS:
                continue
            if g[0] in STOPWORDS and g[1] in STOPWORDS:
                continue
            tokens.add(g)
    return tokens


def jaccard(a: set, b: set) -> float:
    """Jaccard 相似度（MMR 多样性用）。"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / len(a | b)


def overlap(a: set, b: set) -> float:
    """重叠系数 inter/min(|a|,|b|)——短文本重复检测用（n-gram 字级下
    比 Jaccard 合理：小集合被大集合覆盖度高即重复，避免长度差稀释分值）。"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / min(len(a), len(b))
