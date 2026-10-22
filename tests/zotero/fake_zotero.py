"""造一个最小的 Zotero 数据目录：zotero.sqlite（只建用到的表）+ storage/ 里的 PDF。"""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
CREATE TABLE items (itemID INTEGER PRIMARY KEY, itemTypeID INT, dateAdded TEXT, libraryID INT, key TEXT);
CREATE TABLE fieldsCombined (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value);
CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT);
CREATE TABLE creatorTypes (creatorTypeID INTEGER PRIMARY KEY, creatorType TEXT);
CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT, fieldMode INT);
CREATE TABLE itemCreators (itemID INT, creatorID INT, creatorTypeID INT, orderIndex INT);
CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, collectionName TEXT, parentCollectionID INT, libraryID INT);
CREATE TABLE collectionItems (collectionID INT, itemID INT);
CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE itemTags (itemID INT, tagID INT, type INT);
CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INT, linkMode INT, contentType TEXT, path TEXT);
CREATE TABLE deletedItems (itemID INTEGER PRIMARY KEY);
CREATE TABLE deletedCollections (collectionID INTEGER PRIMARY KEY);
CREATE TABLE groups (groupID INTEGER PRIMARY KEY, libraryID INT, name TEXT);
"""
TYPES = ["journalArticle", "preprint", "attachment", "note", "book"]
FIELDS = ["title", "date", "publicationTitle", "DOI", "url", "abstractNote", "archiveID", "repository"]


def pdf_bytes(text: str) -> bytes:
    return b"%PDF-1.4\n% " + text.encode() + b"\n%%EOF\n"


class FakeZotero:
    def __init__(self, root: Path):
        self.root = Path(root)
        (self.root / "storage").mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.root / "zotero.sqlite")
        self.con.executescript(SCHEMA)
        self.con.executemany("INSERT INTO itemTypes VALUES (?, ?)", list(enumerate(TYPES, 1)))
        self.con.executemany("INSERT INTO fieldsCombined VALUES (?, ?)", list(enumerate(FIELDS, 1)))
        self.con.executemany("INSERT INTO creatorTypes VALUES (?, ?)", [(1, "author"), (2, "editor")])
        self.n = 0

    def _id(self) -> int:
        self.n += 1
        return self.n

    def item(self, kind="journalArticle", added="2023-01-02 03:04:05", lib=1, **fields) -> int:
        iid = self._id()
        self.con.execute("INSERT INTO items VALUES (?, ?, ?, ?, ?)", (iid, TYPES.index(kind) + 1, added, lib, f"KEY{iid:05d}"))
        for name, value in fields.items():
            vid = self._id()
            self.con.execute("INSERT INTO itemDataValues VALUES (?, ?)", (vid, value))
            self.con.execute("INSERT INTO itemData VALUES (?, ?, ?)", (iid, FIELDS.index(name) + 1, vid))
        return iid

    def author(self, iid, first, last, order=0, single=False, kind=1):
        cid = self._id()
        self.con.execute("INSERT INTO creators VALUES (?, ?, ?, ?)", (cid, first, last, 1 if single else 0))
        self.con.execute("INSERT INTO itemCreators VALUES (?, ?, ?, ?)", (iid, cid, kind, order))

    def pdf(self, parent, text="paper", added="2023-01-02 03:04:06", name="paper.pdf") -> int:
        aid = self.item("attachment", added=added)
        key = f"KEY{aid:05d}"
        (self.root / "storage" / key).mkdir()
        (self.root / "storage" / key / name).write_bytes(pdf_bytes(text))
        self.con.execute("INSERT INTO itemAttachments VALUES (?, ?, 0, 'application/pdf', ?)", (aid, parent, "storage:" + name))
        return aid

    def collection(self, name, parent=None, lib=1) -> int:
        cid = self._id()
        self.con.execute("INSERT INTO collections VALUES (?, ?, ?, ?)", (cid, name, parent, lib))
        return cid

    def put(self, cid, iid):
        self.con.execute("INSERT INTO collectionItems VALUES (?, ?)", (cid, iid))

    def tag(self, iid, name, auto=False):
        tid = self._id()
        self.con.execute("INSERT INTO tags VALUES (?, ?)", (tid, name))
        self.con.execute("INSERT INTO itemTags VALUES (?, ?, ?)", (iid, tid, 1 if auto else 0))

    def trash(self, iid):
        self.con.execute("INSERT INTO deletedItems VALUES (?)", (iid,))

    def group(self, lib, name):
        self.con.execute("INSERT INTO groups VALUES (?, ?, ?)", (self._id(), lib, name))

    def close(self):
        if self.con:
            self.con.commit()
            self.con.close()
            self.con = None
