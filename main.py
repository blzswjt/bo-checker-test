"""
FastAPI 主入口 - 数据建模识别智能体 v1.0
支持：主题域分类、主题域分组、主题域、业务对象、逻辑实体、业务属性
"""
import os
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional

from llm import chat_stream, get_available_models, get_default_model_id, analyze_image, get_vision_models, get_default_vision_model_id
from rules import ELEMENT_TYPES, ELEMENT_RULES, get_all_rules_text, get_rule_detail, get_rules_config, update_rules_config, reset_rules_config, list_rule_versions, create_rule_version, delete_rule_version, rename_rule_version, switch_rule_version, get_version_rules
from checker import parse_excel_file, extract_column_values, extract_item_context, check_items_stream, check_single_item
from generator import parse_docx, extract_docx_images, analyze_images, run_generation_pipeline
import kb

app = FastAPI(title="数据建模识别智能体", version="1.0.0", description="多元素并发识别 · 流式思考 · 手动纠正 · 知识库学习")

# CORS 支持（同源部署无需开放全部来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ORIGIN", "http://localhost:8005")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# 上传文件保留天数，超过自动清理
UPLOAD_MAX_AGE_DAYS = int(os.getenv("UPLOAD_MAX_AGE_DAYS", 3))


def _cleanup_old_uploads():
    """清理过期的上传文件"""
    import time
    now = time.time()
    cutoff = now - UPLOAD_MAX_AGE_DAYS * 86400
    for f in UPLOAD_DIR.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
            except OSError:
                pass


@app.on_event("startup")
async def on_startup():
    _cleanup_old_uploads()


# ============================================================
# 全局异常处理
# ============================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """统一异常处理，返回友好的错误信息"""
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"error": f"服务器内部错误: {str(exc)}"}
    )


# ============================================================
# 基础路由
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = static_dir / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>页面未找到</h1>")


@app.get("/generator", response_class=HTMLResponse)
async def generator_page():
    html_path = static_dir / "generator.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>页面未找到</h1>")


# ============================================================
# API: 模型与元素类型
# ============================================================

@app.get("/api/models")
async def get_models():
    """返回可用模型列表"""
    return {"models": get_available_models(), "default": get_default_model_id()}


@app.get("/api/vision-models")
async def get_vision_models_api():
    """返回可用的视觉模型列表"""
    return {"models": get_vision_models(), "default": get_default_vision_model_id()}


@app.get("/api/element-types")
async def get_element_types():
    """返回元素类型列表及每种类型的识别规则名"""
    rule_names = {}
    for etype, rules in ELEMENT_RULES.items():
        rule_names[etype] = {
            "identification": [r["rule"] for r in rules.get("identification", []) if r.get("enabled", True) is not False],
            "naming": [r["rule"] for r in rules.get("naming", []) if r.get("enabled", True) is not False],
            "definition": [r["rule"] for r in rules.get("definition", []) if r.get("enabled", True) is not False],
        }
    return {"types": ELEMENT_TYPES, "rule_names": rule_names}


@app.get("/api/rules")
async def get_rules():
    """返回所有元素类型的规则文本"""
    return {"rules": get_all_rules_text()}


@app.get("/api/rules-config")
async def get_rules_config_api():
    """返回当前版本的完整规则配置"""
    return get_rules_config()


@app.put("/api/rules-config")
async def save_rules_config_api(config: dict):
    """保存规则配置到当前版本"""
    update_rules_config(config)
    return {"ok": True}


@app.post("/api/rules-config/reset")
async def reset_rules_config_api():
    """重置当前版本规则配置为默认值"""
    reset_rules_config()
    return {"ok": True, "config": get_rules_config()}


# ---- 规则版本管理 ----

@app.get("/api/rule-versions")
async def list_rule_versions_api():
    """返回所有规则版本列表"""
    return {"versions": list_rule_versions()}


class VersionCreateRequest(BaseModel):
    name: str
    copy_from: str = None

@app.post("/api/rule-versions")
async def create_rule_version_api(req: VersionCreateRequest):
    """创建新版本"""
    ok = create_rule_version(req.name, req.copy_from)
    if not ok:
        return JSONResponse({"error": "版本名已存在或为空"}, status_code=400)
    return {"ok": True, "versions": list_rule_versions()}


