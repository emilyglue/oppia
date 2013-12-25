# coding: utf-8
#
# Copyright 2013 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Model for an Oppia exploration."""

__author__ = 'Sean Lip'

import core.storage.base_model.gae_models as base_models
import feconf

from google.appengine.ext import ndb


QUERY_LIMIT = 100


class ExplorationModel(base_models.BaseModel):
    """Storage model for the Oppia exploration at HEAD.

    Previous versions of this exploration are stored, in serialized form, using
    ExplorationSnapshotModels.

    This class should only be imported by the exploration domain file, the
    exploration services file, and the Exploration model test file.
    """
    # TODO(sll): Write a test that ensures that the only files that are
    # allowed to import this class are the ones described above.

    # The current version number of this exploration. In each PUT operation,
    # this number is incremented and a snapshot of the modified exploration is
    # stored as an ExplorationSnapshotModel. The snapshot version number starts
    # at 1.
    version = ndb.IntegerProperty(default=0)

    # What this exploration is called.
    title = ndb.StringProperty(required=True)
    # The category this exploration belongs to.
    category = ndb.StringProperty(required=True, indexed=True)

    # The name of the initial state of this exploration.
    init_state_name = ndb.StringProperty(required=True, indexed=False)
    # A dict representing the states of this exploration. This dict should
    # not be empty.
    states = ndb.JsonProperty(default={}, indexed=False)
    # The dict of parameter specifications associated with this exploration.
    # Each specification is a dict whose keys are param names and whose values
    # are each dicts with a single key, 'obj_type', whose value is a string.
    param_specs = ndb.JsonProperty(default={}, indexed=False)
    # The list of parameter changes to be performed once at the start of a
    # reader's encounter with an exploration.
    param_changes = ndb.JsonProperty(repeated=True, indexed=False)
    # The default HTML template to use for displaying the exploration to the
    # reader. This is a filename in data/skins (without the .html suffix).
    default_skin = ndb.StringProperty(default='conversation_v1')

    @classmethod
    def get_public_explorations(cls):
        """Returns an iterable containing publicly-available explorations."""
        qo = ndb.QueryOptions(keys_only=True)
        exp_rights_keys = ExplorationRightsModel.query().filter(
            ExplorationRightsModel.status == 'public'
        ).fetch(QUERY_LIMIT, options=qo)

        exploration_keys = [
            ndb.Key(cls, exp_rights_key.id())
            for exp_rights_key in exp_rights_keys]
        return ndb.get_multi(exploration_keys)

    @classmethod
    def get_exploration_count(cls):
        """Returns the total number of explorations."""
        return cls.get_all().count()

    def put(self, committer_id, properties_dict, snapshot=None,
            commit_message=''):
        """Updates the exploration using the properties dict, then saves it.

        If snapshot is not None, increments the exploration version and saves
        a serialized copy or a diff in the history log.
        """
        if not isinstance(committer_id, basestring):
            raise Exception('Invalid committer id: %s' % committer_id)

        if properties_dict is None:
            properties_dict = {}

        # In NDB, self._properties returns the list of ndb properties of a
        # model.
        for key in properties_dict:
            if key in self._properties:
                setattr(self, key, properties_dict[key])
            else:
                raise Exception(
                    'Invalid key for exploration properties dict: %s' % key)

        if snapshot and snapshot != feconf.NULL_SNAPSHOT:
            self.version += 1
            ExplorationSnapshotModel.save_snapshot(
                self.id, self.version, committer_id,
                ExplorationSnapshotContentModel.FORMAT_TYPE_FULL,
                snapshot, commit_message)

        super(ExplorationModel, self).put()


