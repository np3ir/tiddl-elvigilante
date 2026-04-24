from __future__ import annotations
import time
import random
import logging
import sys
import urllib3
import requests
from typing import Literal, TypeAlias, Any
from requests.adapters import HTTPAdapter
from requests.exceptions import (
    HTTPError, ConnectionError, Timeout, ChunkedEncodingError, ReadTimeout
)
from requests_cache import DO_NOT_CACHE, EXPIRE_IMMEDIATELY

from .client import TidalClientImproved
from .exceptions import ApiError
from .models.base import (
    AlbumItems, AlbumItemsCredits, ArtistAlbumsItems, ArtistVideosItems, Favorites,
    MixItems, PlaylistItems, Search, SessionResponse, TrackLyrics, TrackStream, VideoStream
)
from .models.resources import (
    Album, Artist, Playlist, StreamVideoQuality, Track, TrackQuality, Video,
    TrackCredits, TrackMix, ArtistBio, ArtistLinks, ArtistTopTracks,
    ActivityFeed, MixesFavorites, AudioQualityEnum, VideoQualityEnum, AlbumTypeEnum
)
from .models.review import AlbumReview

ID: TypeAlias = str | int

# ============================================================
# CONFIGURACIÓN DE LOGS Y RED
# ============================================================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
log = logging.getLogger(__name__)


class Limits:
    ARTIST_ALBUMS = 10;
    ARTIST_ALBUMS_MAX = 100
    ARTIST_VIDEOS = 10;
    ARTIST_VIDEOS_MAX = 100
    ALBUM_ITEMS = 20;
    ALBUM_ITEMS_MAX = 100
    PLAYLIST_ITEMS = 20;
    PLAYLIST_ITEMS_MAX = 100
    MIX_ITEMS = 20;
    MIX_ITEMS_MAX = 100


