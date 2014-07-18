"""Adds clips to an NFC archive from an external source directory."""


from __future__ import print_function

from collections import defaultdict
import argparse
import calendar
import datetime
import os
import sys
import time

from nfc.archive.archive import Archive
from nfc.archive.clip_class import ClipClass
from nfc.archive.detector import Detector
from nfc.archive.dummy_archive import DummyArchive
from nfc.archive.station import Station
from nfc.util.directory_visitor import DirectoryVisitor
from old_bird.archiver_time_keeper import (
    ArchiverTimeKeeper, NonexistentTimeError, AmbiguousTimeError)
import nfc.archive.archive_utils as archive_utils
import nfc.util.sound_utils as sound_utils
import nfc.util.time_utils as time_utils
import old_bird.file_name_utils as file_name_utils


_STATIONS = [Station(*t) for t in [
    ('Ajo', 'Ajo High School', 'US/Arizona'),
    ('Alfred', 'Klingensmith Residence', 'US/Eastern'),
    ('CLC', 'Columbia Land Conservancy', 'US/Eastern'),
    ('Danby', 'Evans Residence', 'US/Eastern'),
    ('DHBO', 'Derby Hill Bird Observatory', 'US/Eastern'),
    ('HHSS', 'Harlingen High School South', 'US/Central'),
    ('JAS', 'Jamestown Audubon Society', 'US/Eastern'),
    ('LTU', 'Louisiana Technical University', 'US/Central'),
    ('Minatitlan',
     u'Minatitl\u00E1n/Coatzacoalcos International Airport',
     'America/Mexico_City'),
    ('NMHS', 'North Manchester High School', 'US/Eastern'),
    ('Oneonta', 'Oneonta Municipal Airport', 'US/Eastern'),
    ('ONWR', 'Ottawa National Wildlife Refuge', 'US/Eastern'),
    ('Skinner', 'Skinner State Park', 'US/Eastern'),
    ('WFU', 'Wake Forest University', 'US/Eastern')
]]

_MONITORING_TIME_ZONE_NAMES = {}
"""
See documentation for the `ArchiverTimeKeeper` initializer `time_zone_names`
parameter.
"""

_MONITORING_START_TIMES = {
    2012: {
        'Alfred': ('21:00:00', ['10-3']),
        'DHBO': ('21:00:00', [('5-11', '5-12'), ('5-28', '6-6')]),
        'JAS': ('21:00:00', [('8-17', '8-19')]),
        'Oneonta': ('21:00:00', []),
        'ONWR': ('20:00:00', ['9-04', '9-17']),
        'Skinner': ('21:00:00',
                    ['8-13', '8-14', ('10-6', '10-12'), ('10-14', '10-25')])
    }
}
"""
See documentation for the `ArchiverTimeKeeper` initializer `start_times`
parameter.
"""


_DETECTORS = [Detector('Tseep')]

_CLIP_CLASS_DIR_NAME_CORRECTIONS = {
    'calls': 'call',
    'tones': 'tone',
    'palm': 'pawa',
    'shdbup': 'dbup',
    'unkn': 'unknown'
}
'''
Mapping from lower case clip class directory names to their lower case
corrections.
'''

_CALL_CLIP_CLASS_NAMES = frozenset([
                          
    'AMRE', 'ATSP', 'BAWW', 'BRSP', 'BTBW', 'CAWA', 'CCSP', 'CHSP',
    'CMWA', 'COYE', 'CSWA', 'FOSP', 'GHSP', 'HESP', 'HOWA', 'INBU',
    'LALO', 'LCSP', 'MOWA', 'NOPA', 'NWTH', 'OVEN', 'PAWA', 'PROW',
    'SNBU', 'SVSP', 'VESP', 'WCSP', 'WIWA', 'WTSP', 'YRWA',
    
    'WTSP.Songtype',
    
    'DbUp', 'Other', 'SNBULALO', 'SwLi', 'Unknown', 'Weak', 'Zeep'

])

_CLIP_CLASS_NAMES = \
    ['Call', 'Noise', 'Tone'] + ['Call.' + n for n in _CALL_CLIP_CLASS_NAMES]
_CLIP_CLASS_NAMES.sort()
_CLIP_CLASSES = [ClipClass(name) for name in _CLIP_CLASS_NAMES]
    
_CLIP_CLASS_NAMES_DICT = dict(
    [(n.split('.')[-1].lower(), n) for n in _CLIP_CLASS_NAMES] +
    [('classified', 'Call')])
