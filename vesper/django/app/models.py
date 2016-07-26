import logging
import os.path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.db.models import (
    BigIntegerField, CASCADE, CharField, DateTimeField, FloatField, ForeignKey,
    IntegerField, ManyToManyField, Model, TextField)

import vesper.util.os_utils as os_utils
import vesper.util.vesper_path_utils as vesper_path_utils


def _double(*args):
    return tuple((a, a) for a in args)


class DeviceModel(Model):
    
    type = CharField(max_length=255)
    manufacturer = CharField(max_length=255)
    model = CharField(max_length=255)
    short_name = CharField(max_length=255, blank=True)
    description = TextField(blank=True)
    
    @property
    def long_name(self):
        return '{} {} {}'.format(self.manufacturer, self.model, self.type)
    
    def __str__(self):
        return self.long_name
    
    class Meta:
        unique_together = ('manufacturer', 'model')
        db_table = 'vesper_device_model'
    
    
class DeviceModelInput(Model):
    
    model = ForeignKey(DeviceModel, on_delete=CASCADE, related_name='inputs')
    name = CharField(max_length=255)
    description = TextField(blank=True)
    
    @property
    def long_name(self):
        return self.model.long_name + ' ' + self.name
    
    @property
    def short_name(self):
        return self.model.short_name + ' ' + self.name
    
    def __str__(self):
        return self.long_name
    
    class Meta:
        unique_together = ('model', 'name')
        db_table = 'vesper_device_model_input'


class DeviceModelOutput(Model):
    
    model = ForeignKey(DeviceModel, on_delete=CASCADE, related_name='outputs')
    name = CharField(max_length=255)
    description = TextField(blank=True)
    
    @property
    def long_name(self):
        return self.model.long_name + ' ' + self.name
    
    @property
    def short_name(self):
        return self.model.short_name + ' ' + self.name
    
    def __str__(self):
        return self.long_name
    
    class Meta:
        unique_together = ('model', 'name')
        db_table = 'vesper_device_model_output'


class DeviceModelSetting(Model):
    
    model = ForeignKey(DeviceModel, on_delete=CASCADE, related_name='settings')
    name = CharField(max_length=255)
    description = TextField(blank=True)
    
    @property
    def long_name(self):
        return self.model.long_name + ' ' + self.name
    
    @property
    def short_name(self):
        return self.model.short_name + ' ' + self.name
    
    def __str__(self):
        return self.long_name
    
    class Meta:
        unique_together = ('model', 'name')
        db_table = 'vesper_device_model_setting'
        
        
class Device(Model):
    
    model = ForeignKey(DeviceModel, on_delete=CASCADE, related_name='instances')
    serial_number = CharField(max_length=255)
    description = TextField(blank=True)
    
    @property
    def long_name(self):
        return self.model.long_name + ' ' + self.serial_number
    
    @property
    def short_name(self):
        return self.model.short_name + ' ' + self.serial_number
    
    def __str__(self):
        return self.long_name
    
    class Meta:
        unique_together = ('model', 'serial_number')
        db_table = 'vesper_device'


class DeviceInput(Model):
    
    device = ForeignKey(Device, on_delete=CASCADE, related_name='inputs')
    model_input = ForeignKey(
        DeviceModelInput, on_delete=CASCADE, related_name='instances')
    
    @property
    def name(self):
        return self.model_input.name
    
    @property
    def long_name(self):
        return self.device.long_name + ' ' + self.name
    
    @property
    def short_name(self):
        return self.device.short_name + ' ' + self.name
    
    def __str__(self):
        return self.long_name
    
    class Meta:
        unique_together = ('device', 'model_input')
        db_table = 'vesper_device_input'
        
        
