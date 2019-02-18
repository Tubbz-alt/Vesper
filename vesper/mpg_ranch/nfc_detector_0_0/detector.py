"""
Module containing MPG Ranch nocturnal flight call (NFC) detector.

The detector looks for NFCs in a single audio input channel by scoring
a sequence of input records, producing a clip when the score rises above
a threshold. The input records typically overlap. For each input record,
the detector computes a spectrogram and applies a convolutional neural
network to the spectrogram to obtain a score.

The `TseepDetector` and `ThrushDetector` classes of this module are
configured to detect tseep and thrush NFCs, respectively.
"""


import logging
# import time

import numpy as np
import resampy
import tensorflow as tf

from vesper.util.detection_score_file_writer import DetectionScoreFileWriter
from vesper.util.sample_buffer import SampleBuffer
from vesper.util.settings import Settings
import vesper.mpg_ranch.nfc_coarse_classifier_3_0.classifier_utils \
    as classifier_utils
import vesper.mpg_ranch.nfc_coarse_classifier_3_0.dataset_utils \
    as dataset_utils
import vesper.util.signal_utils as signal_utils


_TSEEP_SETTINGS = Settings(
    clip_type='Tseep',
    input_chunk_size=3600,
    hop_size=50,
    threshold=.9,
    min_separation=.2,
    initial_clip_padding=.1,
    clip_duration=.4
)

_THRUSH_SETTINGS = Settings(
    clip_type='Thrush',
    input_chunk_size=3600,
    hop_size=50,
    threshold=.9,
    min_separation=.3,
    initial_clip_padding=.2,
    clip_duration=.6
)


# Constants controlling detection score output. The output is written to
# a stereo audio file with detector audio input samples in one channel
# and detection scores in the other. It is useful for detector debugging,
# but should be disabled in production.
_SCORE_OUTPUT_ENABLED = False
_SCORE_FILE_PATH_FORMAT = '/Users/harold/Desktop/{} Detector Scores.wav'
_SCORE_OUTPUT_START_OFFSET = 3600   # seconds
_SCORE_OUTPUT_DURATION = 1000       # seconds
_SCORE_SCALE_FACTOR = 10000


class _Detector:
    
    """
    MPG Ranch NFC detector.
    
    An instance of this class operates on a single audio channel. It has a
    `detect` method that takes a NumPy array of samples. The method can be
    called repeatedly with consecutive sample arrays. The `complete_detection`
    method should be called after the final call to the `detect` method.
    During detection, each time the detector detects a clip it notifies
    a listener by invoking the listener's `process_clip` method. The
    `process_clip` method must accept two arguments, the start index and
    length of the detected clip.
    
    See the `_TSEEP_SETTINGS` and `_THRUSH_SETTINGS` objects above for
    settings that make a `_Detector` detect higher-frequency and
    lower-frequency NFCs, respectively, using the MPG Ranch tseep and
    thrush coarse classifiers. The `TseepDetector` and `ThrushDetector`
    classes of this module subclass the `_Detector` class with fixed
    settings, namely `_TSEEP_SETTINGS` and  `_THRUSH_SETTINGS`, respectively.
    """
    
    
    def __init__(
            self, settings, input_sample_rate, listener,
            extra_thresholds=None):
        
        # Suppress TensorFlow INFO and DEBUG log messages.
        tf.logging.set_verbosity(tf.logging.WARN)
        
        self._settings = settings
        self._input_sample_rate = input_sample_rate
        self._listener = listener
        
        s2f = signal_utils.seconds_to_frames
        
        s = self._settings
        fs = self._input_sample_rate
        self._input_buffer = None
        self._input_chunk_size = s2f(s.input_chunk_size, fs)
        self._thresholds = self._get_thresholds(extra_thresholds)
        self._min_separation = s.min_separation
        self._clip_start_offset = -s2f(s.initial_clip_padding, fs)
        self._clip_length = s2f(s.clip_duration, fs)
        
        self._input_chunk_start_index = 0
        
        self._classifier_settings = self._load_classifier_settings()
        self._estimator = self._create_estimator()
        
        s = self._classifier_settings
        fs = s.waveform_sample_rate
        self._classifier_sample_rate = fs
        self._classifier_waveform_length = s2f(s.waveform_duration, fs)
        fraction = self._settings.hop_size / 100
        self._hop_size = s2f(fraction * s.waveform_duration, fs)
        
        if _SCORE_OUTPUT_ENABLED:
            file_path = _SCORE_FILE_PATH_FORMAT.format(settings.clip_type)
            self._score_file_writer = DetectionScoreFileWriter(
                file_path, self._input_sample_rate, _SCORE_SCALE_FACTOR,
                self._hop_size, _SCORE_OUTPUT_START_OFFSET,
                _SCORE_OUTPUT_DURATION)
        
