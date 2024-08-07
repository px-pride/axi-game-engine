from discord.abc import User
from discord.utils import get

users = dict()

def get_user(guild, uid):
    if isinstance(uid, str):
        if uid.startswith("<@") and uid.endswith(">"):
            id_num = int(uid[2:-1])
            uid = get(guild.members, id=id_num)
        else:
            return None
    if not uid:
        return None
    if uid in users:
        return users[uid]
    users[uid] = AxiUser(uid)
    return users[uid]


class AxiUser:
    # Wraps strings and Discord members.

    def __init__(self, uid):
        if not isinstance(uid, User):
            raise ValueError("User UID must be Discord user.")
        self.uid = uid

    def send(self, x, file=None):
        return self.uid.send(x, file=file)

    def parse(self, mention=False):
        if mention:
            return str(self.uid.mention)
        #if self.uid.nick is not None:
        #    return self.uid.nick
        return str(self.uid).split("#")[0]

    def __str__(self):
        return self.parse()

    def __repr__(self):
        return self.parse()

