"""Module containing class `Importer`."""


from __future__ import print_function

from collections import namedtuple
import datetime
import itertools
import logging
import os
import re

import pytz

import vesper.util.sound_utils as sound_utils
import vesper.util.time_utils as time_utils


'''
Remaining issues:
* comments not included
* effort data
* station locations
* clip class descriptions
* sunrise/sunset data
'''


# TODO: Implement an indenting `logging` message formatter, so that
# logging code does not have to format messages with an `_indent`
# method.


# We assume that the time zone is US/Mountain for all times that occur
# in input file names.
_TIME_ZONE = pytz.timezone('US/Mountain')


_identity = lambda s: s
_capitalize = lambda s: s.capitalize()
_parse_date = time_utils.parse_date
_parse_date6 = lambda mm, dd, yy: _parse_date(yy, mm, dd)
_parse_time = time_utils.parse_time
_parse_dur = time_utils.parse_time_delta


_FieldFormat = namedtuple(
    '_FieldFormat', ('name', 'field_name', 're', 'num_subfields', 'parser'))
    
_FIELD_FORMATS = dict((t[0], _FieldFormat(*t)) for t in (
    ('class', 'clip_class_name', r'([a-zA-Z_]+)', 1, _identity),
    ('station', 'station_name', r'(baldy|flood|ridge|sheep)', 1,
     _capitalize),
    ('detector', 'detector_name', r'(Tseep|Thrush|Manual)', 1, _capitalize),
    ('date6', 'monitoring_start_date', r'(\d{2})(\d{2})(\d{2})', 3,
     _parse_date6),
    ('time6', 'monitoring_start_time', r'(\d{2})(\d{2})(\d{2})', 3,
     _parse_time),
    ('time4', 'monitoring_start_time', r'(\d{2})(\d{2})', 2, _parse_time),
    ('dur6', 'monitoring_duration', r'(\d{2})(\d{2})(\d{2})', 3, _parse_dur),
    ('dur4', 'monitoring_duration', r'(\d{2})(\d{2})', 2, _parse_dur),
    ('interior_comment', 'interior_comment', r'(.+)', 1, _identity),
    ('second_dur', 'second_dur', r'(\d{2})(\d{2})(\d{2})', 3, _parse_dur),
    ('elapsed7', 'clip_start_time', r'(\d{3})\.(\d{2})\.(\d{2})', 3,
     _parse_dur),
    ('elapsed6', 'clip_start_time', r'(\d{2})(\d{2})(\d{2})', 3, _parse_dur),
    ('num2', 'clip_num', r'(\d{2})', 1, int),
    ('comment', 'comment', r'(.+)', 1, _identity)
))


_FIELD_NAMES = (
    'station_name', 'detector_name', 'monitoring_start_date',
    'monitoring_start_time', 'monitoring_duration', 'interior_comment',
    'second_dur', 'clip_start_time', 'clip_num', 'clip_class_name',
    'comment')

_ClipInfo = namedtuple('_ClipInfo', _FIELD_NAMES)

_DEFAULT_CLIP_INFO = _ClipInfo(*([None] * len(_FIELD_NAMES)))
    

class _Parser(object):
    
    """Parser for a single file name format."""
    
    
    def __init__(self, spec):
        super(_Parser, self).__init__()
        self._field_formats = [_FIELD_FORMATS[name] for name in spec.split()]
        res = [f.re for f in self._field_formats]
        self._re = re.compile(r'^' + '_'.join(res) + '\.wav$')
        
        
    def parse(self, file_name):
   
        m = self._re.match(file_name)
         
        if m is None:
            return None
         
        else:
            
            subfield_values = m.groups()
            field_values = {}
            i = 0
            
            for f in self._field_formats:
                
                n = f.num_subfields
                
                field_values[f.field_name] = \
                    f.parser(*subfield_values[i:i + n])
                    
                i += n
                
            return _DEFAULT_CLIP_INFO._replace(**field_values)
            
        
def _add_comment_parser_specs(*args):
    return list(itertools.chain(*[(p, p + ' comment') for p in args]))


# Note that through the action of the `_add_comment_parsers` function,
# each of the parser specifications listed explicitly below is followed
# in `_PARSERS` by one that is identical to it except that it includes
# a trailing comment. Thus, when one of the explicitly-listed
# specifications is a prefix of one of the other specifications, the
# shorter one must follow the longer one. Otherwise nothing will ever
# be parsed with the longer one, since the extra field or fields it
# describes will always be parsed as part of the trailing comment of
# the implicit, comment-including version of the shorter specification.
_CSD = 'class station date6 '
_PARSER_SPECS = _add_comment_parser_specs(
    _CSD + 'time6 dur6 detector elapsed7 num2',
    _CSD + 'time6 dur6 detector elapsed7',
    _CSD + 'time4 dur4 detector elapsed7 num2',
    _CSD + 'time4 dur4 detector elapsed7',
    _CSD + 'time6 detector elapsed7 num2',
    _CSD + 'time4 detector elapsed7 num2',
    _CSD + 'time4 detector elapsed7',
    _CSD + 'time4 detector elapsed6',
    _CSD + 'time6 dur6 second_dur detector elapsed7 num2',
    _CSD + 'time6 dur6 interior_comment second_dur detector elapsed7 num2',
    _CSD + 'time6 dur6 interior_comment detector elapsed7 num2',
)
_PARSERS = [_Parser(s) for s in _PARSER_SPECS]


