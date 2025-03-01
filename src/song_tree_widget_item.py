# This Python file uses the following encoding: utf-8
from PySide6.QtCore import QFileInfo
from PySide6.QtGui import QStandardItem

import logging
import os
import datetime
from template import SettingTemplate

from const import *
from settings import get_setting
from metadata import Metadata

logger = logging.getLogger(APPLICATION)


class TreeWidgetItemData:
    def __init__(self, item_type, songs=None, **kwargs):

        # metadata values
        self.metadata = None

        # application values
        # always strings
        self.dict = {}
        app_fields = SONG_FIELDS if item_type == TreeWidgetType.SONG else ALBUM_FIELDS
        for field in (set(kwargs.keys()) | app_fields):
            # set all mandatory settings to their defaults if not
            # specified in the parameters
            # and any extra settings specified in the parameters
            if field in kwargs:
                self.dict[field] = kwargs[field]
            else:
                # set to default setting
                self.dict[field] = get_setting(field)

            if field == 'coverArt' and self.dict[field] in QRC_TO_FILE_PATH:
                # convert resource path to real file path for ffmpeg
                self.dict[field] = QRC_TO_FILE_PATH[get_setting(field)]

        # add song metadata
        if item_type == TreeWidgetType.SONG:
            try:
                self.metadata = Metadata(self.dict['song_path'])

                cover_exts = {'.jpg', '.jpeg', '.bmp', '.gif', '.png'}
                cover_names = {'cover', 'folder', 'front', os.path.splitext(self.dict['song_file'])[0]}
                cover_file = None
                for file in os.listdir(self.dict['song_dir']):
                    path = os.path.join(self.dict['song_dir'], file)
                    name, ext = os.path.splitext(file)
                    if os.path.isfile(path) and name.lower() in cover_names and ext.lower() in cover_exts:
                        logger.info(f"Found cover file {path}")
                        cover_file = path
                        break

                if get_setting('preferCoverArtFile') == SETTINGS_VALUES.CheckBox.CHECKED and cover_file:
                        self.set_value('coverArt', cover_file)
                elif get_setting('extractCoverArt') == SETTINGS_VALUES.CheckBox.CHECKED:
                    if (cover_path := self.metadata.get_cover_art()) is not None:
                        self.set_value('coverArt', cover_path)
                    elif cover_file:
                        self.set_value('coverArt', cover_file)


            except Exception as e:
                logger.warning("Error while getting cover art")
                logger.warning(e)
                logger.warning(self.dict['song_path'])
        else:
            # album gets metadata from children
            # song metadata is stored as song.<key>
            # e.g. song.album would be the album name
            #
            # we will only get metadata from one song
            # because the album shouldn't care about
            # the varying metadata values for the songs
            # such as title or track number
            for song in songs:
                for key, value in song.to_dict().items():
                    key = "song.{}".format(key)
                    self.dict[key] = value
                break

        self.update_fields()

    def update_fields(self):
        for field, value in self.dict.items():
            self.set_value(field, value)

    def to_dict(self):
        dict = {**self.dict, **(self.metadata.get_tags() if self.metadata is not None else {})}
        return dict

    def get_value(self, field):
        return self.dict[field]

    def get_metadata_value(self, key):
        if key in self.metadata.get_tags():
            return self.metadata.get_tags()[key]
        return None

    def set_value(self, field, value):
        # replace {variable} with value from metadata
        value = SettingTemplate(value).safe_substitute(**self.to_dict())
        self.dict[field] = value

    def get_duration_ms(self):
        if 'length' in self.metadata.get_tags():
            return float(self.metadata.get_tags()['length']) * 1000
        else:
            logger.error("Could not find duration of file {}".format(self.dict['song_path']))
            logger.debug(self.metadata.get_tags())
            return 999999999

    def get_track_number(self):
        if 'tracknumber' in self.metadata.get_tags():
            try:
                tracknumber = self.metadata.get_tags()['tracknumber']
                if "/" in tracknumber:
                    # sometimes track number is represented as a fraction
                    tracknumber = tracknumber[:tracknumber.index("/")]
                return int(tracknumber)
            except:
                logger.warning("Could not convert {} to int".format(self.metadata.get_tags()['tracknumber']))
                return 0
        return 0

    def __str__(self):
        return str(self.dict)