class ExplorationSnapshotModel(base_models.BaseModel):
    """Storage model for an Oppia exploration snapshot."""

    @classmethod
    def _get_snapshot_id(cls, exploration_id, version_number):
        return '%s-%s' % (exploration_id, version_number)

    @property
    def exploration_id(self):
        return self.id.split('-')[0]

    @property
    def version_number(self):
        return self.id.split('-')[1]

    # The id of the user who committed this revision.
    committer_id = ndb.StringProperty(required=True)
    # A brief commit message.
    # TODO(sll): Make this a required property?
    commit_message = ndb.TextProperty(indexed=False)

    @classmethod
    def get_metadata(cls, exploration_id, version_number):
        """Returns a dict representing an exploration snapshot."""
        snapshot_id = cls._get_snapshot_id(exploration_id, version_number)

        snapshot = cls.get(snapshot_id)
        # TODO(sll): Do a projection query so that the serialized exploration
        # or the diff are only fetched on demand from the datastore.
        return {
            'committer_id': snapshot.committer_id,
            'commit_message': snapshot.commit_message,
            'created_on': snapshot.created_on.strftime(
                feconf.HUMAN_READABLE_DATETIME_FORMAT),
            'version_number': version_number,
        }

    @classmethod
    def save_snapshot(cls, exploration_id, version_number, committer_id,
                      snapshot_format, json_blob, commit_message):
        """Saves a new snapshot for the given exploration."""

        if not isinstance(version_number, int) or version_number < 0:
            raise Exception('Invalid version number: %s' % version_number)

        snapshot_id = cls._get_snapshot_id(exploration_id, version_number)

        # Ensure that this id has not been used.
        if cls.get(snapshot_id, strict=False) is not None:
            raise Exception(
                'Snapshot with exploration id %s and version number %s '
                'already exists' % (exploration_id, version_number))

        # Save the snapshot content.
        ExplorationSnapshotContentModel.save_snapshot_content(
            snapshot_id, snapshot_format, json_blob)

        snapshot_model = cls(id=snapshot_id, committer_id=committer_id,
                             commit_message=commit_message)
        snapshot_model.put()


class ExplorationSnapshotContentModel(base_models.BaseModel):
    """Storage model for the content of an exploration snapshot."""

    @classmethod
    def _get_snapshot_id(cls, exploration_id, version_number):
        return '%s-%s' % (exploration_id, version_number)

    @property
    def exploration_id(self):
        return self.id.split('-')[0]

    @property
    def version_number(self):
        return self.id.split('-')[1]

    FORMAT_TYPE_FULL = 'full'
    FORMAT_TYPE_DIFF = 'diff'

    def _pre_put_hook(self):
        if self.format not in [self.FORMAT_TYPE_FULL, self.FORMAT_TYPE_DIFF]:
            raise Exception('Invalid snapshot format: %s' % self.format)

    # The format of the snapshot (the full serialization, or a diff from the
    # previous snapshot; these correspond to the possible values
    # FORMAT_TYPE_FULL or FORMAT_TYPE_DIFF, respectively).
    format = ndb.StringProperty()
    # The snapshot content, as a JSON blob.
    content = ndb.JsonProperty(indexed=False)

    @classmethod
    def get_snapshot_content(cls, exploration_id, version_number):
        """Returns the exploration snapshot content."""
        snapshot_id = cls._get_snapshot_id(exploration_id, version_number)

        snapshot = cls.get(snapshot_id)
        return {
            'format': snapshot.format,
            'content': snapshot.content
        }

    @classmethod
    def save_snapshot_content(cls, snapshot_id, snapshot_format, json_blob):
        """Saves a new snapshot content for the given exploration.

        This method should only be called from ExplorationSnapshotModel.
        """

        if not json_blob:
            raise Exception(
                'Empty content submitted for exploration snapshot.')

        snapshot_content_model = cls(
            id=snapshot_id, format=snapshot_format, content=json_blob)
        snapshot_content_model.put()


class ExplorationRightsModel(base_models.BaseModel):
    """Storage model for rights related to an exploration.

    The id of each instance is the id of the corresponding exploration.
    """

    # The user_ids of owners of this exploration.
    owner_ids = ndb.StringProperty(repeated=True)
    # The user_ids of users who are allowed to edit this exploration.
    editor_ids = ndb.StringProperty(repeated=True)
    # The user_ids of users who are allowed to view this exploration.
    viewer_ids = ndb.StringProperty(repeated=True)

    # Whether this exploration is owned by the community.
    community_owned = ndb.BooleanProperty(default=False)
    # The exploration id which this exploration was cloned from. If None, this
    # exploration was created from scratch.
    cloned_from = ndb.StringProperty()

    # The publication status of this exploration.
    status = ndb.StringProperty(
        default='private', choices=['private', 'public', 'publicized']
    )
