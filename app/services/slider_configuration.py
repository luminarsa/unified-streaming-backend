
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.platform_config import (
    SliderDefinition,
    SliderCuratedTitle,
    SliderKeyword,
    SliderCollection,
    SliderCompany,
    SliderNetwork,
    SliderExcludedTitle,
)


# ---------------------------------------------------------
# SHARED HELPERS
# ---------------------------------------------------------

def _commit(
    db: Session,
    message: str = "A record with these details already exists.",
):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=message)


def _require_slider(db: Session, slider_id: UUID):
    slider = db.get(SliderDefinition, slider_id)

    if slider is None:
        raise HTTPException(
            status_code=404,
            detail="Slider not found.",
        )

    return slider


def _require_record(db: Session, model, record_id: UUID, label: str):
    record = db.get(model, record_id)

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"{label} not found.",
        )

    return record


def _record_data(record) -> dict:
    """
    Convert a slider configuration SQLAlchemy model
    into a response dictionary.
    """

    data = {}

    for column in record.__table__.columns:
        value = getattr(record, column.name)

        if isinstance(value, UUID):
            value = str(value)

        elif hasattr(value, "isoformat"):
            value = value.isoformat()

        data[column.name] = value

    return data


def _create_record(
    db: Session,
    model,
    data,
    duplicate_message: str,
) -> dict:

    _require_slider(db, data.slider_id)

    record = model(**data.model_dump())

    db.add(record)

    _commit(db, duplicate_message)

    db.refresh(record)

    return _record_data(record)


def _create_slider_record(
    db: Session,
    model,
    slider_id: UUID,
    data,
    duplicate_message: str,
) -> dict:

    _require_slider(db, slider_id)

    record_data = data.model_dump()
    record_data["slider_id"] = slider_id

    record = model(**record_data)

    db.add(record)

    _commit(db, duplicate_message)

    db.refresh(record)

    return _record_data(record)


def _list_records(
    db: Session,
    model,
    slider_id: UUID,
    enabled_only: bool = False,
) -> list:

    _require_slider(db, slider_id)

    query = select(model).where(
        model.slider_id == slider_id
    )

    if enabled_only:
        query = query.where(model.enabled.is_(True))

    query = query.order_by(
        model.priority,
        model.created_at,
    )

    records = db.scalars(query).all()

    return [_record_data(record) for record in records]


def _get_record(
    db: Session,
    model,
    record_id: UUID,
    label: str,
) -> dict:

    record = _require_record(
        db,
        model,
        record_id,
        label,
    )

    return _record_data(record)


def _update_record(
    db: Session,
    model,
    record_id: UUID,
    data,
    label: str,
    duplicate_message: str,
) -> dict:

    record = _require_record(
        db,
        model,
        record_id,
        label,
    )

    changes = data.model_dump(exclude_unset=True)

    for field, value in changes.items():
        setattr(record, field, value)

    _commit(db, duplicate_message)

    db.refresh(record)

    return _record_data(record)


def _delete_record(
    db: Session,
    model,
    record_id: UUID,
    label: str,
) -> dict:

    record = _require_record(
        db,
        model,
        record_id,
        label,
    )

    db.delete(record)
    db.commit()

    return {
        "message": f"{label} deleted successfully.",
        "id": str(record_id),
    }


# ---------------------------------------------------------
# SLIDER CURATED TITLE SERVICES
# ---------------------------------------------------------

def create_curated_title(db: Session, data) -> dict:
    return _create_record(
        db,
        SliderCuratedTitle,
        data,
        "This curated title already exists on this slider.",
    )


def list_curated_titles(
    db: Session,
    slider_id: UUID,
    enabled_only: bool = False,
) -> list:
    return _list_records(
        db,
        SliderCuratedTitle,
        slider_id,
        enabled_only,
    )


def get_curated_title(db: Session, record_id: UUID) -> dict:
    return _get_record(
        db,
        SliderCuratedTitle,
        record_id,
        "Curated title",
    )


