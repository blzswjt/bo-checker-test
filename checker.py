"""
核心检测逻辑 - Excel解析 + 流式识别 + JSON解析

模块分区：
  1. Excel解析: parse_excel_file, extract_column_values, find_target_column
  2. 流式检测: check_items_stream（生成器，yield SSE事件）
  3. 实时解析: _parse_streaming_conclusions, _detect_streaming_rule_checks
  4. JSON解析: parse_llm_response, _extract_json_object
  5. 单个识别: check_single_item
"""
import json
import re
import time
import pandas as pd
from pathlib import Path
from llm import chat, chat_stream, get_model_display_name
from rules import build_batch_prompt, build_check_prompt, ELEMENT_TYPES, recommend_element_type
import kb

# ============================================================
# 0. Excel 文件缓存（避免同一文件被反复读取）
# ============================================================
_excel_cache: dict[str, tuple[float, dict[str, pd.DataFrame]]] = {}
_CACHE_TTL = 300  # 缓存有效期（秒）


def _get_all_sheets(file_path: str) -> dict[str, pd.DataFrame]:
    """带缓存地读取 Excel 所有子表"""
    now = time.time()
    cached = _excel_cache.get(file_path)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    all_sheets = pd.read_excel(file_path, sheet_name=None)
    _excel_cache[file_path] = (now, all_sheets)
    return all_sheets

# ============================================================
# 1. Excel解析
# ============================================================

def find_target_column(df: pd.DataFrame) -> tuple[str, list[str]]:
    """自动识别包含待检测事物的列"""
    keywords = [
        "业务对象唯一标识", "业务对象名称", "业务对象编码",
        "逻辑实体名称", "逻辑实体唯一标识",
        "属性名称", "属性唯一标识",
        "主题域名称", "主题域分类", "主题域分组",
        "对象名称", "对象名", "唯一标识",
        "业务对象", "名称", "实体", "单据", "事物"
    ]
    for col in df.columns:
        col_str = str(col).strip()
        for kw in keywords:
            if kw in col_str:
                values = df[col].dropna().astype(str).str.strip().tolist()
                values = [v for v in values if v and v != "nan" and len(v) > 1]
                if values:
                    return col_str, values

    candidates = []
    for col in df.columns:
        series = df[col].dropna()
        if len(series) < 2:
            continue
        sample = series.head(20)
        str_sample = sample.astype(str)
        numeric_count = str_sample.apply(lambda x: x.replace(".", "").replace("-", "").isdigit()).sum()
        if numeric_count > len(str_sample) * 0.7:
            continue
        date_pattern = re.compile(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}')
        date_count = str_sample.apply(lambda x: bool(date_pattern.match(str(x)))).sum()
        if date_count > len(str_sample) * 0.5:
            continue
        avg_len = str_sample.apply(len).mean()
        if avg_len > 80:
            continue
        values = series.astype(str).str.strip().tolist()
        values = [v for v in values if v and v != "nan" and len(v) > 1]
        if len(values) >= 2:
            candidates.append((str(col), values, avg_len))

    if candidates:
        candidates.sort(key=lambda x: (x[2], -len(x[1])))
        best = candidates[0]
        return best[0], best[1]

    col = str(df.columns[0])
    values = df.iloc[:, 0].dropna().astype(str).str.strip().tolist()
    values = [v for v in values if v and v != "nan" and len(v) > 1]
    return col, values


