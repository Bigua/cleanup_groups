import asyncio
import os
import sys
import configparser
import datetime


from getpass import getpass
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from telethon.network import ConnectionTcpAbridged
from telethon.utils import get_display_name
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights , UserStatusOffline, InputPeerEmpty


# Create a global variable to hold the loop we will be using
loop = asyncio.get_event_loop()


def sprint(string, *args, **kwargs):
    """Safe Print (handle UnicodeEncodeErrors on some terminals)"""
    try:
        print(string, *args, **kwargs)
    except UnicodeEncodeError:
        string = string.encode('utf-8', errors='ignore')\
                       .decode('ascii', errors='ignore')
        print(string, *args, **kwargs)


def print_title(title):
    """Helper function to print titles to the console more nicely"""
    sprint('\n')
    sprint('=={}=='.format('=' * len(title)))
    sprint('= {} ='.format(title))
    sprint('=={}=='.format('=' * len(title)))


def bytes_to_string(byte_count):
    """Converts a byte count to a string (in KB, MB...)"""
    suffix_index = 0
    while byte_count >= 1024:
        byte_count /= 1024
        suffix_index += 1

    return '{:.2f}{}'.format(
        byte_count, [' bytes', 'KB', 'MB', 'GB', 'TB'][suffix_index]
    )


async def async_input(prompt):
    """
    Python's ``input()`` is blocking, which means the event loop we set
    above can't be running while we're blocking there. This method will
    let the loop run while we wait for input.
    """
    print(prompt, end='', flush=True)
    return (await loop.run_in_executor(None, sys.stdin.readline)).rstrip()


