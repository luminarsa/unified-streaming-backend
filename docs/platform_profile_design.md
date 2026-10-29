# Platform profile and slider design

The platform profile is configuration, not a stored movie list.

Recommended slider strategies:
- `continue_watching`: local progress only
- `recommended`: dynamically fetched candidates, ranked with profile signals
- `provider_popular`: discover sorted by popularity with regional provider filter
- `provider_recent`: discover sorted by release date with regional provider filter
- `trending`: TMDB trending; label as global trending unless intersected with filtered platform candidates
- `company_popular` / `company_recent`: company-filtered discover queries
- `network_popular` / `network_recent`: network-filtered TV discover queries
- `genre`: genre ID plus provider/company/network filter where supported
- `top_rated`: discover sorted by vote average with a vote-count floor
- `because_you_watched`: candidates related to profile's high-confidence titles, filtered to the platform's discovery policy

TMDB endpoints:
- Movies: `/discover/movie`
- TV: `/discover/tv`
- Trending: `/trending/{media_type}/{time_window}`
- Provider filtering: `with_watch_providers` together with `watch_region`
- Company filtering: `with_companies`
- TV network filtering: `with_networks`
- Genre filtering: `with_genres`

Provider IDs must be verified for the region. A studio/company relationship is not proof that a title is currently available on a streaming provider. TMDB trending is global and cannot by itself guarantee Netflix-only results.
