"""Trains an NFC species classifier."""


from __future__ import print_function
import cPickle as pickle
import os.path
import random
import sys

import numpy as np
import pandas as pd
from sklearn import cross_validation
from sklearn import svm

from vesper.archive.archive import Archive
from vesper.util.bunch import Bunch
import vesper.util.data_windows as data_windows
import vesper.util.nfc_classification_utils as nfc_classification_utils
import vesper.util.signal_utils as signal_utils


# NOTE: The C and gamma SVM hyperparameter values for both the coarse
# and species classifiers were chosen by brief hand experimentation.
# While this was quick it is probably suboptimal, and it is also
# methodologically unsound to report test results on data that were
# used for the hyperparameter value selection. We should revise our
# training and test procedure to:
#
# (1) Divide data into training and test set.
#
# (2) Select hyperparameter values with cross validation using training
#     data only.
#
# (3) Train final classifier on training data.
#
# (4) Test final classifier on test data.
    

_DIR_PATH = r'C:\Users\Harold\Desktop\NFC\Data\MPG Ranch'
_ARCHIVE_NAME = 'MPG Ranch 2012-2014'
_PICKLE_FILE_NAME = 'Call Clips.pkl'


_CONFIGS = {
            
    'Tseep': Bunch(
        detector_name = 'Tseep',
#        clip_class_names = ['Call.WIWA', 'Call.CHSP'],
#        clip_class_names = [
#            'Call.WIWA', 'Call.CHSP', 'Call.WCSP', 'Call.VESP', 'Call.SAVS'],
        clip_class_names = [
            'Call.WIWA', 'Call.DoubleUp', 'Call.CHSP', 'Call.WCSP',
            'Call.VESP', 'Call.SAVS'],
        segment_duration = .12,
        num_cross_validation_folds=10,
        spectrogram_params=Bunch(
            window=data_windows.create_window('Hann', 110),
            hop_size=55,
            dft_size=128,
            ref_power=1),
        min_freq=4000,
        max_freq=10000,
        min_power=-10,
        max_power=65,
        pooling_block_size=(2, 2),
        include_norm_in_features=False,
        classifier_type='One Versus Rest',
        one_vs_rest_svc_params={
            'cache_size': 500,
            'kernel': 'rbf',
            'gamma': .001,
            'C': 10000.
        },
        one_vs_one_svc_params={
            'cache_size': 500,
            'kernel': 'rbf',
            'gamma': .001,
            'C': 10000.
        }),
            
    'Thrush': Bunch(
        detector_name = 'Thrush'
        )
            
}


def _main():
    
    # Seed random number generators so that script yields identical
    # results on repeated runs.
    random.seed(0)
    np.random.seed(0)
    
    config = _CONFIGS[sys.argv[1]]
    
    print('Getting call clips from archive...')
    clips = _get_clips_from_archive(config)
    print('Got {} clips.\n'.format(len(clips)))
    
    print('Extracting segments...')
    clips = _extract_clip_segments(clips, config)
    print('Extracted {} segments.\n'.format(len(clips)))
    
    print('Computing features...')
    clips = _compute_segment_features(clips, config)
    print()

    print('Pickling clips...')    
    _save_clips(clips)
    print()
    
    # Perform cross-validation training on clip folds.
    if config.num_cross_validation_folds != 0:
        _train_and_test_cv_classifiers(clips, config)
    
    print('Training classifier on all clips...')
    classifier = _train_classifier(clips, config)
    print()
    
    print('Saving classifier...')
    _save_classifier(classifier, config)
    print()
    
    print('Done.')
    
    
def _get_clips_from_archive(config):
    
    clips = _get_clips_list_from_archive(config.detector_name)
    clips = _create_clips_dataframe(clips, config)
    
    station_names = ['Floodplain', 'Sheep Camp', 'Ridge']
    clips = clips[clips['station'].isin(station_names)]
    clips = clips[clips['detector'] == 'Tseep']
    clips = clips[clips['clip_class'] != 'Noise']
    clips = clips[clips['selection'].notnull()]
    
    return clips
    
    
def _get_clips_list_from_archive(detector_name):
    archive_dir_path = _create_full_path(_ARCHIVE_NAME)
    archive = Archive(archive_dir_path)
    archive.open()
    clips = archive.get_clips(
        detector_name=detector_name, clip_class_name='Call*')
    archive.close()
    return clips


