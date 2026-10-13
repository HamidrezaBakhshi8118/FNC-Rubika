"""Inspect local media and build small JPEG previews without changing the file."""

from __future__ import annotations

import base64
from io import BytesIO
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


def _thumbnail(image: Image.Image) -> str:
    preview = image.convert('RGB')
    preview.thumbnail((128, 128))
    with BytesIO() as buffer:
        preview.save(buffer, format='JPEG', quality=70)
        return base64.b64encode(buffer.getvalue()).decode('ascii')


def photo_metadata(path: Path) -> dict[str, Any]:
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original)
        return {'type': 'Image', 'width': image.width, 'height': image.height,
                'thumb_inline': _thumbnail(image)}


def video_metadata(path: Path) -> dict[str, Any]:
    import av

    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError('The file has no video stream')
        stream = container.streams.video[0]
        if stream.duration is not None and stream.time_base is not None:
            seconds = float(stream.duration * stream.time_base)
        elif container.duration is not None:
            seconds = container.duration / av.time_base
        else:
            raise ValueError('The video duration could not be determined')
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('The video duration must be positive')
        frame = next(container.decode(stream), None)
        if frame is None:
            raise ValueError('The video has no decodable frames')
        image = frame.to_image()
        rotation = getattr(frame, 'rotation', 0)
        if rotation:
            image = image.rotate(rotation, expand=True)
        return {'type': 'Video', 'width': image.width, 'height': image.height,
                'time': max(1, math.floor(seconds * 1000)), 'thumb_inline': _thumbnail(image)}