def _parse_file_name(name):
    
    for parser in _PARSERS:
        result = parser.parse(name)
        if result is not None:
            return result
        
    # If we arrive here, none of the parsers could parse the file name.
    _raise_value_error(name)


def _raise_value_error(file_name, message=None):
    
    if message is None:
        message = 'Bad clip file name "{:s}".'.format(file_name)
    else:
        message = '{:s} in clip file name "{:s}".'.format(message, file_name)
        
    raise ValueError(message)


_IGNORED_FILE_NAMES = frozenset(
    ['.DS_Store', 'Thumbs.db', 'desktop.ini', 'keylist.txt'])


class Importer:
    
    """Importer for MPG Ranch 2012-2014 nocturnal flight call data."""
    
    
    def import_(self, source_dir_path, archive):
        
        self._source_dir_path = source_dir_path
        self._archive = archive

        self._indent_level = 0
        self._indent_size = 4
        self._indentation = ''
        
        self._station_names = frozenset(s.name for s in archive.stations)
        self._detector_names = frozenset(d.name for d in archive.detectors)
        self._clip_class_names = \
            frozenset(c.name for c in archive.clip_classes)

        self._num_parsed_file_paths = 0
        self._ignored_file_paths = set()
        self._bad_file_paths = set()
        self._unreadable_file_paths = set()
        self._num_add_errors = 0
        
        self._encountered_station_names = set()
        self._encountered_detector_names = set()
        self._encountered_clip_class_names = set()

        dir_names = [os.path.basename(source_dir_path)]
        self._walk(source_dir_path, dir_names)
        
        
    def _walk(self, dir_path, dir_names):
        
        for _, subdir_names, file_names in os.walk(dir_path):
            
            for file_name in file_names:
                file_path = os.path.join(dir_path, file_name)
                self._visit_file(file_path, dir_names, file_name)
                    
            for subdir_name in subdir_names:
                
                subdir_path = os.path.join(dir_path, subdir_name)
                names = dir_names + [subdir_name]
                
                self._visit_dir(subdir_path, names)
                
                self._increase_indentation()
                self._walk(subdir_path, names)
                self._decrease_indentation()
                
            # stop os.walk from visiting subdirectories
            del subdir_names[:]


    def _increase_indentation(self):
        self._increment_indentation(1)
        
        
    def _increment_indentation(self, i):
        self._indent_level += i
        n = self._indent_level * self._indent_size
        self._indentation = ' ' * n
        
        
    def _decrease_indentation(self):
        self._increment_indentation(-1)
        
        
    def _indent(self, s):
        return self._indentation + s
    
    
    def _visit_file(self, file_path, dir_names, file_name):
        
        try:
            info = _parse_file_name(file_name)
            
        except ValueError:
            
            if file_name in _IGNORED_FILE_NAMES:
                self._ignored_file_paths.add(file_path)
            else:
                self._bad_file_paths.add(file_path)
                
        else:
            
            self._encountered_station_names.add(info.station_name)
            self._encountered_detector_names.add(info.detector_name)
            self._encountered_clip_class_names.add(info.clip_class_name)
            
            time = self._get_clip_time(info)
            if time is None:
                return
            
            sound = self._get_clip_sound(file_path)
            if sound is None:
                return
            
            clip_class_name = _correct_clip_class_name(info.clip_class_name)
            
            try:
                self._archive.add_clip(
                    info.station_name, info.detector_name, time, sound,
                    clip_class_name)
            
            except Exception as e:
                m = self._indent('Error adding clip from "{:s}": {:s}')
                logging.error(m.format(self._rel(file_path), str(e)))
                self._num_add_errors += 1
                
            self._num_parsed_file_paths += 1


    def _get_clip_time(self, info):
        
        # Get monitoring start time.
        date = info.monitoring_start_date
        time = info.monitoring_start_time
        dt = datetime.datetime.combine(date, time)
        
        # Correct monitoring start time if needed.