def update_curated_title(db: Session, record_id: UUID, data) -> dict:
    return _update_record(
        db,
        SliderCuratedTitle,
        record_id,
        data,
        "Curated title",
        "This curated title already exists on this slider.",
    )


def delete_curated_title(db: Session, record_id: UUID) -> dict:
    return _delete_record(
        db,
        SliderCuratedTitle,
        record_id,
        "Curated title",
    )


# ---------------------------------------------------------
# SLIDER KEYWORD SERVICES
# ---------------------------------------------------------

def create_slider_keyword(db: Session, data) -> dict:
    return _create_record(
        db,
        SliderKeyword,
        data,
        "This keyword already exists on this slider.",
    )


def list_slider_keywords(
    db: Session,
    slider_id: UUID,
    enabled_only: bool = False,
) -> list:
    return _list_records(
        db,
        SliderKeyword,
        slider_id,
        enabled_only,
    )


def get_slider_keyword(db: Session, record_id: UUID) -> dict:
    return _get_record(
        db,
        SliderKeyword,
        record_id,
        "Slider keyword",
    )


def update_slider_keyword(db: Session, record_id: UUID, data) -> dict:
    return _update_record(
        db,
        SliderKeyword,
        record_id,
        data,
        "Slider keyword",
        "This keyword already exists on this slider.",
    )


def delete_slider_keyword(db: Session, record_id: UUID) -> dict:
    return _delete_record(
        db,
        SliderKeyword,
        record_id,
        "Slider keyword",
    )


# ---------------------------------------------------------
# SLIDER COLLECTION SERVICES
# ---------------------------------------------------------

def create_slider_collection(db: Session, data) -> dict:
    return _create_record(
        db,
        SliderCollection,
        data,
        "This collection already exists on this slider.",
    )


def list_slider_collections(
    db: Session,
    slider_id: UUID,
    enabled_only: bool = False,
) -> list:
    return _list_records(
        db,
        SliderCollection,
        slider_id,
        enabled_only,
    )


def get_slider_collection(db: Session, record_id: UUID) -> dict:
    return _get_record(
        db,
        SliderCollection,
        record_id,
        "Slider collection",
    )


def update_slider_collection(db: Session, record_id: UUID, data) -> dict:
    return _update_record(
        db,
        SliderCollection,
        record_id,
        data,
        "Slider collection",
        "This collection already exists on this slider.",
    )


def delete_slider_collection(db: Session, record_id: UUID) -> dict:
    return _delete_record(
        db,
        SliderCollection,
        record_id,
        "Slider collection",
    )


# ---------------------------------------------------------
# SLIDER COMPANY SERVICES
# ---------------------------------------------------------

def create_slider_company(db: Session, data) -> dict:
    return _create_record(
        db,
        SliderCompany,
        data,
        "This company mapping already exists on this slider.",
    )


def list_slider_companies(
    db: Session,
    slider_id: UUID,
    enabled_only: bool = False,
) -> list:
    return _list_records(
        db,
        SliderCompany,
        slider_id,
        enabled_only,
    )


def get_slider_company(db: Session, record_id: UUID) -> dict:
    return _get_record(
        db,
        SliderCompany,
        record_id,
        "Slider company",
    )


def update_slider_company(db: Session, record_id: UUID, data) -> dict:
    return _update_record(
        db,
        SliderCompany,
        record_id,
        data,
        "Slider company",
        "This company mapping already exists on this slider.",
    )


def delete_slider_company(db: Session, record_id: UUID) -> dict:
    return _delete_record(
        db,
        SliderCompany,
        record_id,
        "Slider company",
    )


# ---------------------------------------------------------
# SLIDER NETWORK SERVICES
# ---------------------------------------------------------

def create_slider_network(db: Session, data) -> dict:
    return _create_record(
        db,
        SliderNetwork,
        data,
        "This network already exists on this slider.",
    )


