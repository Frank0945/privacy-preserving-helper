from fastapi import APIRouter, Form

router = APIRouter(prefix="/company", tags=["company"])


@router.post("/register")
async def register_company(name: str = Form(...)):
    return {}


@router.get("/list")
async def get_all_companies():
    return {}
