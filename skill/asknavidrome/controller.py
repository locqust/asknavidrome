import logging
from typing import Union

from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_model import Response
from ask_sdk_model.ui import StandardCard
from ask_sdk_model.interfaces.audioplayer import (
    PlayDirective, PlayBehavior, AudioItem, Stream, AudioItemMetadata,
    StopDirective)
from ask_sdk_model.interfaces import display

from .track import Track
from .subsonic_api import SubsonicConnection
from .media_queue import MediaQueue

logger = logging.getLogger(__name__)

# Fallback art URL (the Navidrome logo) used when a track has no coverArt ID.
# This is also the value used before NAVI_BASE_URL is configured.
_FALLBACK_ART_URL = 'https://github.com/navidrome/navidrome/raw/master/resources/logo-192x192.png'

# Set by app.py once NAVI_BASE_URL is read from the environment.
# controller.py reads this to build proxied cover-art URLs.
base_url: str = ''

#
# Functions
#


def _art_url(track_details: Track) -> str:
    """Return the cover art URL to embed in AudioItemMetadata.

    If base_url has been configured and the track has a coverArt ID, returns
    a URL pointing at our own /cover/<id> proxy endpoint so that Alexa fetches
    the image through AskNavidrome (no Navidrome credentials in the URL).

    Falls back to the static Navidrome logo if either value is missing.

    :param Track track_details: The track whose art is needed
    :return: An HTTPS URL for the album art image
    :rtype: str
    """
    if base_url and track_details.cover_art:
        return f'{base_url}/cover/{track_details.cover_art}'
    return _FALLBACK_ART_URL


def start_playback(mode: str, text: str, card_data: dict, track_details: Track, handler_input: HandlerInput) -> Response:
    """Function to play audio.

    Begin playing audio when:

        - Play Audio Intent is invoked.
        - Resuming audio when stopped / paused.
        - Next / Previous commands issues.

    .. note ::
       - https://developer.amazon.com/docs/custom-skills/audioplayer-interface-reference.html#play
           - REPLACE_ALL: Immediately begin playback of the specified stream,
             and replace current and enqueued streams.

    :param str mode: play | continue - Play immediately or enqueue a track
    :param str text: Text which should be spoken before playback starts
    :param dict card_data: Data to display on a card
    :param Track track_details: A Track object containing details of the track to use
    :param HandlerInput handler_input: The Amazon Alexa HandlerInput object
    :return: Amazon Alexa Response class
    :rtype: Response
    """
    metadata = AudioItemMetadata(
        title=track_details.title,
        subtitle=f'{track_details.artist} — {track_details.album}',
        art=display.Image(
            content_description=track_details.title,
            sources=[
                display.ImageInstance(
                    url=_art_url(track_details)
                )
            ]
        )
        # background_image intentionally omitted — we only want the square
        # thumbnail icon, not a full-bleed backdrop.
    )
    
    if mode == 'play':
        # Starting playback
        logger.debug('In start_playback() - play mode')

        if card_data:
            # Cards are only supported if we are starting a new session
            handler_input.response_builder.set_card(
                StandardCard(
                    title=card_data['title'], text=card_data['text'],
                    # image=Image(
                    #    small_image_url=card_data['small_image_url'],
                    #    large_image_url=card_data['large_image_url'])
                )
            )

        handler_input.response_builder.add_directive(
            PlayDirective(
                play_behavior=PlayBehavior.REPLACE_ALL,
                audio_item=AudioItem(
                    stream=Stream(
                        token=track_details.id,
                        url=track_details.uri,
                        offset_in_milliseconds=track_details.offset,
                        expected_previous_token=None),
                    metadata=metadata
                )
            )
        ).set_should_end_session(True)

        if text:
            # Text is not supported if we are continuing an existing play list
            handler_input.response_builder.speak(text)

        logger.debug(f'Track ID: {track_details.id}')
        logger.debug(f'Track Previous ID: {track_details.previous_id}')
        logger.info(f'Playing track: {track_details.title} by: {track_details.artist}')

    elif mode == 'continue':
        # Continuing Playback
        logger.debug('In start_playback() - continue mode')

        handler_input.response_builder.add_directive(
            PlayDirective(
                play_behavior=PlayBehavior.ENQUEUE,
                audio_item=AudioItem(
                    stream=Stream(
                        token=track_details.id,
                        url=track_details.uri,
                        # Offset is 0 to allow playing of the next track from the beginning
                        # if the Previous intent is used
                        offset_in_milliseconds=0,
                        expected_previous_token=track_details.previous_id),
                    metadata=metadata
                )
            )
        ).set_should_end_session(True)

        logger.debug(f'Track ID: {track_details.id}')
        logger.debug(f'Track Previous ID: {track_details.previous_id}')
        logger.info(f'Enqueuing track: {track_details.title} by: {track_details.artist}')

    return handler_input.response_builder.response


def stop(handler_input: HandlerInput) -> Response:
    """Stop playback

    :param HandlerInput handler_input: The Amazon Alexa HandlerInput object
    :return: Amazon Alexa Response class
    :rtype: Response
    """
    logger.debug('In stop()')

    handler_input.response_builder.add_directive(StopDirective())

    return handler_input.response_builder.response


def add_screen_background(card_data: dict, track_details: Track = None) -> Union[AudioItemMetadata, None]:
    """Add now-playing metadata for devices with screens.

    Builds an AudioItemMetadata object with the track's album art served
    through the AskNavidrome cover-art proxy, so Alexa never needs to
    authenticate directly against Navidrome.

    :param dict card_data: Dictionary containing card data
    :param Track track_details: Optional Track object; used to resolve cover art URL
    :return: An Amazon AudioItemMetadata object or None if card data is not present
    :rtype: AudioItemMetadata | None
    """
    logger.debug('In add_screen_background()')

    if card_data:
        art_source = _art_url(track_details) if track_details else _FALLBACK_ART_URL

        metadata = AudioItemMetadata(
            title=card_data['title'],
            subtitle=card_data['text'],
            art=display.Image(
                content_description=card_data['title'],
                sources=[
                    display.ImageInstance(
                        url=art_source
                    )
                ]
            )
            # background_image intentionally omitted — square thumbnail only.
        )

        return metadata
    else:
        return None


def enqueue_songs(api: SubsonicConnection, queue: MediaQueue, song_id_list: list) -> None:
    """Enqueue songs

    Add Track objects to the queue deque

    :param SubsonicConnection api: A SubsonicConnection object to allow access to the Navidrome API
    :param MediaQueue queue: A MediaQueue object
    :param list song_id_list: A list of song IDs to enqueue
    :return: None
    """

    for song_id in song_id_list:
        song_details = api.get_song_details(song_id)
        song_uri = api.get_song_uri(song_id)

        # Create track object from song details
        new_track = Track(song_details.get('song').get('id'),
                          song_details.get('song').get('title'),
                          song_details.get('song').get('artist'),
                          song_details.get('song').get('artistId'),
                          song_details.get('song').get('album'),
                          song_details.get('song').get('albumId'),
                          song_details.get('song').get('track'),
                          song_details.get('song').get('year'),
                          song_details.get('song').get('genre'),
                          song_details.get('song').get('duration'),
                          song_details.get('song').get('bitRate'),
                          song_uri,
                          0,
                          None,
                          song_details.get('song').get('coverArt', ''))

        # Add track object to queue
        queue.add_track(new_track)