class TidalAPI:
    client: TidalClientImproved
    user_id: str
    country_code: str

    def __init__(self, client: TidalClientImproved, user_id: str, country_code: str) -> None:
        self.client = client
        self.user_id = user_id
        self.country_code = country_code
        self._rate_limit_delay = 0.0

        if hasattr(self.client, 'session'):
            adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=3)
            self.client.session.mount('https://', adapter)

    def _fetch_with_retry(self, *args: Any, **kwargs: Any):
        # Adaptive Throttling
        if self._rate_limit_delay > 0:
            time.sleep(self._rate_limit_delay)

        max_retries = 10
        attempt = 0
        base_backoff = 5
        max_backoff = 60

        while True:
            try:
                res = self.client.fetch(*args, **kwargs)
                # Success: reduce delay slightly
                if self._rate_limit_delay > 0:
                    self._rate_limit_delay = max(0.0, self._rate_limit_delay - 0.1)
                return res

            except Exception as e:
                is_net = isinstance(e, (ConnectionError, Timeout, ReadTimeout, ChunkedEncodingError))
                is_http = False
                status = None
                retry_head = None

                if isinstance(e, HTTPError) and getattr(e, "response", None):
                    status = e.response.status_code
                    retry_head = e.response.headers.get("Retry-After")
                
                elif isinstance(e, ApiError):
                    status = e.status

                if status:
                    if status in [401, 403]:
                        # Check if it's Asset not ready (subStatus 4005)
                        sub_status = None
                        try:
                            if isinstance(e, ApiError):
                                sub_status = e.sub_status
                            elif hasattr(e, "response"):
                                sub_status = e.response.json().get("subStatus")
                        except:
                            pass

                        if sub_status == 4005:
                            print(f"⚠️ Content not ready/available ({status}). Skipping...");
                            raise e

                        print(f"\n❌ TOKEN ERROR ({status}).");
                        raise e
                    if status in [406, 451]:
                        print(f"⚠️ Geo-blocked content ({status}). Skipping...");
                        raise e
                    if status in [400, 404]:
                        # Use debug log instead of print to avoid spamming UI for optional items like lyrics
                        log.debug(f"Content not found ({status}). Skipping...")
                        raise e
                    if status in [429, 500, 502, 503, 504]: 
                        is_http = True
                        if status == 429:
                            self._rate_limit_delay = min(5.0, self._rate_limit_delay + 1.0)
                        
                        # Add delay for 500/502/503/504 errors
                        if status in [500, 502, 503, 504]:
                            # Exponential backoff for server errors
                            wait_time = (2 ** attempt) + self._rate_limit_delay
                            print(f"⚠️ Server Error ({status}). Retrying in {wait_time:.1f}s...")
                            time.sleep(wait_time)
                elif "429" in str(e):
                    is_http = True
                    self._rate_limit_delay = min(5.0, self._rate_limit_delay + 1.0)

                if not is_net and not is_http: raise e

                attempt += 1
                if attempt > max_retries:
                    print(f"❌ SKIPPING TRACK: Failed {max_retries} times. Next...")
                    raise e

                wait = 0
                if retry_head:
                    try:
                        wait = int(retry_head)
                    except:
                        wait = 0
                    print(f"🛑 [TIDAL] Mandatory wait: {wait}s.")
                elif is_net:
                    wait = 10
                    print(f"⚠️ [NETWORK] No connection. Retrying in 10s...")
                elif is_http:
                    if wait <= 0: wait = min(base_backoff * (2 ** (attempt - 1)), max_backoff)
                    status_display = status if status is not None else "429/Limit"
                    print(f"⚠️ [API] Pause ({status_display})... {wait:.0f}s")

                time.sleep(wait + random.uniform(1, 3))
                continue

    # =========================================================================
    # MÉTODOS CORREGIDOS (Compatibilidad 'id' vs 'artist_id')
    # =========================================================================

    def get_album(self, album_id: ID = None, id: ID = None):
        # Acepta ambos nombres para evitar errores
        real_id = album_id or id
        return self._fetch_with_retry(Album, f"albums/{real_id}", {"countryCode": self.country_code}, expire_after=3600)

    def get_album_items(self, album_id: ID = None, id: ID = None, limit: int = Limits.ALBUM_ITEMS, offset: int = 0):
        real_id = album_id or id
        return self._fetch_with_retry(AlbumItems, f"albums/{real_id}/items",
                                      {"countryCode": self.country_code, "limit": min(limit, Limits.ALBUM_ITEMS_MAX),
                                       "offset": offset}, expire_after=3600)

    def get_album_items_credits(self, album_id: ID = None, id: ID = None, limit: int = Limits.ALBUM_ITEMS,
                                offset: int = 0):
        real_id = album_id or id
        return self._fetch_with_retry(AlbumItemsCredits, f"albums/{real_id}/items/credits",
                                      {"countryCode": self.country_code, "limit": min(limit, Limits.ALBUM_ITEMS_MAX),
                                       "offset": offset}, expire_after=3600)

    def get_album_review(self, album_id: ID = None, id: ID = None):
        real_id = album_id or id
        return self._fetch_with_retry(AlbumReview, f"albums/{real_id}/review", {"countryCode": self.country_code},
                                      expire_after=3600)

    def get_artist(self, artist_id: ID = None, id: ID = None):
        real_id = artist_id or id
        return self._fetch_with_retry(Artist, f"artists/{real_id}", {"countryCode": self.country_code},
                                      expire_after=3600)

    def get_artist_videos(self, artist_id: ID = None, id: ID = None, limit: int = Limits.ARTIST_VIDEOS,
                          offset: int = 0):
        real_id = artist_id or id
        return self._fetch_with_retry(ArtistVideosItems, f"artists/{real_id}/videos",
                                      {"countryCode": self.country_code, "limit": min(limit, Limits.ARTIST_VIDEOS_MAX),
                                       "offset": offset}, expire_after=3600)

    # AQUÍ ESTABA EL ERROR: Ahora aceptamos artist_id, id, o lo que manden.
    def get_artist_albums(self, artist_id: ID = None, id: ID = None, limit: int = Limits.ARTIST_ALBUMS, offset: int = 0,
                          filter: Literal["ALBUMS", "EPSANDSINGLES"] = "ALBUMS"):
        real_id = artist_id or id
        return self._fetch_with_retry(ArtistAlbumsItems, f"artists/{real_id}/albums",
                                      {"countryCode": self.country_code, "limit": min(limit, Limits.ARTIST_ALBUMS_MAX),
                                       "offset": offset, "filter": filter}, expire_after=3600)

    def get_mix_items(self, mix_id: str, limit: int = Limits.MIX_ITEMS, offset: int = 0):
        return self._fetch_with_retry(MixItems, f"mixes/{mix_id}/items",
                                      {"countryCode": self.country_code, "limit": min(limit, Limits.MIX_ITEMS_MAX),
                                       "offset": offset}, expire_after=3600)

    def get_favorites(self):
        return self._fetch_with_retry(Favorites, f"users/{self.user_id}/favorites/ids",
                                      {"countryCode": self.country_code}, expire_after=EXPIRE_IMMEDIATELY)

    def get_playlist(self, playlist_uuid: str):
        return self._fetch_with_retry(Playlist, f"playlists/{playlist_uuid}", {"countryCode": self.country_code},
                                      expire_after=EXPIRE_IMMEDIATELY)

    def get_playlist_items(self, playlist_uuid: str, limit: int = Limits.PLAYLIST_ITEMS, offset: int = 0):
        return self._fetch_with_retry(PlaylistItems, f"playlists/{playlist_uuid}/items",
                                      {"countryCode": self.country_code, "limit": min(limit, Limits.PLAYLIST_ITEMS_MAX),
                                       "offset": offset}, expire_after=EXPIRE_IMMEDIATELY)

    def get_search(self, query: str):
        return self._fetch_with_retry(Search, "search", {"countryCode": self.country_code, "query": query},
                                      expire_after=DO_NOT_CACHE)

    def get_session(self):
        return self._fetch_with_retry(SessionResponse, "sessions", expire_after=DO_NOT_CACHE)

    def get_track_lyrics(self, track_id: ID = None, id: ID = None):
        real_id = track_id or id
        return self._fetch_with_retry(TrackLyrics, f"tracks/{real_id}/lyrics", {"countryCode": self.country_code},
                                      expire_after=3600)

    def get_track(self, track_id: ID = None, id: ID = None):
        real_id = track_id or id
        return self._fetch_with_retry(Track, f"tracks/{real_id}", {"countryCode": self.country_code}, expire_after=3600)

    def get_track_stream(self, track_id: ID = None, id: ID = None, quality: TrackQuality = "LOSSLESS"):
        real_id = track_id or id
        params = {"countryCode": self.country_code, "audioquality": quality,
                  "playbackmode": "STREAM", "assetpresentation": "FULL"}
        try:
            return self._fetch_with_retry(TrackStream, f"tracks/{real_id}/playbackinfopostpaywall/v4",
                                          params, expire_after=DO_NOT_CACHE)
        except Exception:
            return self._fetch_with_retry(TrackStream, f"tracks/{real_id}/playbackinfopostpaywall",
                                          params, expire_after=DO_NOT_CACHE)

    def get_video(self, video_id: ID = None, id: ID = None):
        real_id = video_id or id
        return self._fetch_with_retry(Video, f"videos/{real_id}", {"countryCode": self.country_code}, expire_after=3600)

    def get_video_stream(self, video_id: ID = None, id: ID = None, quality: StreamVideoQuality = "HIGH"):
        real_id = video_id or id
        return self._fetch_with_retry(VideoStream, f"videos/{real_id}/playbackinfopostpaywall",
                                      {"countryCode": self.country_code, "videoquality": quality,
                                       "playbackmode": "STREAM", "assetpresentation": "FULL"},
                                      expire_after=DO_NOT_CACHE)

    # ====================================================================
    # NUEVOS ENDPOINTS (MEJORA 4)
    # ====================================================================

    def get_track_credits(self, track_id: ID) -> TrackCredits:
        """Get track credits"""
        return self._fetch_with_retry(
            TrackCredits,
            f"tracks/{track_id}/contributors",
            {"countryCode": self.country_code},
            expire_after=3600
        )

    def get_featured_from_contributors(self, track_id: ID) -> list[str]:
        """Return names of Featured Artists from the /contributors endpoint.

        Tidal sometimes removes featured artists from the main artists array
        but keeps them in the /contributors endpoint. This method fetches
        that endpoint and returns only the Featured Artist names.
        """
        try:
            from .client import API_V1_URL
            res = self.client.session.get(
                f"{API_V1_URL}/tracks/{track_id}/contributors",
                params={"countryCode": self.country_code},
                expire_after=3600,
            )
            if res.status_code != 200:
                return []
            items = res.json().get("items", [])
            return [i["name"] for i in items if i.get("role") == "Featured Artist" and i.get("name")]
        except Exception as e:
            log.debug(f"Could not fetch contributors for track {track_id}: {e}")
            return []

    def get_track_mix(self, track_id: ID) -> TrackMix:
        """Obtener mix relacionado al track"""
        return self._fetch_with_retry(
            TrackMix,
            f"tracks/{track_id}/mix",
            {"countryCode": self.country_code},
            expire_after=3600
        )

    def get_artist_bio(self, artist_id: ID) -> ArtistBio:
        """Get artist biography"""
        return self._fetch_with_retry(
            ArtistBio,
            f"artists/{artist_id}/bio",
            {"countryCode": self.country_code},
            expire_after=3600
        )

    def get_artist_links(self, artist_id: ID) -> ArtistLinks:
        """Obtener links externos del artista"""
        return self._fetch_with_retry(
            ArtistLinks,
            f"artists/{artist_id}/links",
            {"countryCode": self.country_code},
            expire_after=3600
        )

    def get_artist_toptracks(self, artist_id: ID, limit: int = 10) -> ArtistTopTracks:
        """Obtener top tracks del artista"""
        return self._fetch_with_retry(
            ArtistTopTracks,
            f"artists/{artist_id}/toptracks",
            {"countryCode": self.country_code, "limit": limit},
            expire_after=3600
        )

    # API V2 - Feed de actividad
    def get_activity_feed(self) -> ActivityFeed:
        """Obtener feed de nuevos lanzamientos de artistas seguidos"""
        return self._fetch_with_retry(
            ActivityFeed,
            f"feed/activities/",
            {"userId": self.user_id, "locale": "en-us", "countryCode": self.country_code},
            expire_after=300,  # 5 minutos
            api_version="v2"
        )

    # Mixes favoritos (v2)
    def get_favorite_mixes(self, limit: int = 10) -> MixesFavorites:
        """Obtener mixes favoritos del usuario"""
        return self._fetch_with_retry(
            MixesFavorites,
            "favorites/mixes",
            {"limit": limit, "locale": "en_US", "countryCode": self.country_code},
            expire_after=300,
            api_version="v2"
        )