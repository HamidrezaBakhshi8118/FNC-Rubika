import asyncio
from fnc_rubika import Client


async def main():
    client = Client('personal')

    @client.on('message')
    async def handle_message(_, delivery):
        # This example prints event IDs only; it sends no replies.
        print('Message update:', delivery.event.event_id)

    async with client:
        print('Chats:', await client.getChats())
        await client.run()


if __name__ == '__main__':
    asyncio.run(main())
