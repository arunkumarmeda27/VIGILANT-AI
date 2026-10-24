from enum import Enum

class UserRole(str, Enum):
    ADMIN = "ADMIN"
    REVIEWER = "REVIEWER"
    INSTITUTION_USER = "INSTITUTION_USER"
