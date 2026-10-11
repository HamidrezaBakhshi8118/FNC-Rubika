from fnc_rubika import Client


with Client('personal') as client:
    print('Chats:', client.api.getChats())