class InteractiveTelegramClient(TelegramClient):


    def __init__(self, session_user_id, api_id, api_hash, proxy=None):
        """
        Initializes the InteractiveTelegramClient.
        :param session_user_id: Name of the *.session file.
        :param api_id: Telegram's api_id acquired through my.telegram.org.
        :param api_hash: Telegram's api_hash.
        :param proxy: Optional proxy tuple/dictionary.
        """
        print_title('Initialization')

        print('Initializing interactive example...')

        # The first step is to initialize the TelegramClient, as we are
        # subclassing it, we need to call super().__init__(). On a more
        # normal case you would want 'client = TelegramClient(...)'
        super().__init__(
            # These parameters should be passed always, session name and API
            session_user_id, api_id, api_hash,

            # You can optionally change the connection mode by passing a
            # type or an instance of it. This changes how the sent packets
            # look (low-level concept you normally shouldn't worry about).
            # Default is ConnectionTcpFull, smallest is ConnectionTcpAbridged.
            connection=ConnectionTcpAbridged,

            # If you're using a proxy, set it here.
            proxy=proxy
        )

        # Store {message.id: message} map here so that we can download
        # media known the message ID, for every message having media.
        self.found_media = {}

        # Calling .connect() may raise a connection error False, so you need
        # to except those before continuing. Otherwise you may want to retry
        # as done here.
        print('Connecting to Telegram servers...')
        try:
            loop.run_until_complete(self.connect())
        except IOError:
            # We handle IOError and not ConnectionError because
            # PySocks' errors do not subclass ConnectionError
            # (so this will work with and without proxies).
            print('Initial connection failed. Retrying...')
            loop.run_until_complete(self.connect())

        # If the user hasn't called .sign_in() or .sign_up() yet, they won't
        # be authorized. The first thing you must do is authorize. Calling
        # .sign_in() should only be done once as the information is saved on
        # the *.session file so you don't need to enter the code every time.
        if not loop.run_until_complete(self.is_user_authorized()):
            print('First run. Sending code request...')
            user_phone = input('Enter your phone: ')
            loop.run_until_complete(self.sign_in(user_phone))

            self_user = None
            while self_user is None:
                code = input('Enter the code you just received: ')
                try:
                    self_user =\
                        loop.run_until_complete(self.sign_in(code=code))

                # Two-step verification may be enabled, and .sign_in will
                # raise this error. If that's the case ask for the password.
                # Note that getpass() may not work on PyCharm due to a bug,
                # if that's the case simply change it for input().
                except SessionPasswordNeededError:
                    pw = getpass('Two step verification is enabled. '
                                 'Please enter your password: ')

                    self_user =\
                        loop.run_until_complete(self.sign_in(password=pw))

    async def run(self):
        """Main loop of the TelegramClient, will wait for user action"""

        # Once everything is ready, we can add an event handler.
        #
        # Events are an abstraction over Telegram's "Updates" and
        # are much easier to use.
        self.add_event_handler(self.message_handler, events.NewMessage)

        # Enter a while loop to chat as long as the user wants
        while True:
            i = None
            while i is None:
                print_title('Groups with Admin permissions')

                admin_groups = await self.list_groups()

                for i, admin_group in enumerate(admin_groups, start=1):
                    sprint('{}. {}'.format(i, admin_group.title))

                print()
                print('> Available commands:')
                print('  !q: Quits the dialogs window and exits.')
                print('  !l: Logs out, terminating this session.')
                print()
                i = await async_input('Enter dialog ID or a command: ')
                if i == '!q':
                    return
                if i == '!l':
                    # Logging out will cause the user to need to reenter the
                    # code next time they want to use the library, and will
                    # also delete the *.session file off the filesystem.
                    #
                    # This is not the same as simply calling .disconnect(),
                    # which simply shuts down everything gracefully.
                    await self.log_out()
                    return

                try:
                    i = int(i if i else 0) - 1
                    # Ensure it is inside the bounds, otherwise retry
                    if not 0 <= i < len(admin_groups):
                        i = None
                except ValueError:
                    i = None

            # Retrieve the selected user (or chat, or channel)
            entity = admin_groups[i]

            # Show some information
            print_title('Chat with "{}"'.format(entity.title))
            print('Available commands:')
            print('  !q:  Quits the current chat.')
            print('  !Q:  Quits the current chat and exits.')
            print('  !h:  prints the latest messages (message History).')
            print('  !i:  Prints information about this chat..')
            print('  !c:  clean deleted accounts')
            print('  !f:  list vanished users (180 days)')
            print()

            # And start a while loop to chat
            while True:
                msg = await async_input('Enter a message: ')
                # Quit
                if msg == '!q':
                    break
                elif msg == '!Q':
                    return
                elif msg == '!h':
                    await self.show_history(entity)
                elif msg == '!i':
                    attributes = list(entity.to_dict().items())
                    pad = max(len(x) for x, _ in attributes)
                    for name, val in attributes:
                        print("{:<{width}} : {}".format(name, val, width=pad))
                elif  msg ==  '!c':
                    await self.clean_users(entity)
                elif  msg ==  '!f':
                    await self.lost(entity)

                # Send chat message (if any)
                elif msg:
                    await self.send_message(entity, msg, link_preview=False)

    async def list_groups(self):
        chats = []
        last_date = None
        chunk_size = 200
        groups = []
        self.request = GetDialogsRequest(
             offset_date=last_date,
             offset_id=0,
             offset_peer=InputPeerEmpty(),
             limit=chunk_size,
             hash=0
        )
        result = await self(self.request)
        chats.extend(result.chats)
        for chat in chats:
            try:
                if chat.megagroup is True and  chat.admin_rights.ban_users is True:
                    groups.append(chat)
            except Exception:
                continue
        return groups

    async def show_history(self, entity):
        # First retrieve the messages and some information
        messages = await self.get_messages(entity, limit=10)

        # Iterate over all (in reverse order so the latest appear
        # the last in the console) and print them with format:
        # "[hh:mm] Sender: Message"
        for msg in reversed(messages):
            # Note how we access .sender here. Since we made an
            # API call using the self client, it will always have
            # information about the sender. This is different to
            # events, where Telegram may not always send the user.
            name = get_display_name(msg.sender)

            # Format the message content
            if getattr(msg, 'media', None):
                self.found_media[msg.id] = msg
                content = '<{}> {}'.format(
                    type(msg.media).__name__, msg.message)

            elif hasattr(msg, 'message'):
                content = msg.message
            elif hasattr(msg, 'action'):
                content = str(msg.action)
            else:
                # Unknown message, simply print its class name
                content = type(msg).__name__

            # And print it to the user
            sprint('[{}:{}] (ID={}) {}: {}'.format(
                msg.date.hour, msg.date.minute, msg.id, name, content))

    async def message_handler(self, event):
        pass
        """Callback method for received events.NewMessage"""

        # Note that message_handler is called when a Telegram update occurs
        # and an event is created. Telegram may not always send information
        # about the ``.sender`` or the ``.chat``, so if you *really* want it
        # you should use ``get_chat()`` and ``get_sender()`` while working
        # with events. Since they are methods, you know they may make an API
        # call, which can be expensive.
        # chat = await event.get_chat()
        # if event.is_group:
        #     if event.out:
        #         sprint('>> senta "{}" to chat {}'.format(
        #             event.text, get_display_name(chat)
        #         ))
        #     else:
        #         sprint('<< {} @ {} sente "{}"'.format(
        #             get_display_name(await event.get_sender()),
        #             get_display_name(chat),
        #             event.text
        #         ))
        # else:
        #     if event.out:
        #         sprint('>> "{}" to user {}'.format( event.text, get_display_name(chat) ))
        #     else:
        #         pass
        #         sprint('<< {} sent "{}"'.format( get_display_name(chat), event.text ))

    async def clean_users(self, group):
        print('Fetching Members...')
        deleted_accounts = 0
        async for participant in self.iter_participants(group):
            if participant.deleted:
                try:
                    deleted_accounts += 1
                    await self(EditBannedRequest(group, participant, ChatBannedRights(
                       until_date=datetime.timedelta(minutes=1),
                       view_messages=True
                       )))
                except Exception as exc:
                    deleted_accounts -= 1
                    print(f"Failed to remove one deleted account because: {str(exc)}")
        if deleted_accounts:
            print(f"Removed {deleted_accounts} Deleted Accounts")
        else:
            print(f"No deleted accounts found in {group}")

    async def lost(self, group):
        async for participant in self.iter_participants(group):
            if isinstance(participant.status , UserStatusOffline):
                dif = datetime.datetime.utcnow().replace(tzinfo=None) - participant.status.was_online.replace(tzinfo=None)
                if  dif > datetime.timedelta(days = 180):
                    print(participant.first_name," " ,participant.last_name)


if __name__ == '__main__':

    config = configparser.ConfigParser()
    config.read("config/config.ini")

    SESSION = os.environ.get('TG_SESSION', 'interactive')
    API_ID = int(config['Basic']['api_id'])
    API_HASH = config['Basic']['api_hash']

    client = InteractiveTelegramClient(SESSION, API_ID, API_HASH)
    loop.run_until_complete(client.run())
