from app.schemas.platform import ContentCard, SliderSection

def test_content_card_contract():
    card = ContentCard(tmdb_id=123, media_type="movie", title="Example", genre_ids=[28])
    assert card.tmdb_id == 123
    assert card.media_type == "movie"

def test_empty_slider_is_valid():
    section = SliderSection(key="continue_watching", title="Continue Watching", items=[])
    assert section.items == []
    assert section.has_more is False
