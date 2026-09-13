"""
隱私保護建議平台 - FastAPI 後端進入點。

啟動方式：
    uv run uvicorn main:app --reload --port 8000

啟動後可至 http://localhost:8000/docs 查看完整、可互動的 API 參數文件。
"""

from core.config import get_settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers.analyze import router as analyze_router

settings = get_settings()

app = FastAPI(
    title="隱私保護建議平台 API",
    description=(
        "提供：合成假資料生成、隱私保護技術判斷（mask/generalize/suppress/"
        "differential_privacy）、Excel 公式建議。所有請求/回應參數皆有中文說明，"
        "詳見各 Endpoint 的 Schema。"
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(analyze_router)