class DeviceOutput(Model):
    
    device = ForeignKey(Device, on_delete=CASCADE, related_name='outputs')
    model_output = ForeignKey(
        DeviceModelOutput, on_delete=CASCADE, related_name='instances')
    
    @property
    def name(self):
        return self.model_output.name
    
    @property
    def long_name(self):
        return self.device.long_name + ' ' + self.name
    
    @property
    def short_name(self):
        return self.device.short_name + ' ' + self.name
    
    def __str__(self):
        return self.long_name
    
    class Meta:
        unique_together = ('device', 'model_output')
        db_table = 'vesper_device_output'
        
        
class DeviceSetting(Model):
    
    device = ForeignKey(Device, on_delete=CASCADE, related_name='settings')
    model_setting = ForeignKey(
        DeviceModelSetting, on_delete=CASCADE, related_name='instances')
    value = CharField(max_length=255)
    start_time = DateTimeField()
    end_time = DateTimeField()
    
    @property
    def name(self):
        return self.model_setting.name
    
    @property
    def long_name(self):
        return '{} {} = {} from {} to {}'.format(
            self.device.long_name, self.name, self.value,
            str(self.start_time), str(self.end_time))
    
    @property
    def short_name(self):
        return '{} {} = {} from {} to {}'.format(
            self.device.short_name, self.name, self.value,
            str(self.start_time), str(self.end_time))
    
    def __str__(self):
        return self.long_name
        
    class Meta:
        unique_together = (
            'device', 'model_setting', 'value', 'start_time', 'end_time')
        db_table = 'vesper_device_setting'
    
    
class DeviceConnection(Model):
    
    output = ForeignKey(
        DeviceOutput, on_delete=CASCADE, related_name='connections')
    input = ForeignKey(
        DeviceInput, on_delete=CASCADE, related_name='connections')
    start_time = DateTimeField()
    end_time = DateTimeField()
    
    @property
    def long_name(self):
        return '{} -> {} from {} to {}'.format(
            self.output.long_name, self.input.long_name,
            str(self.start_time), str(self.end_time))
    
    @property
    def short_name(self):
        return '{} -> {} from {} to {}'.format(
            self.output.short_name, self.input.short_name,
            str(self.start_time), str(self.end_time))
    
    def __str__(self):
        return self.long_name
        
    class Meta:
        unique_together = ('output', 'input', 'start_time', 'end_time')
        db_table = 'vesper_device_connection'
    
    
class RecorderChannelAssignment(Model):
    
    recorder = ForeignKey(
        Device, on_delete=CASCADE, related_name='channel_assignments')
    input = ForeignKey(
        DeviceInput, on_delete=CASCADE, related_name='channel_assignments')
    channel_num = IntegerField()
    start_time = DateTimeField()
    end_time = DateTimeField()
    
    @property
    def long_name(self):
        return '{} -> {} from {} to {}'.format(
            self.input.long_name, self.channel_num,
            str(self.start_time), str(self.end_time))
    
    @property
    def short_name(self):
        return '{} -> {} from {} to {}'.format(
            self.input.short_name, self.channel_num,
            str(self.start_time), str(self.end_time))
    
    def __str__(self):
        return self.long_name
        
    class Meta:
        unique_together = (
            'recorder', 'input', 'channel_num', 'start_time', 'end_time')
        db_table = 'vesper_recorder_channel_assignment'
    
    
# Many stations have a fixed location, in which case the location can
# be recorded using the `latitude`, `longitude`, and `elevation` fields
# of the `Station` model. Some stations are mobile, however, so we will
# eventually want to support the storage of station track data. See the
# commented-out `StationTrack` and `StationLocation` models below.
#
# In some cases the sensors of a station will be at different locations,
# and these locations will be used for source localization. In this case
# we will want to track the locations of individual sensors. This could
# be accomplished with `DeviceTrack` and `DeviceLocation` models similar
# to the commented-out `StationTrack` and `StationLocation` models below.
class Station(Model):
    
    name = CharField(max_length=255, unique=True)
    description = TextField(blank=True)
    latitude = FloatField(null=True)
    longitude = FloatField(null=True)
    elevation = FloatField(null=True)
    time_zone = CharField(max_length=255)
    devices = ManyToManyField(Device, through='StationDevice')
    
    def __str__(self):
        return self.name
    
    class Meta:
        db_table = 'vesper_station'
    
    