@app.delete("/api/rule-versions/{name}")
async def delete_rule_version_api(name: str):
    """删除指定版本"""
    ok = delete_rule_version(name)
    if not ok:
        return JSONResponse({"error": "无法删除默认版本或版本不存在"}, status_code=400)
    return {"ok": True, "versions": list_rule_versions()}


class VersionRenameRequest(BaseModel):
    new_name: str

@app.put("/api/rule-versions/{name}/rename")
async def rename_rule_version_api(name: str, req: VersionRenameRequest):
    """重命名版本"""
    ok = rename_rule_version(name, req.new_name)
    if not ok:
        return JSONResponse({"error": "重命名失败"}, status_code=400)
    return {"ok": True, "versions": list_rule_versions()}


@app.post("/api/rule-versions/{name}/switch")
async def switch_rule_version_api(name: str):
    """切换到指定版本"""
    ok = switch_rule_version(name)
    if not ok:
        return JSONResponse({"error": "版本不存在"}, status_code=400)
    return {"ok": True, "config": get_rules_config()}


@app.get("/api/rule-versions/{name}/rules")
async def get_version_rules_api(name: str):
    """获取指定版本的规则配置"""
    rules = get_version_rules(name)
    if not rules:
        return JSONResponse({"error": "版本不存在"}, status_code=404)
    return rules


# ============================================================
# API: 图片识别提取术语
# ============================================================

@app.post("/api/recognize-image")
async def recognize_image(file: UploadFile = File(...), vision_model: str = None):
    """
    上传图片，调用视觉模型提取图片中的数据建模术语。
    返回结构化列表：[{name, suggested_type}, ...]
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        return JSONResponse({"error": "请上传图片文件（jpg/png/webp）"}, status_code=400)

    import base64
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:  # 20MB limit
        return JSONResponse({"error": "图片大小不能超过 20MB"}, status_code=400)

    image_b64 = base64.b64encode(content).decode("utf-8")

    prompt = """请仔细分析这张图片，提取其中所有可能属于数据建模范畴的术语/名词。

包括但不限于：
- 业务对象（如：采购订单、客户、供应商、合同、产品等）
- 逻辑实体（如：用户信息、地址信息、订单明细等）
- 业务属性（如：姓名、编号、日期、金额、状态等）
- 主题域/主题域分组（如：采购管理、财务管理、供应链等）

请以严格的JSON数组格式返回，每个元素包含：
- name: 术语名称（字符串）
- suggested_type: 建议的元素类型（字符串，可选值：业务对象、逻辑实体、业务属性、主题域、主题域分组、主题域分类）
- confidence: 你对该术语提取的信心程度（high/medium/low）

