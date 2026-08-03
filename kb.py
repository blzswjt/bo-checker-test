"""
知识库管理模块
- 存储用户手动确认/纠正的识别结果
- 提供已知正例和反例供 LLM 参考
- 支持增删改查，持久化到 JSON 文件
"""
import json
import threading
from pathlib import Path
from datetime import datetime

KB_PATH = Path(__file__).parent / "knowledge.json"
_kb_lock = threading.Lock()

DEFAULT_KB = {
    "confirmed_examples": {},
    "corrections": [],
    "custom_rules": {}
}


def load() -> dict:
    """加载知识库"""
    if KB_PATH.exists():
        try:
            with open(KB_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {**DEFAULT_KB, "confirmed_examples": {}, "corrections": [], "custom_rules": {}}


def save(kb: dict):
    """保存知识库到文件"""
    with open(KB_PATH, 'w', encoding='utf-8') as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)


def add_example(element_type: str, item: str, is_match: bool, reason: str = ""):
    """添加一个已确认的示例到知识库"""
    with _kb_lock:
        kb = load()
        if element_type not in kb["confirmed_examples"]:
            kb["confirmed_examples"][element_type] = []

        examples = kb["confirmed_examples"][element_type]

        # 如果已存在同名项，更新它
        for ex in examples:
            if ex["item"] == item:
                ex["is_match"] = is_match
                ex["reason"] = reason
                ex["timestamp"] = datetime.now().isoformat()
                save(kb)
                return

        examples.append({
            "item": item,
            "is_match": is_match,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        })
        save(kb)


def remove_example(element_type: str, item: str):
    """从知识库中删除一个示例"""
    with _kb_lock:
        kb = load()
        if element_type in kb["confirmed_examples"]:
            kb["confirmed_examples"][element_type] = [
                ex for ex in kb["confirmed_examples"][element_type]
                if ex["item"] != item
            ]
            save(kb)


def add_correction(item: str, element_type: str,
                   original_result: bool, corrected_result: bool,
                   reason: str = ""):
    """记录一次用户的纠正，并自动扩充实例库"""
    with _kb_lock:
        kb = load()
        correction = {
            "item": item,
            "element_type": element_type,
            "original": original_result,
            "corrected": corrected_result,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        }
        kb["corrections"].append(correction)

        # 1. 加入当前元素类型的已确认示例
        _add_example_unlocked(kb, element_type, item, corrected_result, reason)

        # 2. 自动扩充到相关元素类型：
        #    如果纠正为“是某类型”，同时作为相邻类型的参考示例
        #    例如：纠正为“是业务对象”→ 加入“逻辑实体”的反例（业务对象不是逻辑实体）
        from rules import ELEMENT_TYPES
        if corrected_result is True:
            # 当前类型是X → 其他类型的反例参考（避免误归类）
            for other_type in ELEMENT_TYPES:
                if other_type == element_type:
                    continue
                _add_example_unlocked(
                    kb, other_type, item, False,
                    f"[自动扩充] 已确认为{element_type}，不属于{other_type}"
                )
        # corrected_result is False 不自动扩充正例（避免引入噪声）

        save(kb)


def _add_example_unlocked(kb: dict, element_type: str, item: str, is_match: bool, reason: str = ""):
    """内部使用：不加锁地添加示例（需在 _kb_lock 内调用）"""
    if element_type not in kb["confirmed_examples"]:
        kb["confirmed_examples"][element_type] = []
    examples = kb["confirmed_examples"][element_type]
    for ex in examples:
        if ex["item"] == item:
            ex["is_match"] = is_match
            ex["reason"] = reason
            ex["timestamp"] = datetime.now().isoformat()
            return
    examples.append({
        "item": item,
        "is_match": is_match,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    })


def _similarity(a: str, b: str) -> float:
    """计算两个字符串的相似度（0~1），基于字符级 n-gram 重叠"""
    if not a or not b:
        return 0.0
    # 完全包含关系给高分
    if a in b or b in a:
        return 0.85
    # 2-gram 重叠
    def ngrams(s, n=2):
        return set(s[i:i+n] for i in range(len(s) - n + 1))
    na, nb = ngrams(a), ngrams(b)
    if not na or not nb:
        # 单字符回退到精确匹配
        return 1.0 if a == b else 0.0
    overlap = len(na & nb)
    return overlap / max(len(na), len(nb))


def get_examples(element_type: str, max_per_side: int = 8, items: list[str] = None) -> dict:
    """
    获取指定元素类型的已知正例和反例，供 LLM Prompt 使用。
    返回 {"positive": [...], "negative": [...]}
    如果传入 items，则按与待判断事物的相似度排序（智能选取）；
    否则按时间倒序。
    """
    kb = load()
    examples = kb["confirmed_examples"].get(element_type, [])

    positive = [ex for ex in examples if ex.get("is_match") is True]
    negative = [ex for ex in examples if ex.get("is_match") is False]

    if items and len(items) > 0:
        # 智能选取：按与待判断事物的最大相似度排序
        def relevance_score(ex):
            item_name = ex.get("item", "")
            return max(_similarity(item_name, target) for target in items)
        positive.sort(key=relevance_score, reverse=True)
        negative.sort(key=relevance_score, reverse=True)
    else:
        # 回退：按时间倒序
        positive.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        negative.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    return {
        "positive": positive[:max_per_side],
        "negative": negative[:max_per_side]
    }


def get_all() -> dict:
    """获取完整知识库（供前端展示和编辑）"""
    return load()


def update_all(kb_data: dict):
    """整体替换知识库（供前端编辑器保存）"""
    with _kb_lock:
        save(kb_data)