#         settings = self._classifier_settings.__dict__
#         names = sorted(settings.keys())
#         for name in names:
#             print('{}: {}'.format(name, settings[name]))
        
        
    @property
    def settings(self):
        return self._settings
    
    
    @property
    def input_sample_rate(self):
        return self._input_sample_rate
    
    
    @property
    def listener(self):
        return self._listener
    
    
    def _get_thresholds(self, extra_thresholds):
        thresholds = set([self._settings.threshold])
        if extra_thresholds is not None:
            thresholds |= set(extra_thresholds)
        return sorted(thresholds)
    
    
    def _load_classifier_settings(self):
        s = self._settings
        path = classifier_utils.get_settings_file_path(s.clip_type)
        logging.info('Loading classifier settings from "{}"...'.format(path))
        return Settings.create_from_yaml_file(path)
        
        
    def _create_estimator(self):
        s = self._settings
        path = classifier_utils.get_tensorflow_model_dir_path(s.clip_type)
        logging.info((
            'Creating TensorFlow estimator from saved model in directory '
            '"{}"...').format(path))
        return tf.contrib.estimator.SavedModelEstimator(str(path))

    
    def _create_dataset(self):
        s = self._classifier_settings
        return dataset_utils.create_spectrogram_dataset_from_waveforms_array(
            self._waveforms, dataset_utils.DATASET_MODE_INFERENCE, s,
            batch_size=64, feature_name=s.model_input_name)
    
    
    def detect(self, samples):
        
        if self._input_buffer is None:
            self._input_buffer = SampleBuffer(samples.dtype)
             
        self._input_buffer.write(samples)
        
        self._process_input_chunks()
            
            
    def _process_input_chunks(self, process_all_samples=False):
        
        # Process as many chunks of input samples of size
        # `self._input_chunk_size` as possible.
        while len(self._input_buffer) >= self._input_chunk_size:
            chunk = self._input_buffer.read(self._input_chunk_size)
            self._process_input_chunk(chunk)
            
        # If indicated, process any remaining input samples as one chunk.
        # The size of the chunk will differ from `self._input_chunk_size`.
        if process_all_samples and len(self._input_buffer) != 0:
            chunk = self._input_buffer.read()
            self._process_input_chunk(chunk)
            
            
    def _process_input_chunk(self, samples):
        
        input_length = len(samples)
        
        if self._classifier_sample_rate != self._input_sample_rate:
             
            samples = resampy.resample(
                samples, self._input_sample_rate, self._classifier_sample_rate,
                filter='kaiser_fast')
            
        self._waveforms = _get_analysis_records(
            samples, self._classifier_waveform_length, self._hop_size)
        
#         print('Scoring chunk waveforms...')
#         start_time = time.time()
         
        scores = classifier_utils.score_dataset_examples(
            self._estimator, self._create_dataset)
        
#         elapsed_time = time.time() - start_time
#         num_waveforms = self._waveforms.shape[0]
#         rate = num_waveforms / elapsed_time
#         print((
#             'Scored {} waveforms in {:.1f} seconds, a rate of {:.1f} '
#             'waveforms per second.').format(
#                 num_waveforms, elapsed_time, rate))
        
        if _SCORE_OUTPUT_ENABLED:
            self._score_file_writer.write(samples, scores)
         
        for threshold in self._thresholds:
            peak_indices = self._find_peaks(scores, threshold)
            self._notify_listener_of_clips(
                peak_indices, input_length, threshold)
        
        self._input_chunk_start_index += input_length
            

    def _find_peaks(self, scores, threshold):
        
        if self._min_separation is None:
            min_separation = None
            
        else:
            
            # Get min separation in hops.
            hop_size = signal_utils.get_duration(
                self._hop_size, self._classifier_sample_rate)
            min_separation = self._settings.min_separation / hop_size
        
        peak_indices = signal_utils.find_peaks(
            scores, threshold, min_separation)
        
