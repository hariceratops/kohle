# kohle/services/debit_category.py
from dataclasses import dataclass
from typing import Tuple
from difflib import SequenceMatcher

from models import DebitCategory
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class CategoryAddResult:
    added: bool
    warnings: Tuple[str, ...]


def add_debit_category(session: Session, name: str) -> CategoryAddResult:
    name = name.strip()
    if not name:
        raise ValueError("Category name cannot be empty")

    existing = session.query(DebitCategory).all()

    for c in existing:
        if c.category.lower() == name.lower():
            return CategoryAddResult(added=False, warnings=())

    warnings = tuple(
        c.category
        for c in existing
        if SequenceMatcher(None, c.category.lower(), name.lower()).ratio() > 0.8
    )

    session.add(DebitCategory(category=name))
    session.commit()

    return CategoryAddResult(added=True, warnings=warnings)