def parse_excel_file(file_path: str) -> dict:
    """
    解析Excel文件结构，返回所有子表、列信息和AI推荐列。
    不执行识别，只做结构解析。
    """
    path = Path(file_path)
    if not path.exists():
        return {"error": "文件不存在"}

    try:
        all_sheets = _get_all_sheets(file_path)
    except Exception as e:
        return {"error": f"读取Excel失败: {str(e)}"}

    if not all_sheets:
        return {"error": "Excel文件为空"}

    sheets = []
    ai_sheet = None
    ai_column = None
    ai_keyword = None

    # 通用关键词用于AI推荐
    all_keywords = [
        "业务对象唯一标识", "业务对象名称", "业务对象编码",
        "逻辑实体名称", "逻辑实体唯一标识",
        "属性名称", "属性唯一标识",
        "主题域名称", "主题域分类", "主题域分组",
        "唯一标识", "名称",
    ]

    for sheet_name, df in all_sheets.items():
        if df.empty:
            continue

        columns = []
        for col in df.columns:
            col_str = str(col).strip()
            series = df[col].dropna()
            values = series.astype(str).str.strip().tolist()
            values = [v for v in values if v and v != "nan"]
            sample = values[:5] if values else []

            columns.append({
                "name": col_str,
                "rows": len(series),
                "sample": sample,
                "unique_count": len(set(values)),
                "recommended_type": recommend_element_type(col_str),
            })

        sheets.append({
            "name": sheet_name,
            "rows": len(df),
            "columns": columns,
        })

        # AI推荐：在所有子表中找最佳匹配列（优先匹配高优先级关键词，找到即停止）
        if ai_column is None:
            for kw in all_keywords:
                found = False
                for col_info in columns:
                    if kw in col_info["name"] and col_info["rows"] > 0:
                        ai_sheet = sheet_name
                        ai_column = col_info["name"]
                        ai_keyword = kw
                        found = True
                        break
                if found:
                    break  # 已找到当前最高优先级关键词，停止搜索

    return {
        "total_sheets": len(all_sheets),
        "sheets": sheets,
        "ai_recommendation": {
            "sheet": ai_sheet,
            "column": ai_column,
            "keyword": ai_keyword,
        }
    }


def extract_column_values(file_path: str, sheet_name: str, column_name: str) -> list[str]:
    """从Excel中提取指定子表指定列的所有非空值（去重）"""
    all_sheets = _get_all_sheets(file_path)
    df = all_sheets.get(sheet_name)
    if df is None or df.empty:
        return []

    if column_name not in df.columns:
        # 尝试模糊匹配
        for col in df.columns:
            if str(col).strip() == column_name:
                column_name = col
                break

    series = df[column_name].dropna()
    values = series.astype(str).str.strip().tolist()
    values = [v for v in values if v and v != "nan" and len(v) > 1]
    return list(dict.fromkeys(values))  # 去重保序


def extract_item_context(file_path: str, sheet_name: str, column_name: str,
                         context_columns: list[str] = None) -> dict[str, dict]:
    """
    从Excel中提取每个条目的业务上下文。
    context_columns: 用户手动指定的上下文列名列表（按顺序拼接为路径）。
    返回 {item_name: {path: 'A → B → C', ctx_cols: {col_name: value}}} 映射。
    """
    all_sheets = _get_all_sheets(file_path)
    df = all_sheets.get(sheet_name)
    if df is None or df.empty:
        return {}

    # 找到目标列（模糊匹配）
    target_col = None
    for col in df.columns:
        if str(col).strip() == column_name:
            target_col = col
            break
    if target_col is None:
        return {}

    # 确定上下文列：优先用用户指定的，否则自动检测
    ctx_cols = []  # [(实际列名, 显示名)]
    def_col = None

    if context_columns:
        # 用户手动指定的上下文列
        for cc in context_columns:
            for col in df.columns:
                if str(col).strip() == cc:
                    ctx_cols.append((col, cc))
                    break
    else:
        # 自动检测 L1/L2/L3
        l1_col = l2_col = l3_col = None
        for col in df.columns:
            col_s = str(col).strip()
            if not l1_col and any(kw in col_s for kw in ['L1', '主题域分类']):
                l1_col = col
            elif not l2_col and any(kw in col_s for kw in ['L2', '主题域分组']):
                l2_col = col
            elif not l3_col and any(kw in col_s for kw in ['L3', '主题域']) and col != l1_col and col != l2_col:
                l3_col = col
        for c in [l1_col, l2_col, l3_col]:
            if c:
                ctx_cols.append((c, str(c).strip()))

    # 自动检测定义列
    for col in df.columns:
        col_s = str(col).strip()
        if any(kw in col_s for kw in ['定义', '说明', '描述']):
            def_col = col
            break

    if not ctx_cols and not def_col:
        return {}

    context_map = {}
    for _, row in df.iterrows():
        item_val = str(row.get(target_col, '')).strip()
        if not item_val or item_val == 'nan' or len(item_val) <= 1:
            continue
        if item_val not in context_map:
            ctx = {}
            parts = []
            for col, display_name in ctx_cols:
                v = str(row.get(col, '')).strip()
                if v and v != 'nan':
                    parts.append(v)
                    ctx[display_name] = v
            path = ' → '.join(parts) if parts else ''
            if path:
                ctx['path'] = path
            if def_col:
                v = str(row.get(def_col, '')).strip()
                if v and v != 'nan' and v != '同上':
                    ctx['definition'] = v
            if ctx:
                context_map[item_val] = ctx

    return context_map