#         print(
#             'Found {} peaks in {} scores.'.format(
#                 len(peak_indices), len(scores)))

        return peak_indices
        
            
    def _notify_listener_of_clips(self, peak_indices, input_length, threshold):
        
        # print('Clips:')
        
        start_offset = self._input_chunk_start_index + self._clip_start_offset
        peak_indices *= self._hop_size
        
        for i in peak_indices:
            
            # Convert classification index to input index, accounting
            # for difference between classifier sample rate and input
            # sample rate.
            t = signal_utils.get_duration(i, self._classifier_sample_rate)
            i = signal_utils.seconds_to_frames(t, self._input_sample_rate)
            
            clip_start_index = i + start_offset
            clip_end_index = clip_start_index + self._clip_length
            chunk_end_index = self._input_chunk_start_index + input_length
            
            if clip_start_index < 0:
                logging.warning(
                    'Rejected clip that started before beginning of '
                    'recording.')
                
            elif clip_end_index > chunk_end_index:
                # clip might extend past end of recording, since it extends
                # past the end of this chunk (we do not know whether or
                # not the current chunk is the last)
                
                logging.warning(
                    'Rejected clip that ended after end of recording chunk.')
                
            else:
                # all clip samples are in the recording interval extending
                # from the beginning of the recording to the end of the
                # current chunk
                
                # print(
                #     '    {} {}'.format(clip_start_index, self._clip_length))
                
                self._listener.process_clip(
                    clip_start_index, self._clip_length, threshold)
        

    def complete_detection(self):
        
        """
        Completes detection after the `detect` method has been called
        for all input.
        """
        
        self._process_input_chunks(process_all_samples=True)
            
        self._listener.complete_processing()
        
        if _SCORE_OUTPUT_ENABLED:
            self._score_file_writer.close()


# TODO: The following two functions were copied from
# vesper.util.time_frequency_analysis_utils. They should probably both
# be public, and in a more general-purpose module.


def _get_analysis_records(samples, record_size, hop_size):

    """
    Creates a sequence of hopped sample records from the specified samples.

    This method uses a NumPy array stride trick to create the desired
    sequence as a view of the input samples that can be created at very
    little cost. The caveat is that the view should only be read from,
    and never written to, since when the hop size is less than the
    record size the view's records overlap in memory.

    The trick is from the `_fft_helper` function of the
    `scipy.signal.spectral` module of SciPy.
    """

    # Get result shape.
    num_samples = samples.shape[-1]
    num_vectors = _get_num_analysis_records(num_samples, record_size, hop_size)
    shape = samples.shape[:-1] + (num_vectors, record_size)

    # Get result strides.
    stride = samples.strides[-1]
    strides = samples.strides[:-1] + (hop_size * stride, stride)

    return np.lib.stride_tricks.as_strided(samples, shape, strides)


def _get_num_analysis_records(num_samples, record_size, hop_size):

    if record_size <= 0:
        raise ValueError('Record size must be positive.')

    elif hop_size <= 0:
        raise ValueError('Hop size must be positive.')

    elif hop_size > record_size:
        raise ValueError('Hop size must not exceed record size.')

    if num_samples < record_size:
        # not enough samples for any records

        return 0

    else:
        # have enough samples for at least one record

        overlap = record_size - hop_size
        return (num_samples - overlap) // hop_size


class TseepDetector(_Detector):
    
    
    extension_name = 'MPG Ranch Tseep Detector 0.0'
    
    
    def __init__(self, sample_rate, listener, extra_thresholds=None):
        super().__init__(
            _TSEEP_SETTINGS, sample_rate, listener, extra_thresholds)

    
class ThrushDetector(_Detector):
     
     
    extension_name = 'MPG Ranch Thrush Detector 0.0'
     
     
    def __init__(self, sample_rate, listener, extra_thresholds=None):
        super().__init__(
            _THRUSH_SETTINGS, sample_rate, listener, extra_thresholds)