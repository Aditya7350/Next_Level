from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.api_route("/health", methods=["GET", "HEAD"], summary="Liveness probe")
def health() -> dict[str, str]:
    return {"status": "ok"}