#         if info.interior_comment == 'add':
#             dt += info.second_dur
            
        # Add clip start time.
        dt += info.clip_start_time
        
        # Add offset for clip num if needed.
        if info.clip_num is not None and info.clip_num != 0:
            dt += datetime.timedelta(microseconds=info.clip_num * 100000)

        # Convert naive time to UTC.
        #
        # We must specify `is_dst=None` here for the `localize` method
        # to raise an exception if the naive time is either nonexistent
        # or ambiguous. If we omit the `is_dst` argument the method will
        # *not* raise an exception if the naive time is nonexistent or
        # ambiguous, but rather yield the specified time with the
        # standard time (as opposed to daylight time) offset.
        #
        # We do not handle exceptions here since the 2012-2014 data
        # that this importer is designed to process are all from
        # periods when DST was in effect.
        try:
            dt = _TIME_ZONE.localize(dt, is_dst=None)
        except pytz.NonExistentTimeError:
            raise
        except pytz.AmbiguousTimeError:
            raise
        
        return dt.astimezone(pytz.utc)
    
    
    def _get_clip_sound(self, file_path):
        
        try:
            return sound_utils.read_sound_file(file_path)
            
        except Exception:
            self._unreadable_file_paths.add(file_path)
            return None
    
    
    def _rel(self, path):
        return path[len(self._source_dir_path) + 1:]
    
    
    def _visit_dir(self, dir_path, dir_names):
        logging.info(self._indent('dir "{:s}"'.format(dir_names[-1])))
        
        
    def log_summary(self):
        
        sfp = self._show_file_path
        
        logging.info('')
        self._show_items('Ignored files:', self._ignored_file_paths, sfp)
        
        logging.info('')
        self._show_items(
            'File names that could not be parsed:', self._bad_file_paths, sfp)
        
        logging.info('')
        self._show_items('Unreadable files:', self._unreadable_file_paths, sfp)
        
        logging.info('')
        self._show_items('Station names:', self._encountered_station_names)
        
        logging.info('')
        self._show_items('Detector names:', self._encountered_detector_names)
        
        logging.info('')
        self._show_clip_class_names()
        
        logging.info('')
        
        good = self._num_parsed_file_paths
        bad = len(self._bad_file_paths)
        ignored = len(self._ignored_file_paths)
        
        logging.info('{:d} files visited'.format(good + bad + ignored))
        logging.info('{:d} file names were parsed'.format(good))
        logging.info('{:d} file names could not be parsed'.format(bad))
        logging.info('{:d} file names were ignored'.format(ignored))
        logging.info(
            '{:d} clip add operations failed'.format(self._num_add_errors))
        


    def _show_items(self, title, items, show=None):
        
        if show is None:
            show = self._show_item
            
        logging.info(title)
        
        items = sorted(items)
        
        self._increase_indentation()
        
        if len(items) == 0:
            logging.info(self._indent('None'))
            
        else:
            for item in items:
                show(item)
            
        self._decrease_indentation()


    def _show_item(self, item):
        logging.info(self._indent(item))
        
        
    def _show_file_path(self, path):
        (dir_path, file_name) = os.path.split(path)
        logging.info(self._indent('{:s} ({:s})'.format(file_name, dir_path)))


    def _show_clip_class_names(self):
        
        logging.info('Clip class names:')
        
        names = sorted(self._encountered_clip_class_names)
        
        self._increase_indentation()
        
        if len(names) == 0:
            logging.info(self._indent('None'))
            
        else:
            
            for name in names:
                corrected_name = _correct_clip_class_name(name)
                logging.info(self._indent(
                    '{:s}: {:s}'.format(name, corrected_name)))
                
        self._decrease_indentation()
        

_CALL_CLIP_CLASS_NAME_CORRECTIONS = {
    'bhgr_type': 'BHGR',
    'ccbr': 'CCSP_BRSP',
    'ccsp': 'CCSP_BRSP',
    'ccsp_brsp': 'CCSP_BRSP',
    'DbUp': 'DoubleUp',
    'lalo_type': 'LALO',
    'lisp_type': 'LISP',
    'mgwa_type': 'MGWA',
    'othe': 'Other',
    'other': 'Other',
    'peep': 'Peep',
    'pynu_lbdo': 'PYNU_LBDO',
    'sdup': 'DoubleUp',
    'ShDbUp': 'DoubleUp',
    'sosp_type': 'SOSP',
    'spso': 'SPSA_SOSA',
    'unkn': 'Unknown',
    'unkw': 'Unknown',
    'vewe': 'VEER_WETA',
    'weak': 'Weak',
    'zeep': 'Zeep'
}


def _correct_clip_class_name(name):
    
    if name is None:
        return None
    
    elif name == 'nois':
        return 'Noise'
    
    else:
        # name is neither `None` nor `'nois'`
        
        try:
            name = _CALL_CLIP_CLASS_NAME_CORRECTIONS[name]
        
        except KeyError:
            # no explicit correction available
            
            if len(name) == 4 and name == name.lower():
                # name comprises four lower-case characters
                
                name = name.upper()
                
        return 'Call.' + name