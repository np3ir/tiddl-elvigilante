from typing import Literal

from pydantic import BaseModel

from .resources import (
    Album,
    Artist,
    Playlist,
    StreamVideoQuality,
    Track,
    TrackQuality,
    Video,
)


class SessionResponse(BaseModel):
    class Client(BaseModel):
        id: int
        name: str
        authorizedForOffline: bool
        authorizedForOfflineDate: str | None = None

    sessionId: str
    userId: int
    countryCode: str
    channelId: int
    partnerId: int
    client: Client


class Items(BaseModel):
    limit: int
    offset: int
    totalNumberOfItems: int


class ArtistAlbumsItems(Items):
    items: list[Album]


class ArtistVideosItems(Items):
    items: list[Video]


ItemType = Literal["track", "video"]


class AlbumItems(Items):
    class VideoItem(BaseModel):
        item: Video
        type: ItemType = "video"

    class TrackItem(BaseModel):
        item: Track
        type: ItemType = "track"

    items: list[TrackItem | VideoItem]


class AlbumItemsCredits(Items):
    class ItemWithCredits(BaseModel):
        class CreditsEntry(BaseModel):
            class Contributor(BaseModel):
                name: str
                id: int | None = None

            type: str
            contributors: list[Contributor]

        credits: list[CreditsEntry]

    class VideoItem(ItemWithCredits):
        item: Video
        type: ItemType = "video"

    class TrackItem(ItemWithCredits):
        item: Track
        type: ItemType = "track"

    items: list[TrackItem | VideoItem]


class PlaylistItems(Items):
    class PlaylistVideoItem(BaseModel):
        class PlaylistVideo(Video):
            dateAdded: str
            index: int
            itemUuid: str

        item: PlaylistVideo
        type: ItemType = "video"
        cut: None = None

    class PlaylistTrackItem(BaseModel):
        class PlaylistTrack(Track):
            dateAdded: str
            index: int
            itemUuid: str

        item: PlaylistTrack
        type: ItemType = "track"
        cut: None = None

    items: list[PlaylistTrackItem | PlaylistVideoItem]


class MixItems(Items):
    class MixItem(BaseModel):
        item: Track
        type: ItemType = "track"

    items: list[MixItem]


class Favorites(BaseModel):
    PLAYLIST: list[str]
    ALBUM: list[str]
    VIDEO: list[str]
    TRACK: list[str]
    ARTIST: list[str]


class TrackStream(BaseModel):
    """
    Represents audio stream metadata for a Tidal track.

    IMPORTANT:
    Tidal does NOT always return replay gain or peak amplitude fields.
    These MUST be Optional or Pydantic will raise validation errors.
    """

    trackId: int
    assetPresentation: Literal["FULL"]
    audioMode: Literal["STEREO"]
    audioQuality: TrackQuality
    manifestMimeType: Literal["application/dash+xml", "application/vnd.tidal.bts"]
    manifestHash: str
    manifest: str

    # Optional – often missing
    albumReplayGain: float | None = None
    albumPeakAmplitude: float | None = None
    trackReplayGain: float | None = None
    trackPeakAmplitude: float | None = None

    # Optional – depends on stream type
    bitDepth: int | None = None
    sampleRate: int | None = None


class VideoStream(BaseModel):
    videoId: int
    streamType: Literal["ON_DEMAND"]
    assetPresentation: Literal["FULL"]
    videoQuality: StreamVideoQuality
    manifestMimeType: Literal["application/dash+xml", "application/vnd.tidal.emu"]
    manifestHash: str
    manifest: str


class Search(BaseModel):
    class Artists(Items):
        items: list[Artist]

    class Albums(Items):
        items: list[Album]

    class Playlists(Items):
        items: list[Playlist]

    class Tracks(Items):
        items: list[Track]

    class Videos(Items):
        items: list[Video]

    class TopHit(BaseModel):
        value: Artist | Track | Playlist | Album
        type: Literal["ARTISTS", "TRACKS", "PLAYLISTS", "ALBUMS"]

    artists: Artists
    albums: Albums
    playlists: Playlists
    tracks: Tracks
    videos: Videos
    topHit: TopHit | None = None


class TrackLyrics(BaseModel):
    isRightToLeft: bool = False
    lyrics: str | None = None
    lyricsProvider: str | None = None
    providerCommontrackId: str | None = None
    providerLyricsId: str | None = None
    subtitles: str | None = None
    trackId: int