class SongTreeWidgetItem(QStandardItem):
    def __init__(self, file_path, *args):
        super().__init__(*args)
        self.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled
                      | Qt.ItemIsDragEnabled)
        self.setData(TreeWidgetType.SONG, CustomDataRole.ITEMTYPE)
        info = QFileInfo(file_path)
        self.setData(TreeWidgetItemData(
                        TreeWidgetType.SONG,
                        song_path=file_path,
                        song_dir=info.path(),
                        song_file=info.fileName()),
                     CustomDataRole.ITEMDATA)

    def get(self, field):
        return self.data(CustomDataRole.ITEMDATA).get_value(field)

    def set(self, field, value):
        self.data(CustomDataRole.ITEMDATA).set_value(field, value)

    def to_dict(self):
        return self.data(CustomDataRole.ITEMDATA).to_dict()

    def item_type(self):
        return self.data(CustomDataRole.ITEMTYPE)

    def get_duration_ms(self):
        return self.data(CustomDataRole.ITEMDATA).get_duration_ms()

    def before_render(self):
        self.set("fileOutput", os.path.join(self.get("fileOutputDir"), self.get("fileOutputName")))
        self.set("songDuration", str(self.get_duration_ms() / 1000))
        command_path = os.path.join(os.path.dirname(__file__), "commands", "render", self.get("commandName") + ".command")
        try:
            with open(command_path, 'r') as f:
                command = f.read().strip()
                self.set("commandString", command)
        except:
            raise Exception(f"Could not read command from {command_path}")

    def before_upload(self):
        pass

    def get_track_number(self):
        return self.data(CustomDataRole.ITEMDATA).get_track_number()

    @classmethod
    def from_standard_item(cls, item: QStandardItem):
        for name, value in cls.__dict__.items():
            if callable(value) and name != '__init__':
                bound = value.__get__(item)
                setattr(item, name, bound)
        return item



class AlbumTreeWidgetItem(QStandardItem):
    def __init__(self, dir_path, songs, *args):
        super().__init__(*args)
        self.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled
                      | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
        self.setData(TreeWidgetType.ALBUM, CustomDataRole.ITEMTYPE)

        # order songs by tracknumber if possible
        songs.sort(key=lambda song: song.get_track_number())

        self.setData(TreeWidgetItemData(
                        TreeWidgetType.ALBUM,
                        songs,
                        album_dir=dir_path
                    ), CustomDataRole.ITEMDATA)

        for song in songs:
            self.addChild(song)

    def get(self, field):
        return self.data(CustomDataRole.ITEMDATA).get_value(field)

    def set(self, field, value):
        self.data(CustomDataRole.ITEMDATA).set_value(field, value)

    def item_type(self):
        return self.data(CustomDataRole.ITEMTYPE)

    def addChild(self, item):
        self.appendRow(item)

    def childCount(self):
        return self.rowCount()

    def getChildren(self):
        for i in range(self.childCount()):
            yield SongTreeWidgetItem.from_standard_item(self.child(i))

    @staticmethod
    def getChildrenFromStandardItem(item: QStandardItem):
        for i in range(item.rowCount()):
            yield item.child(i)

    @classmethod
    def from_standard_item(cls, item: QStandardItem):
        for name, value in cls.__dict__.items():
            if callable(value) and name != '__init__':
                bound = value.__get__(item)
                setattr(item, name, bound)
        return item

    def get_duration_ms(self):
        return sum(song.get_duration_ms() for song in self.getChildren())

    def before_render(self):
        self.data(CustomDataRole.ITEMDATA).set_value("albumDuration", str(self.get_duration_ms() / 1000))
        self.data(CustomDataRole.ITEMDATA).set_value("fileOutput", os.path.join(self.get("fileOutputDirAlbum"), self.get("fileOutputNameAlbum")))
        command_path = os.path.join(os.path.dirname(__file__), "commands", "concat", self.get("concatCommandName") + ".command")
        try:
            with open(command_path, 'r') as f:
                command = f.read().strip()
                self.set("concatCommandString", command)
        except:
            raise Exception(f"Could not read command from {command_path}")

    def before_upload(self):
        # generate timestamps
        data = self.data(CustomDataRole.ITEMDATA)
        timestamp = 0
        timestamp_str = ""
        for song in self.getChildren():
            format_string = get_setting("timestampFormat")
            # create h/m/s keys
            hours, minutes, seconds = int(timestamp // 3600), int((timestamp // 60) % 60), int(timestamp) % 60
            song.set(r"%H", str(hours))
            song.set(r"%M", str(minutes))
            song.set(r"%S", str(seconds))
            song.set(r"%0H", f"{hours:02}")
            song.set(r"%0M", f"{minutes:02}")
            song.set(r"%0S", f"{seconds:02}")
            song.set("timestamp", format_string)
            timestamp_str += song.get("timestamp") + '\n'
            timestamp += song.get_duration_ms() / 1000
        data.set_value("timestamps", timestamp_str)
        data.update_fields()