def _create_full_path(*parts):
    return os.path.join(_DIR_PATH, *parts)


def _create_clips_dataframe(clips, config):
    
    data = {
        'station': [c.station.name for c in clips],
        'detector': [c.detector_name for c in clips],
        'night': [c.night for c in clips],
        'start_time': [c.start_time for c in clips],
        'clip_class': [c.clip_class_name for c in clips],
        'samples': [c.sound.samples for c in clips],
        'sample_rate': [c.sound.sample_rate for c in clips],
        'selection': [c.selection for c in clips]
    }
    
    columns = [
        'station', 'detector', 'night', 'start_time', 'clip_class',
        'samples', 'sample_rate', 'selection']
    
    return pd.DataFrame(data, columns=columns)
        
        
def _extract_clip_segments(clips, config):
    
    # I suspect there is a more efficient way to do this with Pandas,
    # but I haven't found it yet (see the commented-out code below).
    clips['segment'] = [
        _extract_clip_segment(clip, config.segment_duration)
        for _, clip in clips.iterrows()]
        
    # Not sure why this doesn't work. The idea is to assign a `Series`
    # of NumPy arrays to the `'segment'` column. Unfortunately, though,
    # returning a NumPy array from `_extract_clip_segment` seems to mess
    # up the number of columns somewhere somehow. 
#     clips['segment'] = clips.apply(
#         _extract_clip_segment, axis=1, duration=config.segment_duration)
    
    # Eliminate rows of clips that were too short.
    clips = clips[clips['segment'].notnull()]
    
    return clips
    
    
def _extract_clip_segment(clip, duration):
    
    if clip['selection'] is None:
        return None
    
    else:
        
        selection_start_index, selection_length = clip['selection']
        selection_center_index = selection_start_index + selection_length // 2
        length = signal_utils.seconds_to_frames(duration, clip['sample_rate'])
        start_index = selection_center_index - length // 2
        
        if start_index < 0:
            return None
        
        else:
            
            samples = clip['samples']
            end_index = start_index + length
            
            if end_index > len(samples):
                return None
            
            else:
                return samples[start_index:end_index]


def _compute_segment_features(clips, config):
    
    pairs = [
        _compute_segment_features_aux(clip, config)
        for _, clip in clips.iterrows()]
    
    spectra, features = zip(*pairs)
    
    clips['spectra'] = list(spectra)
    clips['features'] = list(features)
    
    return clips

    
def _compute_segment_features_aux(clip, config):
    segment = Bunch(samples=clip['segment'], sample_rate=clip['sample_rate'])
    features, spectra, _ = \
        nfc_classification_utils.get_segment_features(segment, config)
    return (spectra, features)


def _save_clips(clips):
    file_path = _create_full_path(_PICKLE_FILE_NAME)
    clips.to_pickle(file_path)
    
    
# Three outputs, all pickle files.
#     single species classifiers 
#     coarse cross validation results (DataFrame, one row per fold, plus avg)
#     fine cross validation results (DataFrame, one row per fold/clip)


def _train_and_test_cv_classifiers(clips, config):
    
    results = []
    
    for fold_num, training_clips, test_clips in \
            _generate_clip_folds(clips, config):
            
        print((
            'Training classifier for cross-validation fold {} of '
            '{}...').format(fold_num, config.num_cross_validation_folds))
        
        # _show_clip_counts(all_training_clips, test_clips)
        
        classifier = _train_classifier(training_clips, config)
        
        if config.classifier_type == 'One Versus Rest':
            _test_single_species_cv_classifiers(
                classifier, training_clips, test_clips)

        fold_results = _test_cv_classifier(
            classifier, training_clips, test_clips)
                
        _show_cv_fold_results(fold_results)
        
        results.append(fold_results)
    
    _show_cv_results(results)
    
    return results
    

def _generate_clip_folds(clips, config):
    
    targets = _get_fold_targets(clips['clip_class'], config)
         
    num_folds = config.num_cross_validation_folds
    fold_num = 1
    
    for training_indices, test_indices in cross_validation.StratifiedKFold(
            targets, n_folds=num_folds, shuffle=True, random_state=0):
        
        training_clips = clips.iloc[training_indices]
        test_clips = clips.iloc[test_indices]
        yield (fold_num, training_clips, test_clips)
    
        fold_num += 1
        
        