# ============================================================
# 2. 流式结论/规则实时检测
# ============================================================

def _parse_streaming_conclusions(text: str, batch: list[str]):
    """从思考文本中实时提取已完成的结论，返回 (item_index, result_dict) 列表"""
    results = []
    for line in text.split('\n'):
        line_s = line.strip()
        # 跳过JSON块内的行
        if line_s.startswith('```') or line_s.startswith('{') or line_s.startswith('"results"'):
            continue
        # 检测新事物开始: 支持多种格式
        # - **1. 事物名** / 1. 事物名 / ### 1. 事物名 / #### 1. 事物名
        # - **### 1. 事物名** / #### 1. 事物名（含####） 等混合格式
        # 排除section标题（如 ## JSON结果 → "1. 结果"）
        if re.match(r'^#+\s+(?!\d)', line_s):
            continue
        m = re.match(r'(?:#+\s*)?(?:\*+\s*)?(\d+)[.\uff0e\u3001]\s*(.+?)(?:\s*\*+)?$', line_s)
        if m:
            num = int(m.group(1))
            name = m.group(2).strip().rstrip('*').strip()
            if name in _SECTION_WORDS or len(name) <= 1:
                continue
            if 1 <= num <= len(batch):
                results.append({'idx': num - 1, 'name': name, 'conclusion': None})
            continue
        # 检测结论行: 支持多种格式
        # - 结论：是 / - **结论：** 是 / 结论：是 / **结论：** 是
        # - **判定：** 是 / 判断：是 / 是否为业务对象：是
        m = re.match(r'[-\-\*>\s]*\**\s*(?:结论|判定|判断|是否业务对象|识别结果)\**\s*[：:]\s*(.*)', line_s)
        if m and results and results[-1]['conclusion'] is None:
            conclusion_text = m.group(1).strip().lstrip('*').strip()
            if '不是' in conclusion_text or '否' in conclusion_text:
                is_bo = False
                confidence = 'high'
            elif '是' in conclusion_text:
                is_bo = True
                confidence = 'high'
            else:
                is_bo = None
                confidence = 'medium'
            results[-1]['conclusion'] = {
                'is_bo': is_bo,
                'confidence': confidence,
                'reason': conclusion_text[:80],
            }
    return results


# 正则：检测规则判断行  ✓ 【规则名】理由  或  ✗ 【规则名】理由
_RULE_CHECK_RE = re.compile(r'[✓✗]\s*【(.+?)】\s*(.*)')
# 正则：检测事物标题 - 支持 #, **, 数字+点/顿号 等各种格式
# 额外要求：标题后面不能紧跟常见section标记词（如"结果"、"输出"、"分析"等）
_ITEM_HEADER_RE = re.compile(r'(?:#+\s*)?(?:\*+\s*)?(\d+)[.\uff0e\u3001]\s*(.+?)(?:\s*\*+)?$')
_SECTION_WORDS = {'结果', '输出', '分析', '思考', '说明', '总结', '概述', '判断', '识别', '命名', '定义'}


