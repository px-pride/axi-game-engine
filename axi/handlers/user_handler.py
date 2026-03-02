from discord.utils import get
from axi.axi_user import AxiUser

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
    display_name = str(uid).split("#")[0]
    mention_str = str(uid.mention)
    users[uid] = AxiUser(uid.id, display_name, mention_str)
    return users[uid]
