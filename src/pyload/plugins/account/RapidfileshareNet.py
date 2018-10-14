# -*- coding: utf-8 -*-

from pyload.plugins.internal.xfsaccount import XFSAccount


class RapidfileshareNet(XFSAccount):
    __name__ = "RapidfileshareNet"
    __type__ = "account"
    __version__ = "0.11"
    __pyload_version__ = "0.5"
    __status__ = "testing"

    __description__ = """Rapidfileshare.net account plugin"""
    __license__ = "GPLv3"
    __authors__ = [("guidobelix", "guidobelix@hotmail.it")]

    PLUGIN_DOMAIN = "rapidfileshare.net"

    TRAFFIC_LEFT_PATTERN = r'>Traffic available today:</TD><TD><label for="name">\s*(?P<S>[\d.,]+)\s*(?:(?P<U>[\w^_]+))?'