def _detect_streaming_rule_checks(text: str, batch: list[str], last_pos: int, emitted: dict):
    """从流式文本中实时检测规则判断行，返回新检测到的规则检查列表
    emitted: {item_idx: set(rule_names)} 已发射的规则集合，会就地更新
    简单可靠方案：每次扫描全文，通过emitted去重，性能开销可忽略
    """
    new_checks = []
    current_item_idx = -1

    for line in text.split('\n'):
        line_s = line.strip()

        # 跳过明显是section标题的行（## JSON结果、## 自然语言分析 等）
        # 但保留 ### 1. xxx（数字开头的不跳过）
        if re.match(r'^#+\s+(?!\d)', line_s):
            continue

        # 检测事物标题
        m = _ITEM_HEADER_RE.match(line_s)
        if m:
            num = int(m.group(1))
            name = m.group(2).strip().rstrip('*').strip()
            # 排除section标题误匹配（如 "1. 结果" "1. 输出"）
            if name in _SECTION_WORDS or len(name) <= 1:
                continue
            if 1 <= num <= len(batch):
                current_item_idx = num - 1
            continue

        # 检测规则判断行
        if current_item_idx >= 0:
            m = _RULE_CHECK_RE.search(line_s)
            if m:
                rule_name = m.group(1).strip()
                reason = m.group(2).strip()
                pass_check = '✓' in line_s[:line_s.find('【')]
                if current_item_idx not in emitted:
                    emitted[current_item_idx] = set()
                if rule_name not in emitted[current_item_idx]:
                    emitted[current_item_idx].add(rule_name)
                    new_checks.append({
                        'item_idx': current_item_idx,
                        'item_name': batch[current_item_idx],
                        'rule': rule_name,
                        'pass': pass_check,
                        'reason': reason[:100],
                    })

    return new_checks

# ============================================================
# 3. 流式识别主生成器
# ============================================================

