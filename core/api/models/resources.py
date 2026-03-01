from datetime import datetime
from typing import Literal, Any, Optional, List
from enum import Enum

from pydantic import BaseModel, Field

# ====================================================================
# IMPROVEMENT 4: Add missing enums and constants
# ====================================================================

class AudioQualityEnum(str, Enum):
    """Complete audio quality enum per documentation"""
    LOW = "LOW"  # 96 kbps AAC
    HIGH = "HIGH"  # 320 kbps AAC
    LOSSLESS = "LOSSLESS"  # 1411 kbps FLAC 16bit/44.1kHz
    HI_RES = "HI_RES"  # 24bit/96kHz MQA FLAC
    HI_RES_LOSSLESS = "HI_RES_LOSSLESS"  # Nuevo formato


class VideoQualityEnum(str, Enum):
    """Complete video quality enum per documentation"""
    AUDIO_ONLY = "AUDIO_ONLY"  # 96 kbps MP4
    LOW = "LOW"  # 640x360 1116 kbps MP4
    MEDIUM = "MEDIUM"  # 720p
    HIGH = "HIGH"  # 1080p


class AlbumTypeEnum(str, Enum):
    """Album types per documentation"""
    ALBUM = "ALBUM"
    EP = "EP"
    SINGLE = "SINGLE"
    COMPILATION = "COMPILATION"


TrackQuality = Literal["LOW", "HIGH", "LOSSLESS", "HI_RES_LOSSLESS"]

# audio_only is not stable
StreamVideoQuality = Literal["AUDIO_ONLY", "LOW", "MEDIUM", "HIGH"]

MediaMetadataTags = Literal["LOSSLESS", "HIRES_LOSSLESS", "DOLBY_ATMOS"]


class Track(BaseModel):

    class Artist(BaseModel):
        id: int
        name: str
        type: str
        picture: str | None = None

    class Album(BaseModel):
        id: int
        title: str
        cover: str | None = None
        vibrantColor: str | None = None
        videoCover: str | None = None
        # Genre field for metadata
        genre: str | None = None

    class MediaMetadata(BaseModel):
        tags: list[MediaMetadataTags]

    id: int
    title: str
    duration: int
    replayGain: float
    peak: float
    allowStreaming: bool
    streamReady: bool
    adSupportedStreamReady: bool
    djReady: bool
    stemReady: bool
    streamStartDate: datetime | str | None = None
    premiumStreamingOnly: bool
    trackNumber: int
    volumeNumber: int
    version: str | None = None
    popularity: int
    copyright: str | None = None
    bpm: int | None = None
    url: str
    # FIX: isrc is now Optional (handles unavailable tracks)
    isrc: str | None = None
    editable: bool
    explicit: bool
    audioQuality: TrackQuality
    audioModes: list[str]
    # FIX: mediaMetadata is now Optional
    mediaMetadata: MediaMetadata | dict | None = None
    artist: Artist | None = None
    artists: list[Artist]
    album: Album
    mixes: dict[str, str] | None = None


class Video(BaseModel):

    class Artist(BaseModel):
        id: int
        name: str
        type: str
        picture: str | None = None

    class Album(BaseModel):
        # ID and Title optional for Ghost Albums
        id: int | None = None
        title: str | None = None
        cover: str | None = None
        vibrantColor: str | None = None
        videoCover: str | None = None

    id: int
    title: str
    volumeNumber: int
    trackNumber: int
    releaseDate: datetime | str | None = None
    streamStartDate: datetime | str | None = None
    imagePath: str | None = None
    # FIX: imageId is now Optional
    imageId: str | None = None
    vibrantColor: str | None = None
    duration: int
    # FIX: quality is now Optional
    quality: Literal["MP4_1080P"] | str | None = None
    streamReady: bool
    adSupportedStreamReady: bool
    djReady: bool
    stemReady: bool
    allowStreaming: bool
    explicit: bool
    popularity: int
    # FIX: type is now Optional
    type: str | None = None
    adsUrl: str | None = None
    # FIX: adsPrePaywallOnly is now Optional
    adsPrePaywallOnly: bool | None = None
    artist: Artist | None = None
    artists: list[Artist]
    album: Album | None = None


class Explicit:
    def __init__(self, val):
        self.val = val

    def __format__(self, fmt):
        if not self.val:
            return ""
        if "shortparens" in fmt: return " (explicit)"
        if "parens" in fmt: return " (Explicit)"
        if "upper" in fmt: return "EXPLICIT" if "long" in fmt else "E"
        return "explicit" if "long" in fmt else "E"


class Album(BaseModel):

    class Artist(BaseModel):
        id: int
        name: str
        type: Literal["MAIN", "FEATURED"]
        picture: str | None = None

    class MediaMetadata(BaseModel):
        tags: list[MediaMetadataTags]

    id: int
    title: str
    duration: int
    streamReady: bool
    adSupportedStreamReady: bool
    djReady: bool
    stemReady: bool
    streamStartDate: datetime | str | None = None
    allowStreaming: bool
    premiumStreamingOnly: bool
    numberOfTracks: int
    numberOfVideos: int
    numberOfVolumes: int
    releaseDate: str | None = None 
    copyright: str | None = None
    type: Literal["ALBUM", "SINGLE", "EP"]
    version: str | None = None
    url: str
    cover: str | None = None
    vibrantColor: str | None = None
    videoCover: str | None = None
    explicit: bool
    upc: str
    popularity: int
    audioQuality: str
    audioModes: list[str]
    mediaMetadata: MediaMetadata
    # artist is none in search query
    artist: Artist | None = None
    artists: list[Artist]
    genre: str | None = None


