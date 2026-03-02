class AxiUser:
    def __init__(self, uid_id, display_name, mention_str=None):
        self.uid = type('Uid', (), {'id': uid_id})()
        self._display_name = display_name
        self._mention = mention_str or display_name

    def parse(self, mention=False):
        return self._mention if mention else self._display_name

    def __str__(self):
        return self.parse()

    def __repr__(self):
        return self.parse()
