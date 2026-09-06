from app.models.meter import Meter
from app.models.user import User


def scope_to_owner(query, model, current_user: User):
    """Filters a query to the current user's own meters, unless they're an admin.

    `model` is the entity being queried. When it's Meter itself, filter directly
    on Meter.user_id; otherwise join to Meter via its meter_id FK and filter there.
    """
    if current_user.role.value == "admin":
        return query
    if model is Meter:
        return query.filter(Meter.user_id == current_user.id)
    return query.join(Meter, model.meter_id == Meter.id).filter(Meter.user_id == current_user.id)
