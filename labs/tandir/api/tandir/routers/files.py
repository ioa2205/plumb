from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter(tags=["files"])


@router.get("/avatars")
def get_avatar(name: str, request: Request) -> FileResponse:
    root = request.app.state.settings.avatar_dir.resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Avatar not found")
    return FileResponse(path)