def list_slider_networks(
    db: Session,
    slider_id: UUID,
    enabled_only: bool = False,
) -> list:
    return _list_records(
        db,
        SliderNetwork,
        slider_id,
        enabled_only,
    )


def get_slider_network(db: Session, record_id: UUID) -> dict:
    return _get_record(
        db,
        SliderNetwork,
        record_id,
        "Slider network",
    )


def update_slider_network(db: Session, record_id: UUID, data) -> dict:
    return _update_record(
        db,
        SliderNetwork,
        record_id,
        data,
        "Slider network",
        "This network already exists on this slider.",
    )


def delete_slider_network(db: Session, record_id: UUID) -> dict:
    return _delete_record(
        db,
        SliderNetwork,
        record_id,
        "Slider network",
    )


# ---------------------------------------------------------
# SLIDER EXCLUDED TITLE SERVICES
# ---------------------------------------------------------

def create_excluded_title(db: Session, data) -> dict:
    return _create_record(
        db,
        SliderExcludedTitle,
        data,
        "This excluded title already exists on this slider.",
    )


def list_excluded_titles(
    db: Session,
    slider_id: UUID,
    enabled_only: bool = False,
) -> list:
    return _list_records(
        db,
        SliderExcludedTitle,
        slider_id,
        enabled_only,
    )


def get_excluded_title(db: Session, record_id: UUID) -> dict:
    return _get_record(
        db,
        SliderExcludedTitle,
        record_id,
        "Excluded title",
    )


def update_excluded_title(db: Session, record_id: UUID, data) -> dict:
    return _update_record(
        db,
        SliderExcludedTitle,
        record_id,
        data,
        "Excluded title",
        "This excluded title already exists on this slider.",
    )


def delete_excluded_title(db: Session, record_id: UUID) -> dict:
    return _delete_record(
        db,
        SliderExcludedTitle,
        record_id,
        "Excluded title",
    )


# ---------------------------------------------------------
# API COMPATIBILITY FUNCTIONS
# ---------------------------------------------------------

# CURATED TITLES

def create_slider_curated_title(
    db: Session,
    slider_id: UUID,
    data,
) -> dict:
    return _create_slider_record(
        db,
        SliderCuratedTitle,
        slider_id,
        data,
        "This curated title already exists on this slider.",
    )


def list_slider_curated_titles(
    db: Session,
    slider_id: UUID,
    enabled_only: bool = False,
) -> list:
    return list_curated_titles(
        db,
        slider_id,
        enabled_only,
    )


def get_slider_curated_title(
    db: Session,
    record_id: UUID,
) -> dict:
    return get_curated_title(db, record_id)


def update_slider_curated_title(
    db: Session,
    record_id: UUID,
    data,
) -> dict:
    return update_curated_title(db, record_id, data)


def delete_slider_curated_title(
    db: Session,
    record_id: UUID,
) -> dict:
    return delete_curated_title(db, record_id)


# EXCLUDED TITLES

def create_slider_excluded_title(
    db: Session,
    slider_id: UUID,
    data,
) -> dict:
    return _create_slider_record(
        db,
        SliderExcludedTitle,
        slider_id,
        data,
        "This excluded title already exists on this slider.",
    )


def list_slider_excluded_titles(
    db: Session,
    slider_id: UUID,
    enabled_only: bool = False,
) -> list:
    return list_excluded_titles(
        db,
        slider_id,
        enabled_only,
    )


def get_slider_excluded_title(
    db: Session,
    record_id: UUID,
) -> dict:
    return get_excluded_title(db, record_id)


def update_slider_excluded_title(
    db: Session,
    record_id: UUID,
    data,
) -> dict:
    return update_excluded_title(db, record_id, data)


def delete_slider_excluded_title(
    db: Session,
    record_id: UUID,
) -> dict:
    return delete_excluded_title(db, record_id)
