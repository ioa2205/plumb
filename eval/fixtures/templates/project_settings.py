from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Project, User
from app.schemas import ProjectSettingsIn, ProjectSettingsOut
from app.security import current_user

router = APIRouter()


@router.put("/projects/{project_id}/settings")
def update_project_settings(
    project_id: int,
    body: ProjectSettingsIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ProjectSettingsOut:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Project not found")
    project.visibility = body.visibility
    project.default_branch = body.default_branch
    db.commit()
    return ProjectSettingsOut.from_project(project)
