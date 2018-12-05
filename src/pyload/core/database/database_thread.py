# -*- coding: utf-8 -*-
# AUTHOR: RaNaN, mkaay

import inspect
import os
import shutil
import sqlite3
from builtins import object, range, str
from queue import Queue
from threading import Event, Thread
from contextlib import closing

from ... import exc_logger

# DATABASE VERSION
__version__ = 4


class style(object):
    db = None

    @classmethod
    def setDB(cls, db):
        cls.db = db

    @classmethod
    def inner(cls, fn):
        @staticmethod
        def x(*args, **kwargs):
            return fn(cls.db, *args, **kwargs)

        return x

    @classmethod
    def queue(cls, fn):
        @staticmethod
        def x(*args, **kwargs):
            return cls.db.queue(fn, *args, **kwargs)

        return x

    @classmethod
    def async_(cls, fn):
        @staticmethod
        def x(*args, **kwargs):
            return cls.db.async_(fn, *args, **kwargs)

        return x


class DatabaseJob(object):
    def __init__(self, f, *args, **kwargs):
        self.done = Event()

        self.f = f
        self.args = args
        self.kwargs = kwargs

        self.result = None
        self.exception = False

        self.frame = inspect.currentframe()

    def __repr__(self):

        frame = self.frame.f_back
        output = ""
        for i in range(5):
            output += "\t{}:{}, {}\n".format(
                os.path.basename(frame.f_code.co_filename),
                frame.f_lineno,
                frame.f_code.co_name,
            )
            frame = frame.f_back
        del frame
        del self.frame

        return "DataBase Job {}:{}\n{}Result: {}".format(
            self.f.__name__, self.args[1:], output, self.result
        )

    def processJob(self):
        try:
            self.result = self.f(*self.args, **self.kwargs)
        except Exception as exc:
            exc_logger.exception("Database Error @", self.f.__name__, self.args[1:], self.kwargs, exc)
            self.exception = exc
        finally:
            self.done.set()

    def wait(self):
        self.done.wait()


