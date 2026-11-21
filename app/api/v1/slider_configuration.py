
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db

from app.schemas.slider_configuration import (
    SliderCuratedTitleCreate,
    SliderCuratedTitleUpdate,
    SliderCuratedTitleResponse,
    SliderKeywordCreate,
    SliderKeywordUpdate,
    SliderKeywordResponse,
    SliderCollectionCreate,
    SliderCollectionUpdate,
    SliderCollectionResponse,
    SliderCompanyCreate,
    SliderCompanyUpdate,
    SliderCompanyResponse,
    SliderNetworkCreate,
    SliderNetworkUpdate,
    SliderNetworkResponse,
    SliderExcludedTitleCreate,
    SliderExcludedTitleUpdate,
    SliderExcludedTitleResponse,
)

from app.services.slider_configuration import (
    create_slider_curated_title,
    list_slider_curated_titles,
    get_slider_curated_title,
    update_slider_curated_title,
    delete_slider_curated_title,

    create_slider_keyword,
    list_slider_keywords,
    get_slider_keyword,
    update_slider_keyword,
    delete_slider_keyword,

    create_slider_collection,
    list_slider_collections,
    get_slider_collection,
    update_slider_collection,
    delete_slider_collection,

    create_slider_company,
    list_slider_companies,
    get_slider_company,
    update_slider_company,
    delete_slider_company,

    create_slider_network,
    list_slider_networks,
    get_slider_network,
    update_slider_network,
    delete_slider_network,

    create_slider_excluded_title,
    list_slider_excluded_titles,
    get_slider_excluded_title,
    update_slider_excluded_title,
    delete_slider_excluded_title,
)


router = APIRouter(
    prefix="/platforms/sliders",
    tags=["Slider Configuration"],
)


# ==================================================
# CURATED TITLES
# ==================================================

