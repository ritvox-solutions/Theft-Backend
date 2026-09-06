from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.meter import Meter, MeterStatus


def get_meter_by_device_key(
    x_device_key: str = Header(...),
    db: Session = Depends(get_db),
) -> Meter:
    """Resolves the Meter a device is authenticating as, via its x-device-key header.

    Deliberately separate from get_current_user (Phase 1): devices never hold a
    user JWT, they hold a per-meter secret. Keep this trust boundary distinct.
    """
    meter = db.query(Meter).filter(Meter.device_key == x_device_key).first()
    if meter is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device key"
        )
    # An admin deactivating a meter (Phase 5) is meant to actually stop it from
    # reporting, not just hide it in the UI — a decommissioned/suspected-tampered
    # meter's key should stop working the moment it's deactivated.
    if meter.status == MeterStatus.inactive:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This meter is inactive and cannot submit readings",
        )
    return meter
