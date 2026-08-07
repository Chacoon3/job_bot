from fastapi import APIRouter

router = APIRouter(prefix="/api/", tags=["job_bot"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}
