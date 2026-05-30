import hashlib

DEFAULT_ROOT_PASSWORD = "123456"


def md5(text: str):
    m = hashlib.md5()
    m.update(text.encode("utf-8"))
    return m.hexdigest()


class User:
    def __init__(self, name, password, user_id, home_path=None):
        self._name = name
        self._password = md5(password)
        self._user_id = user_id
        self._home_path = home_path

    @property
    def user_id(self):
        return self._user_id

    @property
    def name(self):
        return self._name

    @property
    def home_path(self):
        return self._home_path

    def verify_password(self, password):
        return md5(password) == self._password

    def set_password(self, password):
        self._password = md5(password)

    def login(self, name, password):
        return name == self._name and self.verify_password(password)

    def __str__(self):
        return f"{self.name} {self.user_id} {self.home_path or ''} {self._password}"


def create_root_user():
    return User("root", DEFAULT_ROOT_PASSWORD, 0, "/root")
