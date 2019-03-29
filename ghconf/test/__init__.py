# -* encoding: utf-8 *-
from ghconf.base import GHConfModuleDef
from ghconf.utils import print_warning, ErrorMessage


class PrintTestWarningConfig(GHConfModuleDef):
    def __init__(self) -> None:
        super().__init__()
        print()
        print_warning("*" * 78)
        print_warning("{:^78}".format("Use ghconf.test.apply or ghconf.test.revert instead!"))
        print_warning("*" * 78)
        print()
        raise ErrorMessage("")


entry_point = PrintTestWarningConfig