'''mapping from lower case clip class directory names to clip class names'''

_MONTH_PREFIXES = [
    'jan', 'feb', 'mar', 'apr', 'may', 'jun',
    'jul', 'aug', 'sep', 'oct', 'nov', 'dec']

_MONTH_NUMS = dict((s, i + 1) for (i, s) in enumerate(_MONTH_PREFIXES))

_MONTH_PREFIXES = frozenset(_MONTH_PREFIXES)

_MONTH_NAMES = dict((i + 1, s) for (i, s) in enumerate([
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December']))


def _main():
    
    args = _get_args()
    
    logger = _Logger(args.verbose, args.source_dir)
    
    archive = _open_archive(args)
    
    station_names = _get_station_names(args, archive)
    
    visitor = _OldBirdSourceDirectoryVisitor()
    
    visitor.visit(
        args.source_dir, args.year, archive, logger, station_names,
        args.dates, args.start_date, args.end_date,
        args.dry_run, args.max_num_clips, args.performance_reporting_period,
        args.count_ignored_dir_clips)
    
    _close_archive(archive, logger)
    
    visitor.log_stats()

    
def _get_args():
    
    args = _parse_args()
    
    try:
        _check_args(args)
        
    except ValueError as e:
        _handle_fatal_error(str(e))
    
    return args


def _handle_fatal_error(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def _parse_args():
    
    parser = argparse.ArgumentParser(
        description='''
            This script adds clips to an NFC archive from an external
            source directory. The archive can be either a new or
            existing one. The source directory has a hierarchical
            structure and contains clips in individual sound files.
            The script displays progress and error messages as it
            proceeds, and a summary of its processing on completion.''',
        fromfile_prefix_chars='@')
    
    date_format = 'YYYY-MM-DD'
    
    parser.add_argument(
        '--verbose', action='store_true', default=False,
        help='display more detailed progress messages')
    
    parser.add_argument(
        '--dry-run', action='store_true', default=False,
        help='process clips as usual except do not add them to archive')
    
    parser.add_argument(
        '--max-num-clips', type=int, default=None,
        help='maximum number of clips to process')
    
    parser.add_argument(
        '--performance-reporting-period', type=int, metavar='NUM_CLIPS',
        default=None, help='period with which to report performance')
    
    parser.add_argument(
        '--stations', nargs='+', metavar='STATION',
        help='names of stations to include')
    
    parser.add_argument(
        '--excluded-stations', nargs='+', metavar='STATION',
        help='names of stations to exclude')
    
    parser.add_argument(
        '--dates', nargs='+', metavar=date_format,
        help='one or more dates of clips to process')
    
    parser.add_argument(
        '--start-date', metavar=date_format,
        help='start date of clips to process')
    
    parser.add_argument(
        '--end-date', metavar=date_format,
        help='end date of clips to process')
    
    parser.add_argument(
        '--year', type=int, metavar='YYYY', help='year of clips')
    
    parser.add_argument(
        '--create-archive', action='store_true', default=False,
        help='create new archive')
    
    parser.add_argument(
        '--count-ignored-dir-clips', action='store_true', default=False,
        help='count clip files in ignored directories')
    
    parser.add_argument(
        'source_dir', type=str, help='path of source root directory')
    
    parser.add_argument(
        'archive_dir', type=str, help='path of archive root directory')
    
    args = parser.parse_args()
    
    return args


def _check_args(args):
    
    if args.max_num_clips is not None and args.max_num_clips < 0:
        raise ValueError('Maximum number of clips must be nonnegative.')
    
    if args.performance_reporting_period is not None and \
       args.performance_reporting_period <= 0:
        
        raise ValueError('Performance logging period must be positive.')
    
    _check_station_names(args.stations)
    _check_station_names(args.excluded_stations)
    _parse_dates(args)
        
    if args.year is None:
        raise ValueError('Year of data must be specified.')
    
    if args.year < 1900:
        raise ValueError('Year {:d} is too small.'.format(args.year))
    
    if args.year > datetime.datetime.now().year:
        raise ValueError('Year {:d} is in the future.'.format(args.year))
    
    if not os.path.exists(args.source_dir):
        f = 'Source directory "{:s}" does not exist.'
        raise ValueError(f.format(args.source_dir))
    
    if not args.dry_run:
        
        archive_dir_exists = os.path.exists(args.archive_dir)
        
        if args.create_archive and archive_dir_exists:
            
            f = ('Archive directory "{:s}" exists. Please delete or '
                 'rename it and try again.')
            raise ValueError(f.format(args.archive_dir))
        
        elif not args.create_archive and not archive_dir_exists:
            
            f = 'Archive directory "{:s}" does not exist.'
            raise ValueError(f.format(args.archive_dir))
    
    
def _check_station_names(names):
    
    if names is not None:
        
        station_names = frozenset(s.name for s in _STATIONS)
        
        for name in names:
            
            if name not in station_names:
                f = 'Unrecognized station name "{:s}".'
                raise ValueError(f.format(name))
        
    
def _parse_dates(args):
    
    if args.dates is not None:
        args.dates = [_parse_date(d, 'date') for d in args.dates]
        
    else:
        
        if args.start_date is not None:
            args.start_date = _parse_date(args.start_date, 'start date')
            
        if args.end_date is not None:
            args.end_date = _parse_date(args.end_date, 'end date')
            
            
def _parse_date(s, name):
    try:
        return time_utils.parse_date(s)
    except ValueError:
        raise ValueError('Bad {:s} "{:s}".'.format(name, s))
    
    
def _open_archive(args):
    
    init_args = (args.archive_dir, _STATIONS, _DETECTORS, _CLIP_CLASSES)
    
    if args.dry_run:
        archive = DummyArchive.create(*init_args)
        archive.open()

    else:
        
        if args.create_archive:
            archive = Archive.create(*init_args)
            
        else:
            archive = Archive(args.archive_dir)
            
        archive.open(cache_db=True)
        
    return archive


def _get_station_names(args, archive):
    
    station_names = frozenset(s.name for s in archive.stations)
    
    if args.stations is not None:
        _validate_station_names(args.stations, station_names)
        return frozenset(args.stations)
    
    elif args.excluded_stations is not None:
        _validate_station_names(args.excluded_stations, station_names)
        return station_names - frozenset(args.excluded_stations)
        
    else:
        return station_names
    
    
def _validate_station_names(names, valid_names):
    for name in names:
        if name not in valid_names:
            f = 'Unrecognized station name "{:s}" in command line.'
            _handle_fatal_error(f.format(name))
            
            
def _close_archive(archive, logger):
    
    start_time = time.time()
    archive.close()
    delta = int(round(time.time() - start_time))
    
    f = 'Closed archive in {:d} seconds.'
    logger.log(f.format(delta))
        

class _OldBirdSourceDirectoryVisitor(DirectoryVisitor):
    
    
    def visit(
        self, path, year, archive, logger,
        station_names=None, dates=None, start_date=None, end_date=None,
        dry_run=False, max_num_clips=None, performance_reporting_period=None,
        count_ignored_dir_files=False):
        
        self.root_path = path
        self.year = year
        self.archive = archive
        self.station_names = station_names
        self.dates = _create_set(dates)
        self.start_date = start_date
        self.end_date = end_date
        self.dry_run = dry_run
        self.max_num_clips = max_num_clips
        self.performance_reporting_period = performance_reporting_period
        self.count_ignored_dir_files = count_ignored_dir_files
        
        self.stations = dict((s.name, s) for s in self.archive.stations)
        self.detectors = dict((d.name, d) for d in self.archive.detectors)

        # logging functions
        self._indent = logger.indent
        self._unindent = logger.unindent
        self._log = logger.log
        self._indent_v = logger.indent_v
        self._unindent_v = logger.unindent_v
        self._log_v = logger.log_v
        
        level_names = ['root', 'station', 'month', 'day']
        super(_OldBirdSourceDirectoryVisitor, self).visit(path, level_names)
        
        
    def _start_root_dir_visit(self, path):
        
        self.total_num_files = 0
        
        self.num_escaped_files = 0
        self.num_ignored_dir_files = 0
        self.num_date_time_file_names = 0
        self.num_resolved_file_names = 0
        self.num_unresolved_file_names = 0
        
        self.num_bad_detector_name_file_names = 0
        
        self.num_file_repetitions = 0
        self.num_duplicate_classifications = 0
        self.num_consistent_reclassifications = 0
        
        self.num_unreadable_files = 0
        self.num_add_errors = 0
        
        self.clip_counts = defaultdict(int)
        self.consistent_reclassification_counts = defaultdict(int)

        self.misplaced_file_counts = defaultdict(int)
        self.malformed_file_name_file_paths = set()
        self.bad_detector_name_dir_paths = set()
        self.nonexistent_time_file_counts = defaultdict(int)
        self.ambiguous_time_file_counts = defaultdict(int)
        self.unresolved_file_name_dir_paths = set()
        self.unreclassified_subclassified_call_paths = set()
        self.duplicate_classification_path_pairs = set()
        self.inconsistent_reclassifications = set()
        
        self.time_keeper = ArchiverTimeKeeper(
            self.stations, _MONITORING_TIME_ZONE_NAMES,
            _MONITORING_START_TIMES)
        
        self.resolved_times = {}
        
        self.clip_info = {}
        
        self._log('Directory "{:s}"'.format(path))
        self._indent()
        
        self.start_time = time.time()
        
        self._count_escaped_files(path)
        
        return True
        
        
    def _count_escaped_files(self, path):
        n = _count_clip_files(path, recursive=False)
        if n != 0:
            suffix = 's' if n > 1 else ''
            f = 'Found {:d} escaped clip file{:s} in directory "{:s}"'
            self._log(f.format(n, suffix, self._rel(path)))
        self.num_escaped_files += n
            
            
    def _end_root_dir_visit(self, path):
        self._unindent()
        self.total_num_files += \
            self.num_escaped_files + self.num_ignored_dir_files
        
        
    def _start_station_dir_visit(self, path):
        
        if self._max_num_clips_reached():
            return False
        
        name = os.path.basename(path)
        
        if name not in self.stations:
            self._ignore_station_dir(path, 'unrecognized')
            return False
            
        elif self.station_names is not None and \
                 name not in self.station_names:
            self._count_ignored_dir_files(path)
            return False
            
        else:
            self.station = self.stations[name]
            self._log('Station "{:s}"'.format(self.station.name))
            self._indent()
            self._count_escaped_files(path)
            return True
        
        
    def _ignore_station_dir(self, path, description):
        f = 'Ignored {:s} station directory "{:s}".'
        self._log(f.format(description, self._rel(path)))
        self._count_ignored_dir_files(path)
        
        
    def _count_ignored_dir_files(self, path):
        if self.count_ignored_dir_files:
            self.num_ignored_dir_files += _count_clip_files(path)
        
        
    def _end_station_dir_visit(self, path):
        self._unindent()
        
        
    def _max_num_clips_reached(self):
        return self.max_num_clips is not None and \
               self.total_num_files >= self.max_num_clips


    def _start_month_dir_visit(self, path):
        
        if self._max_num_clips_reached():
            return False

        name = os.path.basename(path)
        month = _MONTH_NUMS.get(name[:3].lower())
        
        if month is None:
            self._ignore_month_dir(path, 'unrecognized')
            return False
        
        elif not self._is_month_included(self.year, month):
            self._count_ignored_dir_files(path)
            return False
            
        else:
            self.month = month
            f = 'Month "{:s}" {:d}'
            self._log(f.format(name, month))
            self._indent()
            self._count_escaped_files(path)
            return True
        
        
    def _ignore_month_dir(self, path, description):
        f = 'Ignored {:s} month directory "{:s}".'
        self._log(f.format(description, self._rel(path)))
        self._count_ignored_dir_files(path)
            
            
    def _is_month_included(self, year, month):
        
        if self.dates is not None:
            for date in self.dates:
                if date.year == year and date.month == month:
                    return True
                
        else:
            return self._is_month_ge_start_month(year, month) and \
                   self._is_month_le_end_month(year, month)
            
            
    def _is_month_ge_start_month(self, year, month):
        
        if self.start_date is None:
            return True
        
        else:
            date = datetime.date(year, month, 1)
            start = self.start_date.replace(day=1)
            return date >= start
    
    
    def _is_month_le_end_month(self, year, month):
        
        if self.end_date is None:
            return True
        
        else:
            date = datetime.date(year, month, 1)
            end = self.end_date.replace(day=1)
            return date <= end

    
    def _end_month_dir_visit(self, path):
        self._unindent()
        
        
    def _start_day_dir_visit(self, path):
        
        if self._max_num_clips_reached():
            return False
        
        try:
            self.night = self._get_night(path)
        except:
            return False
        
        if not self._is_day_included(self.night):
            self._count_ignored_dir_files(path)
            return False
        
        else:
            self._visit_day_dir(path)
            return True
        
        
    def _get_night(self, path):
        
        try:
            
            name = os.path.basename(path)
            (start_day, end_day) = name.split('-')
            
            start_day = int(start_day)
            
            i = 1 if not end_day[1].isdigit() else 2
            prefix = end_day[i:].lower()
            month = _MONTH_NUMS[prefix[:3]]
            if not _MONTH_NAMES[month].lower().startswith(prefix):
                raise ValueError()
            end_day = int(end_day[:i])
            
        except:
            self._ignore_day_dir(path, 'unrecognized')
            raise

        if month != self.month:
            self._ignore_day_dir(path, 'misplaced or misnamed')
            raise ValueError()
        
        if start_day < 1:
            self._ignore_day_dir(path, 'misnamed (start date is invalid)')
            raise ValueError()
        
        else:
            
            start_month = month if end_day != 1 else month - 1

            (_, month_days) = calendar.monthrange(self.year, start_month)
            
            if start_day > month_days:
                self._ignore_day_dir(path, 'misnamed (start date is invalid)')
                raise ValueError()
            
        # We assume here that day directory names reflect local time,
        # regardless of the monitoring time zone.
        midnight = datetime.datetime(self.year, self.month, end_day, 0, 0, 0)
        night = archive_utils.get_night(midnight)
        
        return night
        
        
    def _ignore_day_dir(self, path, description):
        f = 'Ignored {:s} day directory "{:s}".'
        self._log(f.format(description, self._rel(path)))
        self._count_ignored_dir_files(path)

    
    def _is_day_included(self, date):
        
        if self.dates is not None:
            return date in self.dates
               
        else:
            return (self.start_date is None or date >= self.start_date) and \
                   (self.end_date is None or date <= self.end_date)

        
    def _visit_day_dir(self, path):
        
        name = os.path.basename(path)
        
        f = 'Day "{:s}" {:02d}-{:02d}'
        self._log_v(f.format(name, self.night.month, self.night.day))
        
        self._indent_v()
        self._visit_clip_dir(path, [])
        self._unindent_v()
        
        
    def _visit_clip_dir(self, path, clip_class_dir_names):
        
        clip_class_name = self._get_clip_class_name(path, clip_class_dir_names)
                    
        n = len(clip_class_dir_names)
        
        if n != 0:
            class_name = clip_class_name
            if class_name is None:
                class_name = '<None>'
            dir_name = os.path.basename(path)
            f = 'Clip class {:d} "{:s}" {:s}'
            self._log_v(f.format(n, dir_name, class_name))
            self._indent_v()
                
        for _, subdir_names, file_names in os.walk(path):
            
            for file_name in file_names:
                if file_name_utils.is_clip_file_name(file_name):
                    file_path = os.path.join(path, file_name)
                    self._visit_clip_file(file_path, clip_class_name)
                    
            for subdir_name in subdir_names:
                
                subdir_path = os.path.join(path, subdir_name)
                
                name = subdir_name.lower()
                name = _CLIP_CLASS_DIR_NAME_CORRECTIONS.get(name, name)
                
                self._visit_clip_dir(
                    subdir_path, clip_class_dir_names + [name])
                
            # stop walk from visiting subdirectories
            del subdir_names[:]
            
        if n != 0:
            self._unindent_v()
            
            
    def _get_clip_class_name(self, path, clip_class_dir_names):
        
        if len(clip_class_dir_names) == 0:
            return None
        
        try:
            return _CLIP_CLASS_NAMES_DICT[clip_class_dir_names[-1]]
        
        except KeyError:
            f = 'Unrecognized clip class directory name at "{:s}".'
            self._log(f.format(self._rel(path)))
            return None
            
            
    def _rel(self, path):
        return path[len(self.root_path) + 1:]
    
    
    def _visit_clip_file(self, path, clip_class_name):
        
        dir_path, file_name = os.path.split(path)
        
        try:
            (detector_name, time) = \
                file_name_utils.parse_date_time_clip_file_name(file_name)
                
        except ValueError:
            
            try:
                f = file_name_utils.parse_elapsed_time_clip_file_name
                (detector_name, time_delta) = f(file_name)
                    
            except ValueError:
                self.malformed_file_name_file_paths.add(path)
                              
            else:
                # successfully parsed elapsed time file name
                
                convert = self.time_keeper.convert_elapsed_time_to_utc
                time = convert(time_delta, self.station.name, self.night)
                
                if time is None:
                    self.num_unresolved_file_names += 1
                    self.unresolved_file_name_dir_paths.add(dir_path)

                else:
                    self.num_resolved_file_names += 1
                    self.resolved_times[(self.station.name, self.night)] = \
                        (time_delta, time)
                    self._visit_clip_file_aux(
                        path, self.station, detector_name, time,
                        clip_class_name)
                
        else:
            # successfully parsed date/time file name
            
            self.num_date_time_file_names += 1
            
            convert = self.time_keeper.convert_naive_time_to_utc
            
            try:
                time = convert(time, self.station.name)
                
            except NonexistentTimeError:
                self.nonexistent_time_file_counts[dir_path] += 1
            
            except AmbiguousTimeError:
                self.ambiguous_time_file_counts[dir_path] += 1
                
            else:
                # conversion of time to UTC succeeded
                
                self._visit_clip_file_aux(
                    path, self.station, detector_name, time, clip_class_name)
            
        self.total_num_files += 1
        
        if self.performance_reporting_period is not None and \
           self.total_num_files % self.performance_reporting_period == 0:
            
            self._log_performance()
            
            
    def _visit_clip_file_aux(
        self, path, station, detector_name, time, clip_class_name):
        
        dir_path = os.path.dirname(path)
        
        if station.get_night(time) != self.night:
            self.misplaced_file_counts[dir_path] += 1
            return
            
        if detector_name not in self.detectors:
            self.num_bad_detector_name_file_names += 1
            self.bad_detector_name_dir_paths.add(dir_path)
            return
            
        key = (station.name, detector_name, time)
        
        try:
            old_clip_class_name, old_path = self.clip_info[key]
        
        except KeyError:
            # do not already have clip for this station, detector, and time
            
            if self.dry_run:
                self._count_new_clip(key, clip_class_name, path)
                
            else:
                # not dry run
                
                try:
                    sound = sound_utils.read_sound_file(path)
                    
                except Exception, e:
                    f = 'Error reading sound file "{:s}": {:s}'
                    self._log(f.format(self._rel(path), str(e)))
                    self.num_unreadable_files += 1
                
                else:
                    # successfully read sound file
                
                    try:
                        self.archive.add_clip(
                            station.name, detector_name, time, sound,
                            clip_class_name)
                    
                    except Exception, e:
                        f = 'Error adding clip from "{:s}": {:s}'
                        self._log(f.format(self._rel(path), str(e)))
                        self.num_add_errors += 1
                    
                    else:
                        self._count_new_clip(key, clip_class_name, path)
            
        else:
            # already have clip for this station, detector, and time
            
            old = old_clip_class_name
            new = clip_class_name
            
            # We assume in the following that we will never encounter
            # a less specific classification of a clip after a more
            # specific but consistent one. This is the case since we
            # enumerate clip files breadth first, and more
            # specifically classified files are deeper in the
            # directory hierarchy. If somehow we do encounter a
            # less specific classification after a more specific one,
            # the reclassification will be considered inconsistent
            # and appear in the set of inconsistent classifications.
            
            if new == old:
                self.duplicate_classification_path_pairs.add((old_path, path))
                
            elif old is None or \
                 new is not None and \
                 new.startswith(old) and \
                 new[len(old)] == '.':
                # new classification is more specific version of old one
            
                self.clip_info[key] = (new, path)
                
                self.clip_counts[new] += 1
                self.clip_counts[old] -= 1
                
                self.consistent_reclassification_counts[old] += 1
                self.num_consistent_reclassifications += 1
        
            else:
                # new classification differs from old one and is not
                # a more specific version of it
                
                # In this case we leave the file with its original
                # classification, but remember both the old and
                # new classifications to report later. Inconsistent
                # reclassifications must be resolved manually.
                
                self.inconsistent_reclassifications.add((old_path, path))
                    
            self.num_file_repetitions += 1
        
    
    def _count_new_clip(self, key, clip_class_name, path):
        
        self.clip_info[key] = (clip_class_name, path)
        self.clip_counts[clip_class_name] += 1
        
        if clip_class_name is not None and \
           clip_class_name.startswith('Call.'):
            
            self.unreclassified_subclassified_call_paths.add(path)
        

    def log_stats(self):
        
        self._log_space()
        self._log_performance()
        
        self._log_counts(
                     
            ('escaped clip files', self.num_escaped_files),
            
            ('clip files in ignored directories', self.num_ignored_dir_files),
            
            ('malformed clip file names',
             len(self.malformed_file_name_file_paths)),
                     
            ('date/time clip file names', self.num_date_time_file_names),
            
            ('resolved elapsed time clip file names',
             self.num_resolved_file_names),
                     
            ('unresolved elapsed time clip file names',
             self.num_unresolved_file_names))
                     
        self._log_counts(
                    
            ('misplaced clip files',
             _aggregate_counts(self.misplaced_file_counts)),
        
            ('clip file names with bad detector names',
             self.num_bad_detector_name_file_names),
        
            ('clip files with nonexistent times near DST start',
             _aggregate_counts(self.nonexistent_time_file_counts)),
            
            ('clip files with ambiguous times near DST end',
             _aggregate_counts(self.ambiguous_time_file_counts)))
            
        self._log_counts(

            ('clip file repetitions', self.num_file_repetitions),
            
            ('duplicate classifications',
             len(self.duplicate_classification_path_pairs)),

            ('consistent reclassifications',
             self.num_consistent_reclassifications),

            ('inconsistent reclassifications',
             len(self.inconsistent_reclassifications)))
        
        # total number of calls
        self._log_total_num_calls()
        
        # clip counts by clip class
        self._log_count_dict('Clip counts by clip class:', self.clip_counts)
        
        # numbers of consistent reclassifications by less specific call class
        self._log_count_dict(
            'Numbers of reclassifications to more specific classes:',
            self.consistent_reclassification_counts)
        
        self._log_counts(
            ('clip files classified as Call.* but not also as Call',
             len(self.unreclassified_subclassified_call_paths)))
        
        self._log_counts(
            ('unreadable clip files', self.num_unreadable_files),
            ('archive add errors', self.num_add_errors))
        
        # directories containing misplaced files
        self._log_misplaced_file_dir_paths()
            
        # files with malformed names
        self._log_paths(
            'clip files with malformed names',
            self.malformed_file_name_file_paths)
        
        # directories containing file names with bad detector names
        self._log_paths(
            'directories containing file names with bad detector names',
            self.bad_detector_name_dir_paths)
        
        # directories containing files with nonexistent times near DST start
        self._log_nonexistent_time_dir_paths()
            
        # directories containing files with ambiguous times near DST end
        self._log_ambiguous_time_dir_paths()
            
        # examples of resolved elapsed times
        self._log_resolved_times()
        
        # directories containing unresolved elapsed time file names
        self._log_paths(
            'directories containing unresolved elapsed time clip file names',
            self.unresolved_file_name_dir_paths)
            
        self._log_paths(
            'clip files classified as Call.* but not also as Call',
            self.unreclassified_subclassified_call_paths)
        
        self._log_path_pairs(
            'clip files classified identically',
            self.duplicate_classification_path_pairs)
            
        self._log_path_pairs(
            'clip files classified inconsistently',
            self.inconsistent_reclassifications)

        
    def _log_space(self, num_lines=2):
        for _ in xrange(num_lines):
            self._log('')
                
              
    def _log_counts(self, *args):
        
        counts = [count for _, count in args]
        
        if any(counts):
            
            self._log_space()
            
            for pair in args:
                self._log_count(*pair)
    
    
    def _log_count(self, description, count):
        if count != 0:
            self._log('Number of {:s}: {:d}'.format(description, count))
    
    
    def _log_count_dict(self, message, counts):
        
        total_count = _aggregate_counts(counts)
        
        if total_count != 0:
            
            self._log_space()
            
            self._log(message)
            
            keys = counts.keys()
            keys.sort()
            
            for key in keys:
                count = counts[key]
                if count != 0:
                    self._log('    {:s} {:d}'.format(str(key), count))
                
                
    def _log_performance(self):
        
        num_files = self.total_num_files
        seconds = int(round(time.time() - self.start_time))
        
        if seconds == 0:
            f = 'Processed {:d} clip files in {:d} seconds.'
            args = (num_files, seconds)
            
        else:
            f = ('Processed {:d} clip files in {:d} seconds, {:d} files '
                 'per second.')
            rate = int(round(num_files / float(seconds)))
            args = (num_files, seconds, rate)
            
        self._log(f.format(*args))
                    
    
    def _log_total_num_calls(self):
        self._log_space()
        predicate = lambda k: k is not None and k.startswith('Call')
        num_calls = _aggregate_counts(self.clip_counts, predicate)
        self._log(
            'Total number of distinct call files: {:d}'.format(num_calls))
        
        
    def _log_misplaced_file_dir_paths(self):
        
        paths = self.misplaced_file_counts.keys()
        
        if len(paths) != 0:
            
            self._log_space()
            
            f = 'Paths ({:d}) of directories containing misplaced clip files:'
            self._log(f.format(len(paths)))
            
            paths.sort()
                      
            for path in paths:
                
                num_misplaced_files = self.misplaced_file_counts[path]
                total_num_files = _count_clip_files(path, recursive=False)
                
                self._log(
                    '{:s} ({:d} of {:d} files)'.format(
                        self._rel(path), num_misplaced_files, total_num_files))
            
            
    def _log_paths(self, description, paths):
        
        if len(paths) != 0:
            
            self._log_space()
            
            f = 'Paths ({:d}) of {:s}:'
            self._log(f.format(len(paths), description))
                    
            paths = [self._rel(p) for p in paths]
            paths.sort()
            for path in paths:
                self._log(path)
            
            
    def _log_nonexistent_time_dir_paths(self):
        self._log_bad_time_dir_paths('nonexistent', 'start')


    def _log_bad_time_dir_paths(self, name, point):
        
        attribute_name = '{:s}_time_file_counts'.format(name)
        counts = getattr(self, attribute_name)
        total_count = _aggregate_counts(counts)
        
        if total_count != 0:
            
            self._log_space()
            
            f = ('Paths ({:d}) of directories containing clip files with '
                 '{:s} times near DST {:s}:')
            self._log(f.format(len(counts), name, point))
            
            pairs = counts.items()
            pairs.sort()
            
            for path, count in pairs:
                f = '{:s} ({:d} files)'
                self._log(f.format(self._rel(path), count))


    def _log_ambiguous_time_dir_paths(self):
        self._log_bad_time_dir_paths('ambiguous', 'end')


    def _log_resolved_times(self):
        
        if len(self.resolved_times) != 0:
            
            self._log_space()
            
            self._log('Examples of resolved times:')
            
            keys = self.resolved_times.keys()
            keys.sort()
            
            for key in keys:
                
                station_name, night = key
                delta_time, time = self.resolved_times[key]
                
                self._log(
                    station_name + ' ' + str(night) + ': ' +
                    str(delta_time) + ' ' + str(time))
            
            
    def _log_path_pairs(self, description, pairs):
        
        if len(pairs) != 0:
            
            self._log_space()
            
            f = 'Pairs ({:d}) of {:s}:'
            self._log(f.format(len(pairs), description))
            
            pairs = [(self._rel(p), self._rel(q)) for p, q in pairs]
            pairs.sort()
            for pair in pairs:
                self._log(str(pair))


def _is_month_before(year, month, date):
    
    # Increment month.
    month += 1
    if month == 13:
        month = 1
        year += 1
        
    return datetime.date(year, month, 1) <= date


def _is_month_after(year, month, date):
    return datetime.date(year, month, 1) > date


def _create_set(collection):
    return None if collection is None else frozenset(collection)

    
def _count_clip_files(dir_path, recursive=True):
    count = 0
    for dir_path, subdir_names, file_names in os.walk(dir_path):
        for name in file_names:
            if file_name_utils.is_clip_file_name(name):
                count += 1
        if not recursive:
            del subdir_names[:]
    return count


def _aggregate_counts(counts, key_predicate=None):

    total = 0
            
    for key, count in counts.iteritems():
        if key_predicate is None or key_predicate(key):
            total += count
                
    return total

         
class _Logger(object):
    
    
    def __init__(self, verbose, root_dir_path):
        self.verbose = verbose
        self.root_dir_path = root_dir_path
        self.indentation = ''
        self.indentation_increment = 4
        
        
    def indent(self):
        self.indentation += ' ' * self.indentation_increment
        
        
    def unindent(self):
        if len(self.indentation) >= self.indentation_increment:
            self.indentation = self.indentation[:-self.indentation_increment]
        
            
    def log(self, message):
        print(self.indentation + message)
            
            
    def indent_v(self):
        if self.verbose:
            self.indent()
        
        
    def unindent_v(self):
        if self.verbose:
            self.unindent()
            
            
    def log_v(self, message):
        if self.verbose:
            self.log(message)
        
        
if __name__ == '__main__':
    _main()
