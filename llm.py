"""
LLM 客户端封装 - 支持多模型切换
支持: 火山引擎方舟(豆包/DeepSeek) / OpenAI兼容接口(通义千问)
"""
import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

# 模型配置列表
MODELS = [
    {
        "id": "doubao-turbo",
        "name": "豆包 Turbo (快速)",
        "provider": "ark",
        "model": os.getenv("DOUBAO_TURBO_MODEL", "Doubao-Seed-2.1-turbo"),
        "base_url": os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        "api_key": os.getenv("DOUBAO_API_KEY", ""),
    },
    {
        "id": "doubao",
        "name": "豆包 Evolving (推理)",
        "provider": "ark",
        "model": os.getenv("DOUBAO_MODEL", "doubao-seed-evolving"),
        "base_url": os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        "api_key": os.getenv("DOUBAO_API_KEY", ""),
    },
    {
        "id": "deepseek-flash",
        "name": "DeepSeek V4 Flash (快速)",
        "provider": "ark",
        "model": os.getenv("DEEPSEEK_FLASH_MODEL", "deepseek-v4-flash-260425"),
        "base_url": os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        "api_key": os.getenv("DOUBAO_API_KEY", ""),
    },
    {
        "id": "deepseek-pro",
        "name": "DeepSeek V4 Pro",
        "provider": "ark",
        "model": os.getenv("DEEPSEEK_PRO_MODEL", "deepseek-v4-pro-260425"),
        "base_url": os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        "api_key": os.getenv("DOUBAO_API_KEY", ""),
    },
    {
        "id": "qwen",
        "name": "通义千问 (Qwen)",
        "provider": "openai",
        "model": os.getenv("QWEN_MODEL", "qwen-plus-latest"),
        "base_url": os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "api_key": os.getenv("QWEN_API_KEY", ""),
    },
]

# 视觉模型配置（用于图片识别提取术语）
VISION_MODELS = [
    {
        "id": "qwen-vl",
        "name": "通义千问 VL",
        "provider": "openai",
        "model": os.getenv("VISION_QWEN_MODEL", "qwen-vl-max"),
        "base_url": os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "api_key": os.getenv("QWEN_API_KEY", ""),
    },
    {
        "id": "doubao-vision",
        "name": "豆包 Vision",
        "provider": "ark",
        "model": os.getenv("VISION_DOUBAO_MODEL", "doubao-1-5-vision-pro/250328"),
        "base_url": os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        "api_key": os.getenv("DOUBAO_API_KEY", ""),
    },
]
_default_vision_model_id = os.getenv("DEFAULT_VISION_MODEL", "qwen-vl")

# 缓存客户端
_clients = {}
_default_model_id = os.getenv("DEFAULT_MODEL", "doubao-turbo")


def get_available_models() -> list[dict]:
    """返回可用的模型列表（仅含已配置API Key的）"""
    available = []
    for m in MODELS:
        if m["api_key"]:
            available.append({
                "id": m["id"],
                "name": m["name"],
                "model": m["model"],
            })
    # 如果没有配置任何key，返回全部（开发环境可能用.env）
    if not available:
        return [{"id": m["id"], "name": m["name"], "model": m["model"]} for m in MODELS]
    return available


def get_default_model_id() -> str:
    return _default_model_id


def get_vision_models() -> list[dict]:
    """返回可用的视觉模型列表"""
    available = []
    for m in VISION_MODELS:
        if m["api_key"]:
            available.append({"id": m["id"], "name": m["name"]})
    if not available:
        available = [{"id": m["id"], "name": m["name"]} for m in VISION_MODELS]
    return available


def get_default_vision_model_id() -> str:
    return _default_vision_model_id


def _get_vision_config(model_id: str = None) -> dict:
    """获取视觉模型配置"""
    mid = model_id or _default_vision_model_id
    for m in VISION_MODELS:
        if m["id"] == mid:
            return m
    return VISION_MODELS[0]


def _get_vision_client(model_id: str = None):
    """获取视觉模型客户端"""
    mid = model_id or _default_vision_model_id
    cache_key = f"vision_{mid}"
    if cache_key not in _clients:
        cfg = _get_vision_config(mid)
        if cfg["provider"] == "ark":
            try:
                from volcenginesdkarkruntime import Ark
                _clients[cache_key] = Ark(api_key=cfg["api_key"], base_url=cfg["base_url"])
            except (ImportError, AttributeError):
                from openai import OpenAI
                _clients[cache_key] = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
        else:
            from openai import OpenAI
            _clients[cache_key] = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    return _clients[cache_key]