def check_items_stream(items: list[str], element_type: str = "业务对象", batch_size: int = 5, model_id: str = None, context_map: dict = None, analysis_context: str = None):
    """
    生成器：逐批调用LLM判断，yield SSE事件。
    集成知识库示例，结果包含逐条规则分析(rules_check)。
    支持实时逐条输出：思考完一个事物的结论后立即显示结果。
    """
    total = len(items)
    model_name = get_model_display_name(model_id)
    yield {"type": "start", "total": total, "element_type": element_type, "model_id": model_id, "model_name": model_name}

    all_results: dict[str, dict] = {}  # {item_name: result_dict} O(1) 查找

    for i in range(0, total, batch_size):
        batch = items[i:i + batch_size]

        # 智能示例选取：每批根据当前 batch 内容获取最相关的 KB 示例
        kb_examples = kb.get_examples(element_type, items=batch)
        numbered = "\n".join(f"{j+1}. {item}" for j, item in enumerate(batch))

        prompt = build_batch_prompt(element_type, numbered, kb_examples=kb_examples, context_map=context_map, analysis_context=analysis_context)
        if not prompt:
            for j, item in enumerate(batch):
                result = {"item": item, "is_bo": None, "confidence": "low", "reason": f"未知元素类型: {element_type}", "rules_check": []}
                all_results[item] = result
                yield {"type": "result", "index": i + j, **result}
            yield {"type": "progress", "current": min(i + len(batch), total), "total": total}
            continue

        messages = [
            {"role": "system", "content": "你是数据治理专家。请先用自然语言对每个事物进行分析思考，然后再输出JSON结果。"},
            {"role": "user", "content": prompt}
        ]

        try:
            # 流式调用：实时推送思考过程 + 实时逐条检测结果
            batch_idx = i // batch_size
            yield {"type": "thinking_start", "batch_index": batch_idx}
            full_response = ""
            json_started = False
            emitted_indices = set()  # 已经通过思考解析发射的结果索引
            _pending_items = set()   # 已发射 item_pending 的条目索引
            _last_parse_len = 0  # 上次解析到的位置，避免重复解析
            _item_scan_pos = 0   # item_header 扫描位置（避免重复扫描）
            _rule_check_emitted = {}  # {item_idx: set(rule_names)} 已发射的规则检查
            _rule_check_last_pos = 0  # 规则检查解析位置

            for token in chat_stream(messages, temperature=0.1, model_id=model_id):
                full_response += token
                # 检测JSON块开始，停止推送思考token
                if not json_started:
                    if '```json' in full_response or '`{' in full_response or (full_response.count('{') > 0 and '"results"' in full_response):
                        json_started = True
                    else:
                        yield {"type": "thinking", "batch_index": batch_idx, "token": token}

                    # 实时检测规则判断行，立即发射逐条规则更新
                    if '\n' in full_response[_rule_check_last_pos:]:
                        _rule_check_last_pos = len(full_response)
                        checks = _detect_streaming_rule_checks(
                            full_response, batch, max(0, _rule_check_last_pos - 2000),
                            _rule_check_emitted
                        )
                        for ck in checks:
                            yield {
                                "type": "rule_check",
                                "batch_index": batch_idx,
                                "item_index": i + ck['item_idx'],
                                "item_name": ck['item_name'],
                                "rule": ck['rule'],
                                "pass": ck['pass'],
                                "reason": ck['reason'],
                            }

                    # 实时检测新条目开始分析（检测到标题行立即通知前端显示占位行）
                    if '\n' in full_response[_item_scan_pos:]:
                        _new_end = len(full_response)
                        _new_text = full_response[_item_scan_pos:_new_end]
                        for _scan_line in _new_text.split('\n'):
                            _scan_ls = _scan_line.strip()
                            _hm = _ITEM_HEADER_RE.match(_scan_ls)
                            if _hm:
                                _num = int(_hm.group(1))
                                _name = _hm.group(2).strip().rstrip('*').strip()
                                if _name not in _SECTION_WORDS and len(_name) > 1 and 1 <= _num <= len(batch):
                                    _item_idx = _num - 1
                                    if _item_idx not in _pending_items and _item_idx not in emitted_indices:
                                        _pending_items.add(_item_idx)
                                        emitted_indices.add(_item_idx)
                                        _pending_item = {"item": batch[_item_idx], "is_bo": None, "confidence": "pending", "reason": "", "rules_check": []}
                                        all_results[batch[_item_idx]] = _pending_item
                                        yield {"type": "item_pending", "index": i + _item_idx, "item": batch[_item_idx], "batch_index": batch_idx}
                        _item_scan_pos = _new_end

                    # 实时检测已完成的结论，立即发射结果
                    # 优化：只在有新完整行时才重新解析，避免O(n²)重解析
                    last_nl = full_response.rfind('\n')
                    if last_nl > _last_parse_len:
                        _last_parse_len = last_nl
                        conclusions = _parse_streaming_conclusions(full_response, batch)
                        for c in conclusions:
                            if c['conclusion'] and c['idx'] in emitted_indices:
                                con = c['conclusion']
                                item_name = batch[c['idx']]
                                # 更新 all_results 中已有的 pending 记录（O(1)查找）
                                ar = all_results.get(item_name)
                                if ar and ar.get('confidence') == 'pending':
                                    ar['is_bo'] = con['is_bo']
                                    ar['confidence'] = con['confidence']
                                    ar['reason'] = con['reason']
                                yield {"type": "result_update", "index": i + c['idx'],
                                       "item": item_name, "is_bo": con['is_bo'],
                                       "confidence": con['confidence'], "reason": con['reason'],
                                       "rules_check": []}

            yield {"type": "thinking_end", "batch_index": batch_idx}

            # 解析完整JSON响应，补充rules_check详情
            parsed = parse_llm_response(full_response, batch)

            for j, result in enumerate(parsed):
                item_name = result.get("item", batch[j])
                full_result = {
                    "item": item_name,
                    "is_bo": result.get("is_bo"),
                    "confidence": result.get("confidence", "low"),
                    "reason": result.get("reason", ""),
                    "rules_check": result.get("rules_check", []),
                }
                if j in emitted_indices:
                    # 已通过思考发射过
                    # 关键：如果JSON解析失败(is_bo=None)，保留流式解析的结论
                    if full_result['is_bo'] is None:
                        ar = all_results.get(item_name)
                        if ar and ar.get('is_bo') is not None:
                            # 流式解析已有结论，只更新rules_check
                            if full_result.get('rules_check'):
                                ar['rules_check'] = full_result['rules_check']
                        elif ar:
                            # 流式也没有，发送更新
                            ar.update(full_result)
                            yield {"type": "result_update", "index": i + j, **full_result}
                        else:
                            all_results[item_name] = full_result
                            yield {"type": "result_update", "index": i + j, **full_result}
                    else:
                        # JSON有有效结论，发送更新
                        ar = all_results.get(item_name)
                        if ar:
                            ar.update(full_result)
                        else:
                            all_results[item_name] = full_result
                        yield {"type": "result_update", "index": i + j, **full_result}
                else:
                    # 未发射过，正常发射
                    all_results[item_name] = full_result
                    yield {"type": "result", "index": i + j, **full_result}

        except Exception as e:
            for j, item in enumerate(batch):
                if j not in emitted_indices:
                    result = {"item": item, "is_bo": None, "confidence": "low", "reason": f"AI分析出错: {str(e)}", "rules_check": []}
                    all_results[item] = result
                    yield {"type": "result", "index": i + j, **result}

        yield {"type": "progress", "current": min(i + len(batch), total), "total": total}

    results_list = list(all_results.values())
    bo_count = sum(1 for r in results_list if r.get("is_bo") is True)
    not_bo_count = sum(1 for r in results_list if r.get("is_bo") is False)
    unknown_count = sum(1 for r in results_list if r.get("is_bo") is None)

    yield {
        "type": "done",
        "summary": {"is_bo": bo_count, "not_bo": not_bo_count, "unknown": unknown_count, "total": total}
    }