@router.post(
    "/{slider_id}/curated-titles",
    response_model=SliderCuratedTitleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_curated_title(
    slider_id: UUID,
    data: SliderCuratedTitleCreate,
    db: Session = Depends(get_db),
):
    return create_slider_curated_title(db, slider_id, data)


@router.get(
    "/{slider_id}/curated-titles",
    response_model=list[SliderCuratedTitleResponse],
)
def get_curated_titles(
    slider_id: UUID,
    enabled_only: bool = False,
    db: Session = Depends(get_db),
):
    return list_slider_curated_titles(db, slider_id, enabled_only)


@router.get(
    "/curated-titles/{record_id}",
    response_model=SliderCuratedTitleResponse,
)
def get_curated_title(
    record_id: UUID,
    db: Session = Depends(get_db),
):
    return get_slider_curated_title(db, record_id)


@router.patch(
    "/curated-titles/{record_id}",
    response_model=SliderCuratedTitleResponse,
)
def update_curated_title(
    record_id: UUID,
    data: SliderCuratedTitleUpdate,
    db: Session = Depends(get_db),
):
    return update_slider_curated_title(db, record_id, data)


@router.delete("/curated-titles/{record_id}")
def remove_curated_title(
    record_id: UUID,
    db: Session = Depends(get_db),
):
    return delete_slider_curated_title(db, record_id)


# ==================================================
# KEYWORDS
# ==================================================

@router.post(
    "/{slider_id}/keywords",
    response_model=SliderKeywordResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_keyword(
    slider_id: UUID,
    data: SliderKeywordCreate,
    db: Session = Depends(get_db),
):
    return create_slider_keyword(db, slider_id, data)


@router.get(
    "/{slider_id}/keywords",
    response_model=list[SliderKeywordResponse],
)
def get_keywords(
    slider_id: UUID,
    enabled_only: bool = False,
    db: Session = Depends(get_db),
):
    return list_slider_keywords(db, slider_id, enabled_only)


@router.get("/keywords/{record_id}", response_model=SliderKeywordResponse)
def get_keyword(
    record_id: UUID,
    db: Session = Depends(get_db),
):
    return get_slider_keyword(db, record_id)


@router.patch("/keywords/{record_id}", response_model=SliderKeywordResponse)
def update_keyword(
    record_id: UUID,
    data: SliderKeywordUpdate,
    db: Session = Depends(get_db),
):
    return update_slider_keyword(db, record_id, data)


@router.delete("/keywords/{record_id}")
def remove_keyword(
    record_id: UUID,
    db: Session = Depends(get_db),
):
    return delete_slider_keyword(db, record_id)


# ==================================================
# COLLECTIONS
# ==================================================

@router.post(
    "/{slider_id}/collections",
    response_model=SliderCollectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_collection(
    slider_id: UUID,
    data: SliderCollectionCreate,
    db: Session = Depends(get_db),
):
    return create_slider_collection(db, slider_id, data)


@router.get(
    "/{slider_id}/collections",
    response_model=list[SliderCollectionResponse],
)
def get_collections(
    slider_id: UUID,
    enabled_only: bool = False,
    db: Session = Depends(get_db),
):
    return list_slider_collections(db, slider_id, enabled_only)


@router.get("/collections/{record_id}", response_model=SliderCollectionResponse)
def get_collection(
    record_id: UUID,
    db: Session = Depends(get_db),
):
    return get_slider_collection(db, record_id)


@router.patch("/collections/{record_id}", response_model=SliderCollectionResponse)
def update_collection(
    record_id: UUID,
    data: SliderCollectionUpdate,
    db: Session = Depends(get_db),
):
    return update_slider_collection(db, record_id, data)


@router.delete("/collections/{record_id}")
def remove_collection(
    record_id: UUID,
    db: Session = Depends(get_db),
):
    return delete_slider_collection(db, record_id)


# ==================================================
# COMPANIES / STUDIOS
# ==================================================

@router.post(
    "/{slider_id}/companies",
    response_model=SliderCompanyResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_company(
    slider_id: UUID,
    data: SliderCompanyCreate,
    db: Session = Depends(get_db),
):
    return create_slider_company(db, slider_id, data)


@router.get(
    "/{slider_id}/companies",
    response_model=list[SliderCompanyResponse],
)
def get_companies(
    slider_id: UUID,
    enabled_only: bool = False,
    db: Session = Depends(get_db),
):
    return list_slider_companies(db, slider_id, enabled_only)


@router.get("/companies/{record_id}", response_model=SliderCompanyResponse)
def get_company(
    record_id: UUID,
    db: Session = Depends(get_db),
):
    return get_slider_company(db, record_id)


@router.patch("/companies/{record_id}", response_model=SliderCompanyResponse)
def update_company(
    record_id: UUID,
    data: SliderCompanyUpdate,
    db: Session = Depends(get_db),
):
    return update_slider_company(db, record_id, data)


@router.delete("/companies/{record_id}")
def remove_company(
    record_id: UUID,
    db: Session = Depends(get_db),
):
    return delete_slider_company(db, record_id)


# ==================================================
# TV NETWORKS
# ==================================================

@router.post(
    "/{slider_id}/networks",
    response_model=SliderNetworkResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_network(
    slider_id: UUID,
    data: SliderNetworkCreate,
    db: Session = Depends(get_db),
):
    return create_slider_network(db, slider_id, data)


@router.get(
    "/{slider_id}/networks",
    response_model=list[SliderNetworkResponse],
)
def get_networks(
    slider_id: UUID,
    enabled_only: bool = False,
    db: Session = Depends(get_db),
):
    return list_slider_networks(db, slider_id, enabled_only)


@router.get("/networks/{record_id}", response_model=SliderNetworkResponse)
def get_network(
    record_id: UUID,
    db: Session = Depends(get_db),
):
    return get_slider_network(db, record_id)


@router.patch("/networks/{record_id}", response_model=SliderNetworkResponse)
def update_network(
    record_id: UUID,
    data: SliderNetworkUpdate,
    db: Session = Depends(get_db),
):
    return update_slider_network(db, record_id, data)


@router.delete("/networks/{record_id}")
def remove_network(
    record_id: UUID,
    db: Session = Depends(get_db),
):
    return delete_slider_network(db, record_id)


# ==================================================
# EXCLUDED TITLES
# ==================================================

@router.post(
    "/{slider_id}/excluded-titles",
    response_model=SliderExcludedTitleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_excluded_title(
    slider_id: UUID,
    data: SliderExcludedTitleCreate,
    db: Session = Depends(get_db),
):
    return create_slider_excluded_title(db, slider_id, data)


@router.get(
    "/{slider_id}/excluded-titles",
    response_model=list[SliderExcludedTitleResponse],
)
def get_excluded_titles(
    slider_id: UUID,
    enabled_only: bool = False,
    db: Session = Depends(get_db),
):
    return list_slider_excluded_titles(db, slider_id, enabled_only)


@router.get(
    "/excluded-titles/{record_id}",
    response_model=SliderExcludedTitleResponse,
)
def get_excluded_title(
    record_id: UUID,
    db: Session = Depends(get_db),
):
    return get_slider_excluded_title(db, record_id)


@router.patch(
    "/excluded-titles/{record_id}",
    response_model=SliderExcludedTitleResponse,
)
def update_excluded_title(
    record_id: UUID,
    data: SliderExcludedTitleUpdate,
    db: Session = Depends(get_db),
):
    return update_slider_excluded_title(db, record_id, data)


@router.delete("/excluded-titles/{record_id}")
def remove_excluded_title(
    record_id: UUID,
    db: Session = Depends(get_db),
):
    return delete_slider_excluded_title(db, record_id)