class Playlist(BaseModel):

    class Creator(BaseModel):
        id: int

    uuid: str
    title: str
    numberOfTracks: int
    numberOfVideos: int
    creator: Creator | dict[Any, Any]
    description: str | None = None
    duration: int
    lastUpdated: str | None = None
    created: str | None = None
    type: str
    publicPlaylist: bool
    url: str
    image: str | None = None
    popularity: int
    squareImage: str | None = None
    promotedArtists: list[Album.Artist]
    lastItemAddedAt: str | None = None


# ==================================================================== 
# MEJORA 5: Modelo para ETag y control de concurrencia 
# ==================================================================== 

class PlaylistWithETag(Playlist):
    """Playlist with ETag to prevent corruption on edits"""
    etag: Optional[str] = None  # Extracted from If-None-Match header
    
    class Config:
        extra = "allow"


class Artist(BaseModel):

    class Role(BaseModel):
        categoryId: int
        category: Literal[
            "Artist",
            "Songwriter",
            "Performer",
            "Producer",
            "Engineer",
            "Production team",
            "Misc",
        ]

    class Mix(BaseModel):
        ARTIST_MIX: str
        MASTER_ARTIST_MIX: str | None = None

    id: int
    name: str
    type: str | None = None
    artistTypes: list[str] | None = None
    url: str | None = None
    picture: str | None = None
    selectedAlbumCoverFallback: str | None = None
    popularity: int | None = None
    artistRoles: list[Role] | None = None
    mixes: Mix | dict[Any, Any] | None = None


# ==================================================================== 
# MEJORA 1: Agregar TODOS los campos documentados en la API 
# ==================================================================== 

class AlbumExtended(BaseModel): 
    """Complete Album model per official TIDAL documentation""" 
    id: int 
    title: str 
    duration: int 
    streamReady: bool 
    streamStartDate: datetime 
    allowStreaming: bool 
    premiumStreamingOnly: bool 
    numberOfTracks: int 
    numberOfVideos: int 
    numberOfVolumes: int 
    releaseDate: str 
    copyright: str 
    type: Literal["ALBUM", "EP", "SINGLE", "COMPILATION"] 
    version: Optional[str] = None 
    url: str 
    cover: str 
    videoCover: Optional[str] = None 
    explicit: bool 
    upc: str 
    popularity: int 
    audioQuality: Literal["LOW", "HIGH", "LOSSLESS", "HI_RES"] 
    audioModes: List[str] 
    
    # NEW FIELDS not included in your current code: 
    artist: dict  # {"id": int, "name": str, "type": str} 
    artists: List[dict]  # Lista completa de artistas 
    
    # Missing fields useful for filtering: 
    mediaMetadata: Optional[dict] = None  # Metadatos adicionales 
    
    class Config: 
        # Permitir campos adicionales que TIDAL pueda agregar 
        extra = "allow" 


class TrackExtended(BaseModel): 
    """Modelo completo de Track con TODOS los campos de la API""" 
    id: int 
    title: str 
    duration: int 
    replayGain: float 
    peak: float 
    allowStreaming: bool 
    streamReady: bool 
    streamStartDate: datetime 
    premiumStreamingOnly: bool 
    trackNumber: int 
    volumeNumber: int 
    version: Optional[str] = None 
    popularity: int 
    copyright: str 
    url: str 
    isrc: str 
    editable: bool 
    explicit: bool 
    audioQuality: Literal["LOW", "HIGH", "LOSSLESS", "HI_RES"] 
    audioModes: List[str] 
    
    # CRUCIAL FIELDS missing from your implementation: 
    artist: dict 
    artists: List[dict] 
    album: dict 
    mixes: dict  # {"TRACK_MIX": "...", "MASTER_TRACK_MIX": "..."} 
    
    # Useful new fields: 
    dateAdded: Optional[datetime] = None  # Para favoritos 
    index: Optional[int] = None  # Para playlists 
    itemUuid: Optional[str] = None  # Para playlists 


# ==================================================================== 
# MEJORA 2: Agregar modelos para NUEVOS endpoints no implementados 
# ==================================================================== 

class TrackCredits(BaseModel): 
    """Track credits - Endpoint not implemented in your code""" 
    type: str  # "Composer", "Producer", etc. 
    contributors: List[dict]  # [{"name": str, "id": Optional[int]}] 


class TrackMix(BaseModel): 
    """Mix relacionado a un track - Endpoint no implementado""" 
    id: str 


class ArtistBio(BaseModel): 
    """Artist biography - Endpoint not implemented""" 
    source: str 
    lastUpdated: datetime 
    text: str 
    summary: str 


class ArtistLinks(BaseModel): 
    """Links externos del artista - Endpoint no implementado""" 
    limit: int 
    offset: int 
    totalNumberOfItems: int 
    items: List[dict]  # [{"url": str, "siteName": str}] 
    source: str 


class ArtistTopTracks(BaseModel): 
    """Top tracks del artista - Endpoint no implementado""" 
    limit: int 
    offset: int 
    totalNumberOfItems: int 
    items: List[TrackExtended] 


# ==================================================================== 
# MEJORA 3: Agregar modelos para el Feed API (v2) 
# ==================================================================== 

class ActivityFeed(BaseModel): 
    """Feed de actividad de artistas seguidos - API v2 no implementada""" 
    activities: List[dict] 
    stats: dict  # {"totalNotSeenActivities": int} 


class MixesFavorites(BaseModel): 
    """Favoritos de mixes - Endpoint v2 no implementado""" 
    items: List[dict] 
    cursor: Optional[str] = None 
    lastModifiedAt: datetime