只返回JSON数组，不要返回其他任何文字。示例：
[{"name":"采购订单","suggested_type":"业务对象","confidence":"high"},{"name":"订单编号","suggested_type":"业务属性","confidence":"high"}]"""

    try:
        result_text = analyze_image(image_b64, prompt, model_id=vision_model)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    # 解析 JSON 结果
    import re
    items = []
    try:
        # 尝试从结果中提取 JSON 数组
        json_match = re.search(r'\[.*\]', result_text, re.DOTALL)
        if json_match:
            items = json.loads(json_match.group())
            # 校验格式
            for item in items:
                if "name" not in item:
                    items = [i for i in items if "name" in i]
    except (json.JSONDecodeError, ValueError):
        # 如果解析失败，返回原始文本让用户手动提取
        return {"items": [], "raw_text": result_text, "error": "AI返回格式异常，请查看原始文本"}

    return {"items": items, "raw_text": result_text, "total": len(items)}


# ============================================================
# API: Excel解析与流式识别
# ============================================================

@app.post("/api/parse-excel")
async def parse_excel(file: UploadFile = File(...)):
    """上传并解析Excel，返回所有子表和列信息（不执行识别）"""
    if not file.filename.endswith((".xlsx", ".xls")):
        return JSONResponse({"error": "请上传 .xlsx 或 .xls 格式文件"}, status_code=400)

    file_id = str(uuid.uuid4())[:8]
    save_name = f"{file_id}_{file.filename}"
    save_path = UPLOAD_DIR / save_name
    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    result = parse_excel_file(str(save_path))
    if "error" in result:
        return JSONResponse(result, status_code=400)

    result["file_id"] = file_id
    result["file_name"] = file.filename
    result["file_path"] = save_name
    return result


class CheckRequest(BaseModel):
    items: list[str]
    element_type: str = "业务对象"
    batch_size: int = 5
    model_id: Optional[str] = None
    context_map: Optional[dict] = None  # {item_name: {l1, l2, l3, definition}} 业务上下文
    analysis_context: Optional[str] = None  # AI 预分析结果，作为识别参考


@app.post("/api/check-items")
async def check_items(req: CheckRequest):
    """SSE流式逐批识别，实时推送进度和结果"""
    if req.element_type not in ELEMENT_TYPES:
        return JSONResponse({"error": f"不支持的元素类型: {req.element_type}"}, status_code=400)

    def event_stream():
        for event in check_items_stream(req.items, req.element_type, req.batch_size, model_id=req.model_id, context_map=req.context_map, analysis_context=req.analysis_context):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class SingleCheckRequest(BaseModel):
    item: str
    element_type: str = "业务对象"
    model_id: Optional[str] = None


@app.post("/api/check-single")
async def check_single(req: SingleCheckRequest):
    """流式判断单个事物"""
    if req.element_type not in ELEMENT_TYPES:
        return JSONResponse({"error": f"不支持的元素类型: {req.element_type}"}, status_code=400)

    messages = check_single_item(req.item, element_type=req.element_type)

    def generate():
        for chunk in chat_stream(messages, temperature=0.2, model_id=req.model_id):
            yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/column-values")
async def get_column_values(file_path: str, sheet: str, column: str):
    """获取指定文件中指定子表指定列的所有非空唯一值"""
    full_path = UPLOAD_DIR / file_path
    if not full_path.exists():
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    values = extract_column_values(str(full_path), sheet, column)
    return {"values": values, "count": len(values)}


@app.get("/api/excel-context")
async def get_excel_context(file_path: str, sheet: str, column: str, context_columns: str = None):
    """获取指定列中每个条目的业务上下文，用于增强AI识别。
    context_columns: 逗号分隔的上下文列名（可选，不传则自动检测L1/L2/L3）"""
    full_path = UPLOAD_DIR / file_path
    if not full_path.exists():
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    cols = [c.strip() for c in context_columns.split(',') if c.strip()] if context_columns else None
    context = extract_item_context(str(full_path), sheet, column, context_columns=cols)
    return {"context": context, "count": len(context)}


# ============================================================
# AI 数据分析（预分析对话）
# ============================================================

class AnalyzeRequest(BaseModel):
    file_path: str
    sheet: str
    prompt: str
    model_id: Optional[str] = None


@app.post("/api/analyze-data")
async def analyze_data(req: AnalyzeRequest):
    """SSE流式分析Excel数据，基于用户自定义指令"""
    full_path = UPLOAD_DIR / req.file_path
    if not full_path.exists():
        return JSONResponse({"error": "文件不存在"}, status_code=404)

    # 获取子表的完整结构信息
    parsed = parse_excel_file(str(full_path))
    if "error" in parsed:
        return JSONResponse({"error": parsed["error"]}, status_code=400)

    # 找到目标子表
    sheet_info = None
    for s in parsed.get("sheets", []):
        if s["name"] == req.sheet:
            sheet_info = s
            break
    if not sheet_info:
        return JSONResponse({"error": f"子表 '{req.sheet}' 不存在"}, status_code=404)

    # 获取子表所有列的样本数据摘要
    from checker import extract_column_values as _ecv
    columns_summary = []
    for col in sheet_info.get("columns", []):
        col_name = col["name"]
        # 获取前20个样本值
        try:
            vals = _ecv(str(full_path), req.sheet, col_name)
            sample = vals[:20]
            total = len(vals)
        except Exception:
            sample = col.get("sample", [])
            total = col.get("unique_count", 0)
        columns_summary.append({
            "name": col_name,
            "rows": col.get("rows", 0),
            "unique_count": total,
            "samples": sample,
        })

    # 构建分析上下文
    data_context = f"""## 数据表信息
- 子表名称：{req.sheet}
- 总行数：{sheet_info.get('rows', '?')}
- 总列数：{len(columns_summary)}