# The `StationTrack` and `StationLocation` models will store tracks of mobile
# stations. When we want the location of a station at a specified time, we
# can look first for a `StationTrack` whose time interval includes that time,
# and if there is no such track we can fall back on the location from the
# `Station` model (if that location is specified). The `Station` model might
# also have a boolean `mobile` field to tell us whether or not to look for
# tracks before looking for the `Station` location.
# class StationTrack(Model):
#     station = ForeignKey(Station, on_delete=CASCADE, related_name='tracks')
#     start_time = DateTimeField()
#     end_time = DateTimeField()
#     class Meta:
#         db_table = 'vesper_station_track'
# 
#     
# class StationLocation(Model):
#     track = ForeignKey(
#         StationTrack, on_delete=CASCADE, related_name='locations')
#     latitude = FloatField()
#     longitude = FloatField()
#     elevation = FloatField(null=True)
#     time = DateTimeField()
#     class Meta:
#         db_table = 'vesper_station_location'
    
    
class StationDevice(Model):
    
    station = ForeignKey(
        Station, on_delete=CASCADE, related_name='device_associations')
    device = ForeignKey(
        Device, on_delete=CASCADE, related_name='station_associations')
    start_time = DateTimeField()
    end_time = DateTimeField()
    
    @property
    def long_name(self):
        return '{} at {} from {} to {}'.format(
            self.device.long_name, self.station.name,
            str(self.start_time), str(self.end_time))
        
    @property
    def short_name(self):
        return '{} at {} from {} to {}'.format(
            self.device.short_name, self.station.name,
            str(self.start_time), str(self.end_time))
        
    def __str__(self):
        return self.long_name
        
    class Meta:
        unique_together = ('station', 'device', 'start_time', 'end_time')
        db_table = 'vesper_station_device'


class Algorithm(Model):
    
    type = CharField(max_length=255)
    name = CharField(max_length=255)
    version = CharField(max_length=255)
    description = TextField(blank=True)
    
    def __str__(self):
        return self.name + ' ' + self.version
    
    class Meta:
        unique_together = ('type', 'name', 'version')
        db_table = 'vesper_algorithm'
    
    
