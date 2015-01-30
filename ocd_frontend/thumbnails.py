import os
from PIL import Image, ImageOps
import requests
from tempfile import SpooledTemporaryFile

from ocd_frontend import settings


class CannotSaveOriginal(Exception):
    """Thrown when a thumbnail cannot be saved"""


class CannotSaveThumbnail(Exception):
    """Thrown when a thumbnail cannot be saved"""


class InvalidThumbnailSize(Exception):
    """Thrown when an invalid thumbnail size is provided"""


def get_thumbnail_path(identifier, thumbnail_size='large'):
    return os.path.join(settings.THUMBNAILS_DIR, identifier[:2],
                        '{}_{}.jpg'.format(identifier[2:], thumbnail_size))


def get_thumbnail_url(identifier, thumbnail_size='large'):
    return os.path.join(settings.THUMBNAIL_URL, identifier[:2],
                        '{}_{}.jpg'.format(identifier[2:], thumbnail_size))


def fetch_original(url, identifier):
    with SpooledTemporaryFile(max_size=1024*1024, prefix='ocd_thumb_',
                              suffix='.tmp', dir=settings.THUMBNAILS_TEMP_DIR) as tempfile:

        r = requests.get(url, stream=True)

        for chunk in r.iter_content(chunk_size=512*1024):
            if chunk:
                tempfile.write(chunk)

        tempfile.flush()  # clear buffer
        tempfile.seek(0)  # set pointer

        im = Image.open(tempfile)

        thumb_path = get_thumbnail_path(identifier, 'original')

        # Create the (sub)directory if it does not exist yet
        if not os.path.exists(os.path.dirname(thumb_path)):
            os.makedirs(os.path.dirname(thumb_path))

        try:
            im.save(get_thumbnail_path(identifier, 'original'), 'JPEG',
                    quality=90)
        except IOError:
            raise CannotSaveOriginal


def create_thumbnail(source, identifier, size='large'):
    _size = settings.THUMBNAIL_SIZES.get(size)

    if not _size:
        raise InvalidThumbnailSize
    try:
        im = Image.open(source)
        if _size.get('type') == 'crop':
            imc = ImageOps.fit(im, _size.get('size'), Image.ANTIALIAS)
            imc.save(get_thumbnail_path(identifier, size), 'JPEG', quality=90)
        else:
            im.thumbnail(_size.get('size'), Image.ANTIALIAS)
            im.save(get_thumbnail_path(identifier, size), 'JPEG', quality=90)
    except IOError:
        raise CannotSaveThumbnail