# ============================================================
# 4. JSON解析
# ============================================================

def _extract_json_object(text: str, start_pos: int) -> str | None:
    """从start_pos位置开始，通过花括号计数提取完整的JSON对象字符串"""
    pos = start_pos
    while pos < len(text) and text[pos] != '{':
        pos += 1
    if pos >= len(text):
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(pos, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\' and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if not in_string:
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return text[pos:i + 1]
    return None


def parse_llm_response(response: str, items: list[str]) -> list[dict]:
    """解析 LLM 返回的结果，从混合文本中提取JSON"""
    default_results = [{"item": item, "is_bo": None, "confidence": "low", "reason": "无法自动解析，请人工判断"} for item in items]

    def _try_parse(json_str: str) -> list[dict] | None:
        try:
            data = json.loads(json_str)
            results = data.get("results", [])
            if len(results) == len(items):
                return results
            elif len(results) > 0:
                result_map = {r.get("item", ""): r for r in results}
                return [
                    result_map.get(item, {"item": item, "is_bo": None, "confidence": "low", "reason": "未返回该项结果"})
                    for item in items
                ]
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    # 方案1：从 ```json 代码块中提取
    json_block = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', response)
    if json_block:
        parsed = _try_parse(json_block.group(1))
        if parsed is not None:
            return parsed

    # 方案2：找到 "results" 关键字，向前找 { 向后用花括号计数提取完整JSON对象
    for m in re.finditer(r'"results"', response):
        # 向前找最近的 {
        search_start = max(0, m.start() - 5000)
        prefix = response[search_start:m.start()]
        brace_pos = prefix.rfind('{')
        if brace_pos >= 0:
            json_str = _extract_json_object(response, search_start + brace_pos)
            if json_str:
                parsed = _try_parse(json_str)
                if parsed is not None:
                    return parsed

    # 方案3：找最后一个 { 并提取（可能是JSON开头）
    last_brace = response.rfind('{')
    if last_brace >= 0:
        # 尝试从每个 { 位置提取，取第一个成功的
        for m in re.finditer(r'\{', response):
            json_str = _extract_json_object(response, m.start())
            if json_str:
                parsed = _try_parse(json_str)
                if parsed is not None:
                    return parsed

    return default_results


def check_single_item(item: str, element_type: str = "业务对象") -> list[dict]:
    """构建单个事物详细判断的消息列表"""
    prompt = build_check_prompt(element_type)
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"请判断「{item}」是否是{element_type}？"}
    ]