class DatabaseThread(Thread):

    subs = []

    DB_FILENAME = "pyload.db"
    VERSION_FILENAME = "db.version"

    def __init__(self, core):
        super().__init__()
        self.daemon = True
        self.pyload = core
        self._ = core._

        datadir = os.path.join(self.pyload.userdir, "data")
        os.makedirs(datadir, exist_ok=True)
        
        self.db_path = os.path.join(datadir, self.DB_FILENAME)
        self.version_path = os.path.join(datadir, self.VERSION_FILENAME)

        self.jobs = Queue()

        self.setuplock = Event()

        style.setDB(self)

    def setup(self):
        self.start()
        self.setuplock.wait()

    def run(self):
        """
        main loop, which executes commands.
        """
        convert = self._checkVersion()  #: returns None or current version

        self.conn = sqlite3.connect(self.db_path, isolation_level=None)
        os.chmod(self.db_path, 0o600)

        self.c = self.conn.cursor()  #: compatibility

        if convert is not None:
            self._convertDB(convert)

        self._createTables()
        self._migrateUser()

        self.conn.commit()

        self.setuplock.set()

        while True:
            j = self.jobs.get()
            if j == "quit":
                self.c.close()
                self.conn.close()
                break
            j.processJob()

    @style.queue
    def shutdown(self):
        self.conn.commit()
        self.jobs.put("quit")

    def _checkVersion(self):
        """
        check db version and delete it if needed.
        """
        if not os.path.exists(self.version_path):
            with open(self.version_path, mode="w") as f:
                f.write(str(__version__))
            return

        with open(self.version_path) as f:
            v = int(f.read().strip())

        if v < __version__:
            if v < 2:
                self.pyload.log.warning(
                        self._("Filedatabase was deleted due to incompatible version.")
                    )
                os.remove(self.version_path)
                shutil.move(self.db_path, "files.backup.db")
            with open(self.version_path, mode="w") as f:
                f.write(str(__version__))
            return v

    def _convertDB(self, v):
        try:
            getattr(self, "_convertV{}".format(v))()
        except Exception:
            self.pyload.log.error(self._("Filedatabase could NOT be converted."))

    # --convert scripts start

    def _convertV2(self):
        self.c.execute(
            'CREATE TABLE IF NOT EXISTS "storage" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "identifier" TEXT NOT NULL, "key" TEXT NOT NULL, "value" TEXT DEFAULT "")'
        )
        self.pyload.log.info(self._("Database was converted from v2 to v3."))
        self._convertV3()

    def _convertV3(self):
        self.c.execute(
            'CREATE TABLE IF NOT EXISTS "users" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "name" TEXT NOT NULL, "email" TEXT DEFAULT "" NOT NULL, "password" TEXT NOT NULL, "role" INTEGER DEFAULT 0 NOT NULL, "permission" INTEGER DEFAULT 0 NOT NULL, "template" TEXT DEFAULT "default" NOT NULL)'
        )
        self.pyload.log.info(self._("Database was converted from v3 to v4."))

    # --convert scripts end

    def _createTables(self):
        """
        create tables for database.
        """

        self.c.execute(
            'CREATE TABLE IF NOT EXISTS "packages" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "name" TEXT NOT NULL, "folder" TEXT, "password" TEXT DEFAULT "", "site" TEXT DEFAULT "", "queue" INTEGER DEFAULT 0 NOT NULL, "packageorder" INTEGER DEFAULT 0 NOT NULL)'
        )
        self.c.execute(
            'CREATE TABLE IF NOT EXISTS "links" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "url" TEXT NOT NULL, "name" TEXT, "size" INTEGER DEFAULT 0 NOT NULL, "status" INTEGER DEFAULT 3 NOT NULL, "plugin" TEXT DEFAULT "BasePlugin" NOT NULL, "error" TEXT DEFAULT "", "linkorder" INTEGER DEFAULT 0 NOT NULL, "package" INTEGER DEFAULT 0 NOT NULL, FOREIGN KEY(package) REFERENCES packages(id))'
        )
        self.c.execute('CREATE INDEX IF NOT EXISTS "pIdIndex" ON links(package)')
        self.c.execute(
            'CREATE TABLE IF NOT EXISTS "storage" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "identifier" TEXT NOT NULL, "key" TEXT NOT NULL, "value" TEXT DEFAULT "")'
        )
        self.c.execute(
            'CREATE TABLE IF NOT EXISTS "users" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "name" TEXT NOT NULL, "email" TEXT DEFAULT "" NOT NULL, "password" TEXT NOT NULL, "role" INTEGER DEFAULT 0 NOT NULL, "permission" INTEGER DEFAULT 0 NOT NULL, "template" TEXT DEFAULT "default" NOT NULL)'
        )

        self.c.execute(
            'CREATE VIEW IF NOT EXISTS "pstats" AS \
        SELECT p.id AS id, SUM(l.size) AS sizetotal, COUNT(l.id) AS linkstotal, linksdone, sizedone\
        FROM packages p JOIN links l ON p.id = l.package LEFT OUTER JOIN\
        (SELECT p.id AS id, COUNT(*) AS linksdone, SUM(l.size) AS sizedone \
        FROM packages p JOIN links l ON p.id = l.package AND l.status in (0,4,13) GROUP BY p.id) s ON s.id = p.id \
        GROUP BY p.id'
        )

        # try to lower ids
        self.c.execute("SELECT max(id) FROM LINKS")
        fid = self.c.fetchone()[0]
        if fid:
            fid = int(fid)
        else:
            fid = 0
        self.c.execute("UPDATE SQLITE_SEQUENCE SET seq=? WHERE name=?", (fid, "links"))

        self.c.execute("SELECT max(id) FROM packages")
        pid = self.c.fetchone()[0]
        if pid:
            pid = int(pid)
        else:
            pid = 0
        self.c.execute(
            "UPDATE SQLITE_SEQUENCE SET seq=? WHERE name=?", (pid, "packages")
        )

        self.c.execute("VACUUM")

    def _migrateUser(self):
        if os.path.exists("pyload.db"):
            self.pyload.log.info(self._("Converting old Django DB"))
            
            with sqlite3.connect("pyload.db", isolation_level=None) as conn:
                with closing(conn.cursor()) as c:
                    c.execute(
                        "SELECT username, password, email from auth_user WHERE is_superuser"
                    )
                    users = []
                    for r in c:
                        pw = r[1].split("$")
                        users.append((r[0], pw[1] + pw[2], r[2]))

            self.c.executemany(
                "INSERT INTO users(name, password, email) VALUES (?, ?, ?)", users
            )
            shutil.move("pyload.db", "pyload.old.db")

    def createCursor(self):
        return self.conn.cursor()

    @style.async_
    def commit(self):
        self.conn.commit()

    @style.queue
    def syncSave(self):
        self.conn.commit()

    @style.async_
    def rollback(self):
        self.conn.rollback()

    def async_(self, f, *args, **kwargs):
        args = (self,) + args
        job = DatabaseJob(f, *args, **kwargs)
        self.jobs.put(job)

    def queue(self, f, *args, **kwargs):
        args = (self,) + args
        job = DatabaseJob(f, *args, **kwargs)
        self.jobs.put(job)
        job.wait()
        return job.result

    @classmethod
    def registerSub(cls, klass):
        cls.subs.append(klass)

    @classmethod
    def unregisterSub(cls, klass):
        cls.subs.remove(klass)

    def __getattr__(self, attr):
        for sub in DatabaseThread.subs:
            if hasattr(sub, attr):
                return getattr(sub, attr)