### 所有字段详情：
"""
    for i, c in enumerate(columns_summary, 1):
        data_context += f"{i}. **{c['name']}**（{c['rows']}行, {c['unique_count']}个唯一值）\n"
        if c['samples']:
            sample_text = ", ".join(str(s) for s in c['samples'][:15])
            if len(c['samples']) > 15:
                sample_text += f"...（共{len(c['samples'])}个）"
            data_context += f"   样本值: {sample_text}\n"

    system_prompt = """你是一位资深数据治理和数据架构专家，擅长企业数据建模、数据资产管理。请根据提供的数据表结构信息，按照用户的指令进行专业分析。

分析要求：
1. 结合字段名（中英文）推断业务含义
2. 通过样本值分析数据特征和用途范围
3. 给出结构化的、可操作的分析结论
4. 如果涉及数据质量，给出具体的判断依据"""

    user_prompt = f"""{data_context}

---

## 用户分析指令
{req.prompt}"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    def event_stream():
        for chunk in chat_stream(messages, temperature=0.3, model_id=req.model_id):
            yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ============================================================
# 知识库管理
# ============================================================

class CorrectionRequest(BaseModel):
    item: str
    element_type: str
    original_result: Optional[bool] = None
    corrected_result: bool
    reason: str = ""


@app.post("/api/correct")
async def submit_correction(req: CorrectionRequest):
    """提交纠正并加入知识库"""
    kb.add_correction(req.item, req.element_type, req.original_result, req.corrected_result, req.reason)
    return {"ok": True}


class ExampleRequest(BaseModel):
    element_type: str
    item: str
    is_match: bool
    reason: str = ""


@app.post("/api/kb/add-example")
async def add_kb_example(req: ExampleRequest):
    """添加知识库示例"""
    kb.add_example(req.element_type, req.item, req.is_match, req.reason)
    return {"ok": True}


@app.delete("/api/kb/remove-example")
async def remove_kb_example(element_type: str, item: str):
    """删除知识库示例"""
    kb.remove_example(element_type, item)
    return {"ok": True}


@app.get("/api/kb")
async def get_knowledge_base():
    """获取完整知识库"""
    return kb.get_all()


@app.put("/api/kb")
async def update_knowledge_base(data: dict):
    """整体更新知识库"""
    kb.update_all(data)
    return {"ok": True}


# ============================================================
# 答疑智能体
# ============================================================

class QAChatRequest(BaseModel):
    item: str
    element_type: str
    rule: str
    pass_status: bool
    reason: str = ""
    question: str
    history: list[dict] = []  # [{role:'user',content:'...'}, {role:'assistant',content:'...'}]
    model_id: Optional[str] = None


@app.post("/api/qa-chat")
async def qa_chat(req: QAChatRequest):
    """答疑智能体：解释规则判断原因，支持多轮对话"""
    rule_detail = get_rule_detail(req.element_type, req.rule)
    pass_text = "通过（✓）" if req.pass_status else "不通过（✗）"

    system_prompt = (
        f"你是数据建模答疑专家。用户正在分析「{req.item}」是否为{req.element_type}。\n"
        f"\n{rule_detail}\n"
        f"\nAI分析结论：该规则{pass_text}\n"
        f"分析理由：{req.reason or '无详细理由'}\n\n"
        "请根据以上信息回答用户的疑问。如果用户不理解为什么通过或不通过，请详细解释。"
        "回答要简洁明了，用通俗易懂的语言。"
    )

    messages = [{"role": "system", "content": system_prompt}]
    for h in req.history[-10:]:  # 最多保留最近10条历史
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": req.question})

    def generate():
        for chunk in chat_stream(messages, temperature=0.3, model_id=req.model_id):
            yield f"data: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


class QASaveRequest(BaseModel):
    item: str
    element_type: str
    rule: str
    pass_status: bool
    question: str
    answer: str


@app.post("/api/qa-save")
async def qa_save(req: QASaveRequest):
    """将答疑内容存入知识库"""
    reason = f"答疑：{req.question} → {req.answer[:200]}"
    kb.add_example(req.element_type, req.item, req.pass_status, reason)
    return {"ok": True}


# ============================================================
# 数据建模生成智能体
# ============================================================

class GenRequest(BaseModel):
    file_path: str
    model_id: Optional[str] = None
    vision_model_id: Optional[str] = None
    analyze_images: bool = True


