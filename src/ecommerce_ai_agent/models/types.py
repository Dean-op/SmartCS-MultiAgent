from enum import Enum

from sqlalchemy import Enum as SqlEnum


def enum_values(enum_type: type[Enum]) -> list[str]:
    return [member.value for member in enum_type]


def database_enum(enum_type: type[Enum], name: str) -> SqlEnum:
    return SqlEnum(enum_type, name=name, native_enum=True, values_callable=enum_values)
