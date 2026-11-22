from .repositories import Repository


def audit(db, user, event, details=None):
    user_id = user.id if hasattr(user, "id") else user
    Repository(db, user_id).log(event, details)