class Processor(Model):
    
    algorithm = ForeignKey(
        Algorithm, on_delete=CASCADE, related_name='processors')
    name = CharField(max_length=255)
    description = TextField(blank=True)
    settings = TextField(blank=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        unique_together = ('algorithm', 'name')
        db_table = 'vesper_processor'
        
    
# A *command* is a specification of something to be executed, possibly
# more than once. A *job* is a particular execution of a command.
class Job(Model):
    
    command = TextField()
    creation_time = DateTimeField()
    creating_user = ForeignKey(
        User, null=True, on_delete=CASCADE, related_name='jobs')
    creating_job = ForeignKey(
        'Job', null=True, on_delete=CASCADE, related_name='jobs')
    processor = ForeignKey(
        Processor, null=True, on_delete=CASCADE, related_name='jobs')
    start_time = DateTimeField(null=True)
    end_time = DateTimeField(null=True)
    status = CharField(max_length=255)
    
    def __str__(self):
        return 'Job {} started {} ended {} command "{}"'.format(
            self.id, self.start_time, self.end_time, self.command)
        
    class Meta:
        db_table = 'vesper_job'
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._logger = None
        
    @property
    def log_file_path(self):
        dir_path = _get_job_logs_dir_path()
        file_name = 'Job {}.log'.format(self.id)
        return os.path.join(dir_path, file_name)
        
    @property
    def logger(self):
        if self._logger is None:
            self._logger = self._create_logger()
        return self._logger
    
    def _create_logger(self):
        
        _create_job_logs_dir_if_needed()
        
        logger_name = 'Job {}'.format(self.id)
        logger = logging.getLogger(logger_name)
        
        level = 'INFO' if settings.DEBUG else 'INFO'
        file_path = self.log_file_path
        
        config = {
            'version': 1,
            'formatters': {
                'vesper': {
                    'class': 'logging.Formatter',
                    'format': '%(asctime)s %(levelname)-8s %(message)s'
                }
            },
            'handlers': {
                'console': {
                    'class': 'logging.StreamHandler',
                    'level': level,
                    'formatter': 'vesper'
                },
                'file': {
                    'class': 'logging.FileHandler',
                    'filename': file_path,
                    'mode': 'w',
                    'level': level,
                    'formatter': 'vesper'
                }
            },
            'loggers': {
                logger_name: {
                    'handlers': ['console', 'file'],
                    'level': level,
                }
            }
        }
        
        logging.config.dictConfig(config)
        
        return logger
    
    
    @property
    def log(self):
        return os_utils.read_file(self.log_file_path)
        

_job_logs_dir_path = None


def _get_job_logs_dir_path():
    
    global _job_logs_dir_path
    
    if _job_logs_dir_path is None:
        _job_logs_dir_path = vesper_path_utils.get_path('Logs', 'Jobs')
            
    return _job_logs_dir_path


def _create_job_logs_dir_if_needed():
    dir_path = _get_job_logs_dir_path()
    os_utils.create_directory(dir_path)
    
    
# We include the `end_time` field even though it's redundant to accelerate
# queries.
#
# An alternative to making the `recorder` field a `StationDevice` would be
# to have a `station` field that is a `Station` and a `recorder` field
# that is a `Device`. However, the latter introduces a redundancy between
# the recorders indicated in the `StationDevice` table and the recorders
# indicated in the `Recording` table. The former eliminates this redundancy.
class Recording(Model):
    
    station_recorder = ForeignKey(
        StationDevice, on_delete=CASCADE, related_name='recordings')
    num_channels = IntegerField()
    length = BigIntegerField()
    sample_rate = FloatField()
    start_time = DateTimeField()
    end_time = DateTimeField()
    
    @property
    def station(self):
        return self.station_recorder.station
    
    @property
    def recorder(self):
        return self.station_recorder.device
    
    def __str__(self):
        return 'Recording "{}" "{}" {} {} {} {}'.format(
            self.station_recorder.station.name,
            self.station_recorder.device.long_name,
            self.num_channels, self.length, self.sample_rate, self.start_time)
        
    class Meta:
        unique_together = ('station_recorder', 'start_time')
        db_table = 'vesper_recording'
        
        
class RecordingFile(Model):
    
    recording = ForeignKey(Recording, on_delete=CASCADE, related_name='files')
    file_num = IntegerField()
    start_index = BigIntegerField()
    length = BigIntegerField()
    file_path = CharField(max_length=255, unique=True, null=True) # long enough?
    
    class Meta:
        unique_together = ('recording', 'file_num')
        db_table = 'vesper_recording_file'


# After much deliberation, I have decided to require that every clip
# refer to a recording. I considered allowing so-called *orphaned clips*
# that did not refer to a recording, but it seems to me that doing this
# would be more trouble than it's worth. It would complicate the database
# schema, code that uses the database, and the Vesper user interface and
# documentation, all for a situation that is uncommon. Note that we do
# *not* require that the samples of a clip's recording be available, only
# the recording's metadata, including its station, recorder, number of
# channels, start time, and length. In cases where somebody wants to import
# a set of clips for which some recording metadata (start times and lengths,
# for example) are not available, made-up metadata will have to be supplied,
# and the fact that the information is made up will have to be noted.
#
# The station, recorder, and sample rate of a clip are the station,
# recorder, and sample rate of its recording.
#
# The `end_time` field of a clip is redundant, since it can be computed
# from the clip's start time, length, and sample rate. We include it anyway
# to accelerate certain types of queries. For example, we will want to be
# able to find all of the clips whose time intervals intersect a specified
# recording subinterval.
#
# The `file_path` field of a clip should be `None` if and only if the clip
# samples are available as part of the clip's recording, and the clip is not
# itself stored in its own file. In some cases the samples of a clip may be
# available both as part of the clip's recording and in an extracted clip
# file. In this case the `file_path` field should be the path of the extracted
# clip file.
#
# We include a multi-column unique constraint to prevent duplicate clips
# from being created by accidentally running a particular detector on a
# particular recording more than once.
class Clip(Model):
    
    recording = ForeignKey(Recording, on_delete=CASCADE, related_name='clips')
    channel_num = IntegerField()
    start_index = BigIntegerField(null=True)
    length = BigIntegerField()
    start_time = DateTimeField()
    end_time = DateTimeField()
    creation_time = DateTimeField()
    creating_user = ForeignKey(
        User, null=True, on_delete=CASCADE, related_name='clips')
    creating_processor = ForeignKey(
        Processor, null=True, on_delete=CASCADE, related_name='clips')
    creating_job = ForeignKey(
        Job, null=True, on_delete=CASCADE, related_name='clips')
    file_path = CharField(max_length=255, unique=True, null=True) # long enough?
    
    def __str__(self):
        return 'Clip {} {} {} {} {} "{}"'.format(
            str(self.recording), self.channel_num, self.start_index,
            self.length, self.start_time, self.file_path)
        
    class Meta:
        unique_together = (
            'recording', 'channel_num', 'start_time', 'length',
            'creating_processor')
        db_table = 'vesper_clip'
        
    @property
    def station(self):
        return self.recording.station
    
    @property
    def recorder(self):
        return self.recording.recorder
    
    @property
    def sample_rate(self):
        return self.recording.sample_rate
    
    @property
    def wav_file_contents(self):
        # TODO: Handle errors, e.g. no such file.
        with open(self.wav_file_path, 'rb') as file_:
            return file_.read()
        
    @property
    def wav_file_path(self):
        if self.file_path is None:
            return _create_clip_file_path(self)
        else:
            return self.file_path
        
    @property
    def wav_file_url(self):
        return reverse('clip-wav', args=(self.id,))


# TODO: Don't hard code this.
_CLIPS_DIR_FORMAT = (3, 3)


def _create_clip_file_path(clip):
    id_parts = _get_clip_id_parts(clip.id, _CLIPS_DIR_FORMAT)
    path_parts = id_parts[:-1]
    id_ = ' '.join(id_parts)
    file_name = 'Clip {}.wav'.format(id_)
    path_parts.append(file_name)
    return vesper_path_utils.get_path('Clips', *path_parts)


def _get_clip_id_parts(num, format_):
    
    # Format number as digit string with leading zeros.
    num_digits = sum(format_)
    f = '{:0' + str(num_digits) + 'd}'
    digits = f.format(num)
    
    # Split string into parts.
    i = 0
    parts = []
    for num_digits in format_:
        parts.append(digits[i:i + num_digits])
        i += num_digits
        
    return parts
    
    
class Annotation(Model):
    
    clip = ForeignKey(Clip, on_delete=CASCADE, related_name='annotations')
    name = CharField(max_length=255)      # e.g. 'Classification', 'Outside'
    value = TextField(blank=True)         # e.g. 'NFC.AMRE', 'True'
    creation_time = DateTimeField(null=True)
    creating_user = ForeignKey(
        User, null=True, on_delete=CASCADE, related_name='annotations')
    creating_job = ForeignKey(
        Job, null=True, on_delete=CASCADE, related_name='annotations')
    
    def __str__(self):
        return '({}, {})'.format(self.name, self.value)
    
    class Meta:
        unique_together = ('clip', 'name')
        db_table = 'vesper_annotation'