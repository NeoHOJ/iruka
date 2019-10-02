class Config(object):
    def __init__(self):
        self.server = None
        self.auth_token = None

    def load_from_dict(self, config_dict):
        self.__dict__.update(config_dict)
