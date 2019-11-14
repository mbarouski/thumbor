#!/usr/bin/python
# -*- coding: utf-8 -*-

# thumbor imaging service
# https://github.com/thumbor/thumbor/wiki

# Licensed under the MIT license:
# http://www.opensource.org/licenses/mit-license
# Copyright (c) 2011 globo.com thumbor@googlegroups.com

from datetime import datetime
from uuid import uuid4
from shutil import move
import pytz
import hashlib

from os.path import exists, dirname, join, getmtime, abspath, isdir, isfile

from thumbor.engines import BaseEngine
from thumbor.result_storages import BaseStorage
from thumbor.utils import logger, deprecated
from tornado.concurrent import return_future
from six.moves.urllib.parse import unquote
from . import ResultStorageResult


class Storage(BaseStorage):
    PATH_FORMAT_VERSION = 'v2'

    @property
    def is_auto_webp(self):
        return self.context.config.AUTO_WEBP and self.context.request.accepts_webp

    def put(self, bytes):
        file_abspath = self.normalize_path(self.context.request.url)
        if not self.validate_path(file_abspath):
            logger.warn("[RESULT_STORAGE] unable to write outside root path: %s" % file_abspath)
            return
        temp_abspath = "%s.%s" % (file_abspath, str(uuid4()).replace('-', ''))
        file_dir_abspath = dirname(file_abspath)
        logger.debug("[RESULT_STORAGE] putting at %s (%s)" % (file_abspath, file_dir_abspath))

        self.ensure_dir(file_dir_abspath)

        with open(temp_abspath, 'wb') as _file:
            _file.write(bytes)

        move(temp_abspath, file_abspath)

    @return_future
    def get(self, callback):
        path = self.context.request.url
        file_abspath = self.normalize_path(path)

        if not self.validate_path(file_abspath):
            logger.warn("[RESULT_STORAGE] unable to read from outside root path: %s" % file_abspath)
            return callback(None)

        logger.debug("[RESULT_STORAGE] getting from %s" % file_abspath)

        if isdir(file_abspath):
            logger.warn("[RESULT_STORAGE] cache location is a directory: %s" % file_abspath)
            return callback(None)

        if not exists(file_abspath):
            legacy_path = self.normalize_path_legacy(path)
            if isfile(legacy_path):
                logger.debug("[RESULT_STORAGE] migrating image from old location at %s" % legacy_path)
                self.ensure_dir(dirname(file_abspath))
                move(legacy_path, file_abspath)
            else:
                logger.debug("[RESULT_STORAGE] image not found at %s" % file_abspath)
                return callback(None)

        if self.is_expired(file_abspath):
            logger.debug("[RESULT_STORAGE] cached image has expired")
            return callback(None)

        with open(file_abspath, 'rb') as f:
            buffer = f.read()

        result = ResultStorageResult(
            buffer=buffer,
            metadata={
                'LastModified': datetime.fromtimestamp(getmtime(file_abspath)).replace(tzinfo=pytz.utc),
                'ContentLength': len(buffer),
                'ContentType': BaseEngine.get_mimetype(buffer)
            }
        )

        callback(result)

    def validate_path(self, path):
        return abspath(path).startswith(self.context.config.RESULT_STORAGE_FILE_STORAGE_ROOT_PATH)

    def normalize_path(self, path):
        digest = hashlib.sha1(unquote(path).encode('utf-8')).hexdigest()

        return "%s/%s/%s/%s/%s" % (
            self.context.config.RESULT_STORAGE_FILE_STORAGE_ROOT_PATH.rstrip('/'),
            'auto_webp' if self.is_auto_webp else 'default',
            digest[:2],
            digest[2:4],
            digest[4:]
        )

    def normalize_path_legacy(self, path):
        path = unquote(path)
        path_segments = [self.context.config.RESULT_STORAGE_FILE_STORAGE_ROOT_PATH.rstrip('/'), Storage.PATH_FORMAT_VERSION, ]
        if self.is_auto_webp:
            path_segments.append("webp")

        path_segments.extend([self.partition(path), path.lstrip('/'), ])

        normalized_path = join(*path_segments).replace('http://', '')
        return normalized_path

    def partition(self, path_raw):
        path = path_raw.lstrip('/')
        return join("".join(path[0:2]), "".join(path[2:4]))

    def is_expired(self, path):
        expire_in_seconds = self.context.config.get('RESULT_STORAGE_EXPIRATION_SECONDS', None)

        if expire_in_seconds is None or expire_in_seconds == 0:
            return False

        timediff = datetime.now() - datetime.fromtimestamp(getmtime(path))
        return timediff.total_seconds() > expire_in_seconds

    @deprecated("Use result's last_modified instead")
    def last_updated(self):
        path = self.context.request.url
        file_abspath = self.normalize_path(path)
        if not self.validate_path(file_abspath):
            logger.warn("[RESULT_STORAGE] unable to read from outside root path: %s" % file_abspath)
            return True
        logger.debug("[RESULT_STORAGE] getting from %s" % file_abspath)

        if not exists(file_abspath) or self.is_expired(file_abspath):
            logger.debug("[RESULT_STORAGE] image not found at %s" % file_abspath)
            return True

        return datetime.fromtimestamp(getmtime(file_abspath)).replace(tzinfo=pytz.utc)