@app.post("/api/gen/parse-docx")
async def gen_parse_docx(file: UploadFile = File(...)):
    """上传并解析docx文档，返回文档结构概览"""
    if not file.filename.endswith(".docx"):
        return JSONResponse({"error": "请上传 .docx 格式文件"}, status_code=400)

    file_id = str(uuid.uuid4())[:8]
    save_name = f"{file_id}_{file.filename}"
    save_path = UPLOAD_DIR / save_name
    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    result = parse_docx(str(save_path))
    if "error" in result:
        return JSONResponse(result, status_code=400)

    # 不返回full_text给前端（太大），只返回结构信息
    result.pop("full_text", None)
    result["file_id"] = file_id
    result["file_name"] = file.filename
    result["file_path"] = save_name
    return result


@app.post("/api/gen/generate")
async def gen_generate(req: GenRequest):
    """SSE流式执行完整生成流程（带心跳保活，防止代理超时）"""
    import queue
    import threading

    full_path = UPLOAD_DIR / req.file_path
    if not full_path.exists():
        return JSONResponse({"error": "文件不存在，请先上传文档"}, status_code=404)

    def event_stream():
        q = queue.Queue()
        _SENTINEL = object()

        def _run_pipeline():
            try:
                for event in run_generation_pipeline(
                    str(full_path),
                    model_id=req.model_id,
                    vision_model_id=req.vision_model_id,
                    analyze_img=req.analyze_images
                ):
                    q.put(event)
            except Exception as e:
                q.put({"type": "error", "message": f"生成失败: {str(e)}"})
            finally:
                q.put(_SENTINEL)

        t = threading.Thread(target=_run_pipeline, daemon=True)
        t.start()

        while True:
            try:
                event = q.get(timeout=15)  # 每15秒超时一次
                if event is _SENTINEL:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except queue.Empty:
                # 发送心跳保活，防止代理超时断开连接
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁止Nginx缓冲
            "Connection": "keep-alive",
        }
    )


@app.get("/api/gen/download/{filename}")
async def gen_download(filename: str):
    """下载生成的Excel文件"""
    from fastapi.responses import FileResponse
    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    # 提取友好的文件名
    download_name = filename.replace("gen_", "").split("_", 1)[-1] if "_" in filename else filename
    return FileResponse(
        path=str(file_path),
        filename=download_name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.post("/api/gen/analyze-image")
async def gen_analyze_image(file: UploadFile = File(...), vision_model: str = None):
    """单独分析一张图片（调试用）"""
    if not file.content_type or not file.content_type.startswith("image/"):
        return JSONResponse({"error": "请上传图片文件"}, status_code=400)

    import base64 as b64
    content = await file.read()
    image_b64 = b64.b64encode(content).decode("utf-8")

    prompt = """请分析这张图片，提取其中的数据建模相关信息：
- 业务对象名称和关系
- 逻辑实体和属性
- 层级结构（L1-L4）
- 实体间关系
请以结构化文本输出。"""

    try:
        result = analyze_image(image_b64, prompt, model_id=vision_model)
        return {"analysis": result}
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    import uvicorn
    import sys
    print("=" * 50)
    print(f"数据建模识别智能体 v1.0")
    print(f"Python: {sys.version}")
    print(f"工作目录: {os.getcwd()}")
    print(f"PORT: {os.getenv('PORT', '未设置')}")
    print(f"DOUBAO_API_KEY: {'已配置' if os.getenv('DOUBAO_API_KEY') else '未配置'}")
    print(f"QWEN_API_KEY: {'已配置' if os.getenv('QWEN_API_KEY') else '未配置'}")
    print(f"DEFAULT_MODEL: {os.getenv('DEFAULT_MODEL', 'doubao')}")
    # 检查关键依赖
    for pkg in ['volcenginesdkarkruntime', 'openai', 'fastapi', 'uvicorn', 'pandas', 'openpyxl']:
        try:
            __import__(pkg)
            print(f"  ✅ {pkg}")
        except ImportError:
            print(f"  ❌ {pkg} 未安装")
    print("=" * 50)
    port = int(os.getenv("PORT", 8005))
    print(f"启动服务: http://0.0.0.0:{port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port)
