"""Readable examples for forwarding and sending photos/videos."""

import asyncio
from pathlib import Path

from fnc_rubika import Client


async def main() -> None:
    chat_id = 'YOUR_DESTINATION_GUID'
    downloads = Path.home() / 'Downloads'

    async with Client('personal') as client:
        await client.forward_message('SOURCE_CHAT_GUID', 'MESSAGE_ID', chat_id)
        await client.send_photo(chat_id, downloads / 'photo.jpg')
        await client.send_photo(chat_id, downloads / 'photo.jpg', caption='کپشن عکس')
        await client.send_video(chat_id, downloads / 'video.mp4')
        await client.send_video(chat_id, downloads / 'video.mp4', caption='کپشن فیلم')


if __name__ == '__main__':
    asyncio.run(main())