def _get_fold_targets(clip_class_names, config):
    names = frozenset(config.clip_class_names)
    return np.array([
        name if name in names else 'Unclassified'
        for name in clip_class_names])
    
    
def _show_clip_counts(training_clips, test_clips):
    
    print(len(training_clips), len(test_clips))
    print()
    
    print('training clips:')
    print(training_clips['clip_class'].value_counts())
    print()
    
    print('test clips:')
    print(test_clips['clip_class'].value_counts())
    print()


def _train_classifier(clips, config):
    
    if config.classifier_type == 'One Versus One':
        return _train_one_vs_one_classifier(clips, config)
    else:
        return _train_one_vs_rest_classifier(clips, config)


def _train_one_vs_one_classifier(clips, config):
    features = _get_features_array(clips)
    targets = _get_classifier_targets(clips, config.clip_class_names)
    classifier = svm.SVC(**config.one_vs_one_svc_params)
    classifier.fit(features, targets)
    clip_class_names = np.unique(targets)
    return _Classifier(classifier, clip_class_names)


def _get_features_array(clips):
    
    # In the following, `clips['features']` is a Pandas `Series`.
    # If we do not convert the `Series` to a `list` before constructing
    # a NumPy array we wind up with a NumPy object array, with each
    # object a one-dimensional NumPy array, rather than a two-dimensional
    # NumPy array.
    return np.array(list(clips['features']))

   
def _get_classifier_targets(clips, clip_class_names):
    names = pd.Series(clips['clip_class'])
    unclassified = ~names.isin(clip_class_names)
    names[unclassified] = 'Unclassified'
    return np.array(names)


def _train_one_vs_rest_classifier(clips, config):
    
    single_species_classifiers = dict(
        (name, _train_single_species_classifier(name, clips, config))
        for name in config.clip_class_names)
    
    return _OneVsRestClassifier(single_species_classifiers)


def _train_single_species_classifier(clip_class_name, clips, config):
    features = _get_features_array(clips)
    targets = _get_single_species_classifier_targets(clips, clip_class_name)
    classifier = svm.SVC(**config.one_vs_rest_svc_params)
    classifier.fit(features, targets)
    return classifier


def _get_single_species_classifier_targets(clips, clip_class_name):
    return np.array([
        1 if name == clip_class_name else 0
        for name in clips['clip_class']])


def _test_single_species_cv_classifiers(
        classifier, training_clips, test_clips):
    
    test = _test_single_species_cv_classifier
    classifiers = classifier.single_species_classifiers
    clip_class_names = sorted(classifiers.keys())
    
    return dict(
        (name, test(classifiers[name], name, training_clips, test_clips))
        for name in clip_class_names)
    
    
def _test_single_species_cv_classifier(
        classifier, clip_class_name, training_clips, test_clips):
    
    training_targets, training_predictions = \
        _test_single_species_cv_classifier_aux(
            classifier, clip_class_name, training_clips, 'training')
        
    test_targets, test_predictions = \
        _test_single_species_cv_classifier_aux(
            classifier, clip_class_name, test_clips, 'test')
            
    return (training_targets, training_predictions,
            test_targets, test_predictions)
    
    
def _test_single_species_cv_classifier_aux(
        classifier, clip_class_name, clips, description):

    print('Testing {} classifier on {} clips...'.format(
              clip_class_name, description))

    targets, predictions = _test_single_species_classifier(
        classifier, clip_class_name, clips)
        
    # _show_test_results(targets, predictions)
    
    return (targets, predictions)

   
def _test_single_species_classifier(classifier, clip_class_name, clips):
    features = _get_features_array(clips)
    targets = _get_single_species_classifier_targets(clips, clip_class_name)
    predictions = classifier.predict(features)
    return (targets, predictions)


def _show_test_results(targets, predictions):
    
    tp, fn, fp, tn = _tally_classification_results(targets, predictions)
        
    fn_rate = 100 * fn / float(tp + fn)
    fp_rate = 100 * fp / float(tn + fp)
    
    print('{} {} {} {} {:.1f} {:.1f}'.format(
        tp, fn, fp, tn, fn_rate, fp_rate))


# TODO: Move this to `nfc_classification_utils`. There is redundant code
# in `train_nfc_coarse_classifier`.
def _tally_classification_results(targets, predictions):
    tp = ((targets == 1) & (predictions == 1)).sum()
    fn = ((targets == 1) & (predictions == 0)).sum()
    fp = ((targets == 0) & (predictions == 1)).sum()
    tn = ((targets == 0) & (predictions == 0)).sum()
    return (tp, fn, fp, tn)


