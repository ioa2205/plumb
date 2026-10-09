from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Patient, Record
from app.schemas import RecordOut
from app.security import current_patient

router = APIRouter()


@router.get("/records/{record_id}")
def read_record(
    record_id: int,
    patient: Patient = Depends(current_patient),
    db: Session = Depends(get_db),
) -> RecordOut:
    record = db.get(Record, record_id)
    if record is None or record.patient_id != patient.id:
        raise HTTPException(status_code=404, detail="Record not found")
    return RecordOut.from_record(record)