def analyze_image(image_base64: str, prompt: str, model_id: str = None, temperature: float = 0.2) -> str:
    """
    调用视觉模型分析图片，返回文本结果。
    image_base64: 图片的 base64 编码（不含 data:image 前缀）
    """
    cfg = _get_vision_config(model_id)
    client = _get_vision_client(model_id)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                {"type": "text", "text": prompt},
            ],
        }
    ]
    try:
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=messages,
            temperature=temperature,
            max_tokens=4096,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        _clients.pop(f"vision_{model_id or _default_vision_model_id}", None)
        raise RuntimeError(f"视觉模型调用失败 ({cfg['name']}): {e}")


def get_model_display_name(model_id: str = None) -> str:
    """获取模型的显示名称"""
    mid = model_id or _default_model_id
    cfg = _get_model_config(mid)
    return cfg.get("name", mid)


def _get_model_config(model_id: str) -> dict:
    """根据model_id获取模型配置"""
    for m in MODELS:
        if m["id"] == model_id:
            return m
    # 默认第一个
    return MODELS[0]


def _get_client(model_id: str):
    """获取或创建对应模型的客户端"""
    if model_id not in _clients:
        cfg = _get_model_config(model_id)
        import httpx
        connect_timeout = int(os.getenv("LLM_CONNECT_TIMEOUT", "30"))
        http_client = httpx.Client(
            timeout=httpx.Timeout(connect=connect_timeout, read=300, write=30, pool=30),
            follow_redirects=True,
        )
        if cfg["provider"] == "ark":
            try:
                from volcenginesdkarkruntime import Ark
                _clients[model_id] = Ark(
                    api_key=cfg["api_key"],
                    base_url=cfg["base_url"],
                    http_client=http_client,
                )
            except (ImportError, AttributeError, TypeError):
                # 回退到 openai SDK（同样兼容 Ark API）
                from openai import OpenAI
                _clients[model_id] = OpenAI(
                    api_key=cfg["api_key"],
                    base_url=cfg["base_url"],
                    http_client=http_client,
                )
        else:
            from openai import OpenAI
            _clients[model_id] = OpenAI(
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
                http_client=http_client,
            )
    return _clients[model_id]


def chat(messages: list[dict], temperature: float = 0.3, model_id: str = None, timeout: int = 120) -> str:
    """同步调用 LLM，返回完整文本。超时默认120秒"""
    mid = model_id or _default_model_id
    cfg = _get_model_config(mid)
    client = _get_client(mid)
    try:
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=messages,
            temperature=temperature,
            timeout=timeout,
        )
        return response.choices[0].message.content
    except Exception as e:
        # 超时重试一次
        if 'timeout' in str(e).lower():
            response = client.chat.completions.create(
                model=cfg["model"],
                messages=messages,
                temperature=temperature,
                timeout=timeout * 2,
            )
            return response.choices[0].message.content
        raise


def chat_stream(messages: list[dict], temperature: float = 0.3, model_id: str = None, max_retries: int = 2):
    """流式调用 LLM，逐步 yield 文本片段。支持自动重试（含网络错误）"""
    import time
    mid = model_id or _default_model_id
    cfg = _get_model_config(mid)
    last_error = None
    # 从环境变量读取超时（秒），默认300秒（大文档生成需要较长时间）
    req_timeout = int(os.getenv("LLM_TIMEOUT", "300"))

    for attempt in range(max_retries + 1):
        client = _get_client(mid)
        try:
            stream = client.chat.completions.create(
                model=cfg["model"],
                messages=messages,
                temperature=temperature,
                stream=True,
                timeout=req_timeout,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
            return  # 成功完成，直接返回
        except Exception as e:
            last_error = e
            # 清除缓存客户端，下次重新创建
            _clients.pop(mid, None)
            if attempt < max_retries:
                time.sleep(2 * (attempt + 1))  # 递增等待: 2s, 4s
                continue  # 重试
            # 生成更友好的错误信息
            err_str = str(last_error).lower()
            if 'network' in err_str or 'connect' in err_str or 'resolve' in err_str:
                hint = (f"网络连接失败，无法访问 {cfg.get('base_url', 'API')}。"
                        f"可能原因：服务器所在地区无法直连国内API、DNS解析失败、或API Key未配置。"
                        f"原始错误: {last_error}")
            elif 'timeout' in err_str:
                hint = f"请求超时（{req_timeout}秒），文档可能过大或模型响应慢。原始错误: {last_error}"
            elif 'auth' in err_str or '401' in err_str or 'key' in err_str:
                hint = f"API Key 认证失败，请检查环境变量配置。原始错误: {last_error}"
            else:
                hint = f"LLM调用失败 ({cfg['name']}): {last_error}"
            raise RuntimeError(hint)