def _test_cv_classifier(classifier, training_clips, test_clips):
    
    clip_class_names = classifier.clip_class_names
    
    training_targets, training_predictions = \
        _test_classifier(classifier, training_clips, clip_class_names)
        
    test_targets, test_predictions = \
        _test_classifier(classifier, test_clips, clip_class_names)
        
    return (training_targets, training_predictions, test_targets,
            test_predictions)


def _test_classifier(classifier, clips, clip_class_names):
    features = _get_features_array(clips)
    targets = _get_classifier_targets(clips, clip_class_names)
    predictions = classifier.predict(features)
    return (targets, predictions)

    
def _show_cv_fold_results(results):
    
#     training_targets, training_predictions = results[:2]
#     _show_confusion_matrix(
#         training_targets, training_predictions, 'Fold training')
    
    test_targets, test_predictions = results[2:]
    _show_confusion_matrix(test_targets, test_predictions, 'Fold test')


def _show_confusion_matrix(targets, predictions, prefix):
    print('{} confusion matrix:'.format(prefix))
    names = sorted(np.unique(targets))
    matrix = _compute_confusion_matrix(targets, predictions, names)
    for target in names:
        counts = [matrix[prediction][target] for prediction in names]
        print('    ', target, counts)
            
    
def _compute_confusion_matrix(targets, predictions, clip_class_names):
    names = clip_class_names
    n = len(names)
    counts = np.zeros((n, n), dtype='int32')
    matrix = pd.DataFrame(counts, columns=names, index=names)
    for target, prediction in zip(targets, predictions):
        matrix[prediction][target] += 1
    return matrix
    
    
def _show_cv_results(results):
    results = tuple([np.hstack(y) for y in zip(*results)])
    test_targets, test_predictions = results[2:]
    _show_confusion_matrix(test_targets, test_predictions, 'Overall test')
    
    
def _save_classifier(classifier, config):
    
    file_name = '{} Species Classifier.pkl'.format(config.detector_name)
    file_path = _create_full_path(file_name)
    
    print('Saving species classifier to file "{}".'.format(file_path))
    
    with open(file_path, 'wb') as file_:
        pickle.dump(classifier, file_)
        
    print()


class _Classifier(object):
    
    
    def __init__(self, classifier, clip_class_names):
        super(_Classifier, self).__init__()
        self._classifier = classifier
        self._clip_class_names = sorted(clip_class_names)
        
    
    @property
    def clip_class_names(self):
        return list(self._clip_class_names)
    
    
    def predict(self, features):
        return self._classifier.predict(features)
    
    
class _OneVsRestClassifier(object):
    
    
    def __init__(self, single_species_classifiers):
        super(_OneVsRestClassifier, self).__init__()
        self.single_species_classifiers = single_species_classifiers
        
    
    @property
    def clip_class_names(self):
        names = sorted(self.single_species_classifiers.keys())
        return names + ['Unclassified']
    
    
    def predict(self, features):
        
        num_predictions = len(features)
        
        classifiers = self.single_species_classifiers
        num_species = len(classifiers)
        
        clip_class_names = sorted(classifiers.keys())
        clip_class_names.sort()
        
        species_predictions = \
            np.zeros((num_species, num_predictions), dtype='int32')
        for i, clip_class_name in enumerate(clip_class_names):
            classifier = classifiers[clip_class_name]
            species_predictions[i] = classifier.predict(features)
            
        # Transpose species predictions so `species_predictions[i, j]` is
        # prediction of classifier `j` for clip `i`.
        species_predictions = species_predictions.transpose()
            
        # Get booleans indicating which clips were positive for
        # exactly one species.
        indicators = species_predictions.sum(axis=1) == 1
        
        # Get predictions as integers in the range [1, num_species].
        # A prediction of zero indicates no species.
        integer_codes = np.arange(num_species) + 1
        predictions = species_predictions * integer_codes
        predictions = predictions.sum(axis=1)
        predictions[~indicators] = 0
        
        # Get predictions as clip class names.
        clip_class_names = np.array(['Unclassified'] + clip_class_names)
        predictions = clip_class_names[predictions]

        return predictions        


if __name__ == '__main__':
    _main()