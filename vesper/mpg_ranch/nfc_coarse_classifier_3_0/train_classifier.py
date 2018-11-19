"""
Trains a Vesper coarse clip classifier.

A coarse clip classifier is a binary classifier that tries to determine
whether or not a clip contains a nocturnal flight call.
"""


from pathlib import Path
import functools
import glob
import math
import os
import shutil
import time

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import MultipleLocator
import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf

from vesper.util.binary_classification_stats import BinaryClassificationStats
from vesper.util.settings import Settings
import vesper.util.signal_utils as signal_utils
import vesper.util.time_frequency_analysis_utils as tfa_utils


# TODO: Try random waveform slicing time offsets.
# TODO: Try various combinations of batch normalization, dropout, and L2
#       regularization.
# TODO: Prepare Thrush HDF5 files.
# TODO: Train thrush coarse classifier.
# TODO: Figure out how to get sequence of training run precision-recall curves.
# TODO: Figure out how to save and restore estimator.
# TODO: Build Vesper classifier from saved estimator.
# TODO: Look at clip albums of incorrectly classified clips.

# TODO: Does normalization matter with one input feature?
# TODO: Evaluate on an initial part of training set.


CLASSIFIER_NAME = 'Tseep BN 340K'

ML_DIR_PATH = Path('/Users/harold/Desktop/NFC/Data/Vesper ML')
DATASETS_DIR_PATH = ML_DIR_PATH / 'Datasets' / 'Coarse Classification'
DATA_FILE_NAME_FORMAT = '{}_{}_{}.tfrecords'

MODELS_DIR_PATH = ML_DIR_PATH / 'Models' / 'Coarse Classification'

RESULTS_DIR_PATH = Path('/Users/harold/Desktop/ML Results')
PR_PLOT_FILE_NAME_FORMAT = '{} PR.pdf'
ROC_PLOT_FILE_NAME_FORMAT = '{} ROC.pdf'
STATS_CSV_FILE_NAME_FORMAT = '{} Stats.csv'

STATS_CSV_FILE_HEADER = (
    'Threshold,'
    'Training Recall,'
    'Training Precision,'
    'Validation Recall,'
    'Validation Precision\n')

STATS_CSV_FILE_ROW_FORMAT = '{:.2f},{:.3f},{:.3f},{:.3f},{:.3f}\n'


EXAMPLE_FEATURES = {
    'waveform': tf.FixedLenFeature((), tf.string, default_value=''),
    'label': tf.FixedLenFeature((), tf.int64, default_value=0)
}

BASE_TSEEP_SETTINGS = Settings(
    
    dataset_name='Base Tseep Settings Dataset',
    
    sample_rate=24000,
    
    # waveform slicing settings
    waveform_start_time=.080,
    waveform_duration=.150,
    
    # spectrogram settings
    spectrogram_window_size=.005,
    spectrogram_hop_size=.5,
    spectrogram_log_epsilon=1e-10,
    
    # spectrogram frequency axis slicing settings
    spectrogram_start_freq=4000,
    spectrogram_end_freq=10000,
    
    # number of parallel calls for input and spectrogram computation
    num_preprocessing_parallel_calls=4,
    
    # spectrogram clipping pretraining settings
    spectrogram_clipping_pretraining_enabled=True,
    pretraining_num_examples=20000,
    pretraining_batch_size=1000,
    pretraining_histogram_min=-25,
    pretraining_histogram_max=50,
    pretraining_histogram_num_bins=750,
    pretraining_clipped_values_fraction=.001,
    pretraining_value_distribution_plotting_enabled=False,
    
    # spectrogram normalization pretraining settings
    spectrogram_normalization_pretraining_enabled=True,
    
    # spectrogram clipping settings
    spectrogram_clipping_enabled=True,
    spectrogram_clipping_min=None,
    spectrogram_clipping_max=None,
    
    # spectrogram normalization settings
    spectrogram_normalization_enabled=True,
    spectrogram_normalization_scale_factor=None,
    spectrogram_normalization_offset=None,
    
    train_cnn=True,
    hidden_layer_sizes=[16],
    batch_normalization_enabled=True,
    regularization_beta=.002,
    
    batch_size=64,
    num_training_steps=50000
    
)


SETTINGS = {
     
    'Tseep Baseline': Settings(BASE_TSEEP_SETTINGS, Settings(
        
        dataset_name='Tseep 100K',
        
        train_cnn=False,
        hidden_layer_sizes=[16],
        regularization_beta=.002,
        
        batch_size=64,
        num_training_steps=50000,
        
    )),
    
    'Tseep Test': Settings(BASE_TSEEP_SETTINGS, Settings(
        
        dataset_name='Tseep 100K',
        
        pretraining_num_examples=1000,
        
        train_cnn=False,
        hidden_layer_sizes=[16],
        regularization_beta=.002,
        
        batch_size=64,
        num_training_steps=1000,
        
    )),    
    
    'Tseep BN': Settings(BASE_TSEEP_SETTINGS, Settings(
        
        dataset_name='Tseep 100K',
        
        batch_normalization_enabled=True,
        
        batch_size=64,
        num_training_steps=4000,
        
    )),    
    
    'Tseep No BN': Settings(BASE_TSEEP_SETTINGS, Settings(
        
        dataset_name='Tseep 100K',
        
        batch_normalization_enabled=False,
        
        batch_size=64,
        num_training_steps=50000,
        
    )),    
    
    'Tseep BN 340K': Settings(BASE_TSEEP_SETTINGS, Settings(
        
        dataset_name='Tseep 340K',
        
        batch_normalization_enabled=True,
        
        batch_size=64,
        num_training_steps=13000,
        
    )),    
    
}


def main():
    
    work_around_openmp_issue()
    
    # save_checkpoint_results('Tseep BN', 2000, 8000)
    
    train_and_evaluate_classifier(CLASSIFIER_NAME)
    
    # settings = SETTINGS[CLASSIFIER_NAME]
    # show_training_dataset(settings)
    # show_spectrogram_dataset(settings)
    
    
def save_checkpoint_results(classifier_name, min_step_num, max_step_num):
    
    model_dir_path = MODELS_DIR_PATH / classifier_name
    
    step_nums = get_checkpoint_step_nums(model_dir_path)
    
    for step_num in step_nums:
        
        if min_step_num <= step_num and step_num <= max_step_num:
            
            checkpoint_path = model_dir_path / 'model.ckpt-*'.format(step_num)
            
            print(checkpoint_path)
            
#             ws = tf.estimator.WarmStartSettings(
#                 ckpt_to_initialize_from=checkpoint_path)
    
    
def get_checkpoint_step_nums(model_dir_path):
    pattern = model_dir_path / 'model.ckpt-*.index'
    file_paths = glob.glob(str(pattern))
    return sorted(get_checkpoint_step_num(p) for p in file_paths)


def get_checkpoint_step_num(file_path):
    file_name = Path(file_path).name
    step_num = file_name.split('-')[1].split('.')[0]
    return int(step_num)


def work_around_openmp_issue():

    # Added this 2018-11-13 to work around a problem on macOS involving
    # potential confusion among multiple copies of the OpenMP runtime.
    # The problem only appears to arise when I install TensorFlow using
    # Conda rather than pip. I'm not sure where the multiple copies are
    # coming from. Perhaps Conda and Xcode? See
    # https://github.com/openai/spinningup/issues/16 for an example of
    # another person encountering this issue.
    os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'


def train_and_evaluate_classifier(name):
    
    settings = SETTINGS[name]
     
    classifier = Classifier(name, settings)
    classifier.train()
     
    classifier.evaluate()
    

class Classifier:
    
    
    def __init__(self, name, settings):
        
        self.name = name
        
        shutil.rmtree(self.model_dir_path, ignore_errors=True)
        
        self.settings = settings
        complete_settings(self.settings)
        
        self.model = self._create_model()
        
        self.estimator = self._create_estimator()
        
        
    @property
    def model_dir_path(self):
        return MODELS_DIR_PATH / self.name
    
    
    @property
    def model_input_name(self):
        
        """
        The name assigned by the Keras model to its input.
        
        We use this as a feature name in training and evaluation datasets
        to tell TensorFlow what data to feed to the model.
        """
        
        return self.model.input_names[0]
    
    
    def _create_model(self):
        
        if self.settings.train_cnn:
            return self._create_cnn_model()
        
        else:
            return self._create_dnn_model()


    def _create_dnn_model(self):
         
        s = self.settings
        
        layer_sizes = s.hidden_layer_sizes + [1]
        num_layers = len(layer_sizes)
         
        regularizer = tf.keras.regularizers.l2(s.regularization_beta)
         
        model = tf.keras.Sequential()
         
        for i in range(num_layers):
             
            kwargs = {
                'activation': 'sigmoid' if i == num_layers - 1 else 'relu',
                'kernel_regularizer': regularizer
            }
             
            if i == 0:
                kwargs['input_dim'] = get_sliced_spectrogram_size(s)
                 
            model.add(tf.keras.layers.Dense(layer_sizes[i], **kwargs))
             
        model.compile(
            optimizer='adam',
            loss='binary_crossentropy',
            metrics=['accuracy'])
        
        return model
        
    
    def _create_cnn_model(self):
        
        s = self.settings
        
        if s.batch_normalization_enabled:
            regularizer = None
        else:
            regularizer = tf.keras.regularizers.l2(s.regularization_beta)
        
        model = tf.keras.Sequential()
        
        # model.add(Conv2D(
        #    16, kernel_size=(3, 3), activation='relu',
        #    input_shape=input_shape))
        # model.add(Conv2D(32, (3, 3), activation='relu'))
        # model.add(MaxPooling2D(pool_size=(2, 2)))
        # model.add(Dropout(.25))
        # model.add(Flatten())
        # model.add(Dense(32, activation='relu'))
        # model.add(Dropout(.5))
        # model.add(Dense(1, activation='sigmoid'))
        
        # Add channel dimension to spectrogram shape to make Conv2D input
        # shape.
        input_shape = get_sliced_spectrogram_shape(s) + (1,)
        
        model.add(tf.keras.layers.Conv2D(
            16, kernel_size=(3, 3), activation='relu',
            input_shape=input_shape,
            kernel_regularizer=regularizer))
        
        if s.batch_normalization_enabled:
            model.add(tf.keras.layers.BatchNormalization())
        
        model.add(tf.keras.layers.MaxPooling2D(pool_size=(2, 2)))
        
        model.add(tf.keras.layers.Conv2D(
            32, kernel_size=(3, 3), activation='relu',
            kernel_regularizer=regularizer))
        
        if s.batch_normalization_enabled:
            model.add(tf.keras.layers.BatchNormalization())
        
        model.add(tf.keras.layers.MaxPooling2D(pool_size=(2, 2)))
        
        model.add(tf.keras.layers.Flatten())
        
        model.add(tf.keras.layers.Dense(
            32, activation='relu', kernel_regularizer=regularizer))
        
        if s.batch_normalization_enabled:
            model.add(tf.keras.layers.BatchNormalization())

        model.add(tf.keras.layers.Dense(
            1, activation='sigmoid', kernel_regularizer=regularizer))
        
        model.compile(
            optimizer='adam',
            loss='binary_crossentropy',
            metrics=['accuracy'])
    
        return model

    
    def _create_estimator(self):
        
        config = tf.estimator.RunConfig(
            save_summary_steps=100,
            save_checkpoints_steps=200,
            keep_checkpoint_max=None)
        
        return tf.keras.estimator.model_to_estimator(
            self.model,
            model_dir=self.model_dir_path,
            config=config)
        
        
    def train(self):
        
        s = self.settings
        
        print(
            'Training classifier for {} steps...'.format(
                s.num_training_steps))
        
        train_spec = tf.estimator.TrainSpec(
            input_fn=self.create_training_dataset,
            max_steps=s.num_training_steps)
        
        eval_spec = tf.estimator.EvalSpec(
            input_fn=self.create_validation_dataset,
            steps=None,
            start_delay_secs=30,
            throttle_secs=30)
        
        start_time = time.time()
        tf.estimator.train_and_evaluate(self.estimator, train_spec, eval_spec)
        delta_time = time.time() - start_time
        print('Training took {} seconds.'.format(delta_time))


    def evaluate(self):
        print('Evaluating classifier on training dataset...')
        train_stats = self._evaluate(self.create_short_training_dataset)
        print('Evaluating classifier on validation dataset...')
        val_stats = self._evaluate(self.create_validation_dataset)
        print('Saving results...')
        save_results(self.name, train_stats, val_stats)
        print('Done.')
            
    
        
    def _evaluate(self, dataset_creator, num_thresholds=101):
        
        labels = get_dataset_labels(dataset_creator())
        
        predictions = self.estimator.predict(input_fn=dataset_creator)
        
        # At this point `predictions` is an iterator that yields
        # dictionaries, each of which contains a single item whose
        # value is an array containing one element, a prediction.
        # Extract the predictions into a NumPy array.
        predictions = np.array(
            [list(p.values())[0][0] for p in predictions])
        
        # pairs = list(zip(labels, predictions))
        # for i, pair in enumerate(pairs[:200]):
        #     print(i, pair)
            
        thresholds = np.arange(num_thresholds) / float(num_thresholds - 1)
    
        return BinaryClassificationStats(labels, predictions, thresholds)
        
        
    def create_training_dataset(self):
        return create_spectrogram_dataset(
            self.settings, 'Training', feature_name=self.model_input_name,
            num_repeats=100, shuffle=True)
    
    
    def create_short_training_dataset(self):
        return create_spectrogram_dataset(
            self.settings, 'Training', feature_name=self.model_input_name)


    def create_validation_dataset(self):
        return create_spectrogram_dataset(
            self.settings, 'Validation', feature_name=self.model_input_name)

    
def get_dataset_labels(dataset):
    
    iterator = dataset.make_one_shot_iterator()
    next_batch = iterator.get_next()
     
    with tf.Session() as session:
        
        label_batches = []
        num_labels = 0
        
        while True:
            
            try:
                _, labels = session.run(next_batch)
                labels = labels.flatten()
                label_batches.append(labels.flatten())
                num_labels += labels.size
                
            except tf.errors.OutOfRangeError:
                break
            
    return np.concatenate(label_batches)
    
    
def complete_settings(settings):
    
    if settings.spectrogram_clipping_pretraining_enabled:
        compute_spectrogram_clipping_settings(settings)
        
    if settings.spectrogram_normalization_pretraining_enabled:
        compute_spectrogram_normalization_settings(settings)
            

def get_sliced_spectrogram_shape(settings):
    
    (time_start_index, time_end_index, window_size, hop_size, _,
     freq_start_index, freq_end_index) = \
        get_low_level_preprocessing_settings(settings)
                
    num_samples = time_end_index - time_start_index
    num_spectra = tfa_utils.get_num_analysis_records(
        num_samples, window_size, hop_size)
    
    num_bins = freq_end_index - freq_start_index
    
    return (num_spectra, num_bins)
    
    
def get_sliced_spectrogram_size(settings):
    num_spectra, num_bins = get_sliced_spectrogram_shape(settings)
    return num_spectra * num_bins


def get_low_level_preprocessing_settings(settings):
    
    s = settings
    fs = s.sample_rate
    s2f = signal_utils.seconds_to_frames
    
    # time slicing
    time_start_index = s2f(s.waveform_start_time, fs)
    length = s2f(s.waveform_duration, fs)
    time_end_index = time_start_index + length
    
    # spectrogram
    window_size = s2f(s.spectrogram_window_size, fs)
    hop_size = s2f(s.spectrogram_window_size * s.spectrogram_hop_size, fs)
    dft_size = tfa_utils.get_dft_size(window_size)
    
    # frequency slicing
    f2i = tfa_utils.get_dft_bin_num
    freq_start_index = f2i(s.spectrogram_start_freq, fs, dft_size)
    freq_end_index = f2i(s.spectrogram_end_freq, fs, dft_size) + 1
    
    return (
        time_start_index, time_end_index, window_size, hop_size, dft_size,
        freq_start_index, freq_end_index)


def compute_spectrogram_clipping_settings(settings):
    
    s = settings
    
    num_examples = s.pretraining_num_examples
    batch_size = s.pretraining_batch_size
    num_batches = int(round(num_examples / batch_size))
    
    hist_min = s.pretraining_histogram_min
    hist_max = s.pretraining_histogram_max
    num_bins = s.pretraining_histogram_num_bins
    bin_size = (hist_max - hist_min) / num_bins
    log_epsilon = math.log(settings.spectrogram_log_epsilon)
    
    dataset = create_spectrogram_dataset(
        settings, 'Training', batch_size=batch_size,
        spectrogram_clipping_enabled=False,
        spectrogram_normalization_enabled=False)
    iterator = dataset.make_one_shot_iterator()
    next_batch = iterator.get_next()
     
    with tf.Session() as session:
        
        print(
            'Computing spectrogram clipping range from {} examples...'.format(
                num_batches * batch_size))
        
        start_time = time.time()
        
        histogram = np.zeros(num_bins)
        
        for _ in range(num_batches):
                
            features, _ = session.run(next_batch)
            grams = features['spectrogram']
            
            h, edges = np.histogram(grams, num_bins, (hist_min, hist_max))
            histogram += h
            
            # If one of the histogram bins includes the log power to which
            # zero spectrogram values are mapped, zero that bin to ensure that
            # it doesn't interfere with computing a good minimum power value.
            if hist_min <= log_epsilon and log_epsilon <= hist_max:
                bin_num = int(math.floor((log_epsilon - hist_min) / bin_size))
                # print('Zeroing histogram bin {}.'.format(bin_num))
                histogram[bin_num] = 0
           
            # Compute clipping powers.
            cumsum = histogram.cumsum() / histogram.sum()
            threshold = s.pretraining_clipped_values_fraction / 2
            min_index = np.searchsorted(cumsum, threshold, side='right')
            max_index = np.searchsorted(cumsum, 1 - threshold) + 1
            min_value = edges[min_index]
            max_value = edges[max_index]
                
            # print(
            #     'Batch {} of {}: ({}, {})'.format(
            #         i + 1, num_batches, min_value, max_value))
            
        end_time = time.time()
        delta_time = end_time - start_time
        print(
            'Computed spectrogram clipping range in {} seconds.'.format(
                delta_time))
        print('Clipping range is ({}, {}).'.format(min_value, max_value))

    # Plot spectrogram value distribution and clipping limits.
    if s.pretraining_value_distribution_plotting_enabled:
        distribution = histogram / histogram.sum()
        plt.figure(1)
        plt.plot(edges[:-1], distribution)
        plt.axvline(min_value, color='r')
        plt.axvline(max_value, color='r')
        plt.xlim((edges[0], edges[-1]))
        plt.title('Distribution of Spectrogram Values')
        plt.xlabel('Log Power')
        plt.show()

    s.spectrogram_clipping_min = min_value
    s.spectrogram_clipping_max = max_value
    
    
def create_spectrogram_dataset(
        settings, dataset_type, feature_name='spectrogram',
        num_repeats=1, shuffle=False, batch_size=None,
        spectrogram_clipping_enabled=None,
        spectrogram_normalization_enabled=None):
    
    dataset = create_base_dataset(settings.dataset_name, dataset_type)
    
    if num_repeats != 1:
        dataset = dataset.repeat(num_repeats)
    
    batch_size = get_batch_size(settings, batch_size)

    if shuffle:
        dataset = dataset.shuffle(10 * batch_size)
        
    if batch_size != 1:
        dataset = dataset.batch(batch_size)
    
    if spectrogram_clipping_enabled is not None:
        settings = Settings(
            settings,
            spectrogram_clipping_enabled=spectrogram_clipping_enabled)
        
    if spectrogram_normalization_enabled is not None:
        enabled = spectrogram_normalization_enabled  # to shorten line below
        settings = Settings(
            settings, spectrogram_normalization_enabled=enabled)

    preprocessor = Preprocessor(settings, feature_name)
    
    dataset = dataset.map(
        preprocessor,
        num_parallel_calls=settings.num_preprocessing_parallel_calls)
    
    return dataset
    

def create_base_dataset(dataset_name, dataset_type):
    
    file_path_pattern = create_data_file_path(dataset_name, dataset_type, '*')
    
    # TODO: Use tf.data.Dataset.list_files instead of tf.gfile.Glob?
    
    # Get file paths matching pattern. Sort the paths for consistency.
    file_paths = sorted(tf.gfile.Glob(file_path_pattern))
    
    return tf.data.TFRecordDataset(file_paths).map(parse_example)
            
        
def create_data_file_path(dataset_name, dataset_type, file_num):
    dir_path = DATASETS_DIR_PATH / dataset_name / dataset_type
    file_name = DATA_FILE_NAME_FORMAT.format(
        dataset_name, dataset_type, file_num)
    return str(dir_path / file_name)
    

def parse_example(example_proto):
    
    example = tf.parse_single_example(example_proto, EXAMPLE_FEATURES)
    
    bytes_ = example['waveform']
    waveform = tf.decode_raw(bytes_, out_type=tf.int16, little_endian=True)
    
    label = example['label']
    
    return waveform, label


def get_batch_size(settings, batch_size):
    
    if batch_size is not None:
        return batch_size
    
    elif settings.batch_size is not None:
        return settings.batch_size
    
    else:
        return 1


def compute_spectrogram_normalization_settings(settings):
    
    s = settings
    
    num_examples = s.pretraining_num_examples
    batch_size = s.pretraining_batch_size
    num_batches = int(round(num_examples / batch_size))
    
    dataset = create_spectrogram_dataset(
        settings, 'Training', batch_size=batch_size,
        spectrogram_clipping_enabled=True,
        spectrogram_normalization_enabled=False)
    iterator = dataset.make_one_shot_iterator()
    next_batch = iterator.get_next()
     
    with tf.Session() as session:
        
        print((
            'Computing spectrogram normalization settings from {} '
            'examples...').format(num_batches * batch_size))
        
        start_time = time.time()
        
        num_values = 0
        values_sum = 0
        squares_sum = 0
        
        for _ in range(num_batches):
                
            features, _ = session.run(next_batch)
            grams = features['spectrogram']
            
            num_values += grams.size
            values_sum += grams.sum()
            squares_sum += (grams ** 2).sum()
            
            mean = values_sum / num_values
            std_dev = math.sqrt(squares_sum / num_values - mean ** 2)
            
            # print(
            #     'Batch {} of {}: ({}, {})'.format(
            #         i + 1, num_batches, mean, std_dev))
            
        end_time = time.time()
        delta_time = end_time - start_time
        print((
            'Computed spectrogram normalization settings in {} '
            'seconds.').format(delta_time))
        print(
            'Normalization mean and standard deviation are ({}, {}).'.format(
                mean, std_dev))
        
    s.spectrogram_normalization_scale_factor = 1 / std_dev
    s.spectrogram_normalization_offset = -mean / std_dev

    
def save_results(classifier_name, train_stats, val_stats):
    plot_precision_recall_curves(classifier_name, train_stats, val_stats)
    plot_roc_curves(classifier_name, train_stats, val_stats)
    write_stats_csv_file(classifier_name, train_stats, val_stats)
        
        
def plot_precision_recall_curves(classifier_name, train_stats, val_stats):
    
    file_path = create_results_file_path(
        PR_PLOT_FILE_NAME_FORMAT, classifier_name)
    
    with PdfPages(file_path) as pdf:
        
        plt.figure(figsize=(6, 6))
        
        # Plot training and validation curves.
        plt.plot(
            train_stats.recall, train_stats.precision, 'b',
            val_stats.recall, val_stats.precision, 'g')
        
        # Set title, legend, and axis labels.
        plt.title('{} Precision vs. Recall'.format(classifier_name))
        plt.legend(['Training', 'Validation'])
        plt.xlabel('Recall')
        plt.ylabel('Precision')
        
        # Set axis limits.
        plt.xlim((.8, 1))
        plt.ylim((.8, 1))
        
        # Configure grid.
        major_locator = MultipleLocator(.05)
        minor_locator = MultipleLocator(.01)
        axes = plt.gca()
        axes.xaxis.set_major_locator(major_locator)
        axes.xaxis.set_minor_locator(minor_locator)
        axes.yaxis.set_major_locator(major_locator)
        axes.yaxis.set_minor_locator(minor_locator)
        plt.grid(which='both')
        plt.grid(which='minor', alpha=.4)

        pdf.savefig()
        
        plt.close()


def create_results_file_path(file_name_format, classifier_name):
    file_name = file_name_format.format(classifier_name)
    return RESULTS_DIR_PATH / file_name


def plot_roc_curves(classifier_name, train_stats, val_stats):
    
    file_path = create_results_file_path(
        ROC_PLOT_FILE_NAME_FORMAT, classifier_name)
    
    with PdfPages(file_path) as pdf:
        
        plt.figure(figsize=(6, 6))
    
        # Plot training and validation curves.
        plt.plot(
            train_stats.false_positive_rate, train_stats.true_positive_rate,
            'b', val_stats.false_positive_rate, val_stats.true_positive_rate,
            'g')
        
        # Set title, legend, and axis labels.
        plt.title('{} ROC'.format(classifier_name))
        plt.legend(['Training', 'Validation'])
        plt.xlabel('False Positive Rate')
        plt.ylabel('True Positive Rate')
        
        # Set axis limits.
        plt.xlim((0, 1))
        plt.ylim((0, 1))
        
        # Configure grid.
        major_locator = MultipleLocator(.25)
        minor_locator = MultipleLocator(.05)
        axes = plt.gca()
        axes.xaxis.set_major_locator(major_locator)
        axes.xaxis.set_minor_locator(minor_locator)
        axes.yaxis.set_major_locator(major_locator)
        axes.yaxis.set_minor_locator(minor_locator)
        plt.grid(which='both')
        plt.grid(which='minor', alpha=.4)
    
        pdf.savefig()
        
        plt.close()


def write_stats_csv_file(classifier_name, train_stats, val_stats):
    
    file_path = create_results_file_path(
        STATS_CSV_FILE_NAME_FORMAT, classifier_name)
    
    with open(file_path, 'w') as csv_file:
        
        csv_file.write(STATS_CSV_FILE_HEADER)
        
        columns = (
            train_stats.threshold,
            train_stats.recall,
            train_stats.precision,
            val_stats.recall,
            val_stats.precision
        )
        
        for row in zip(*columns):
            csv_file.write(STATS_CSV_FILE_ROW_FORMAT.format(*row))


def show_training_dataset(settings):
    complete_settings(settings)
    dataset = create_spectrogram_dataset(settings, 'Training')
    show_dataset(dataset, 20)
        
    
def show_dataset(dataset, num_batches):

    print('output types', dataset.output_types)
    print('output_shapes', dataset.output_shapes)
    
    iterator = dataset.make_one_shot_iterator()
    next_batch = iterator.get_next()
     
    with tf.Session() as session:
        
        start_time = time.time()
        
        num_values = 0
        values_sum = 0
        squares_sum = 0
        
        for i in range(num_batches):
                
            features, labels = session.run(next_batch)
            feature_name, values = list(features.items())[0]
                
            values_class = values.__class__.__name__
            labels_class = labels.__class__.__name__
            
            num_values += values.size
            values_sum += values.sum()
            squares_sum += (values ** 2).sum()
            
            mean = values_sum / num_values
            std_dev = math.sqrt(squares_sum / num_values - mean ** 2)
            
            print(
                'Batch {} of {}: {} {} {} {} {}, labels {} {}'.format(
                    i + 1, num_batches, feature_name, values_class,
                    values.shape, mean, std_dev, labels_class, labels.shape))
            
        print('Iteration took {} seconds.'.format(time.time() - start_time))
                    

def show_spectrogram_dataset(settings):
    
    total_num_examples = 2 ** 9
    batch_size = 2 ** 6
    
    dataset = create_spectrogram_dataset(
        settings, 'Training', batch_size=batch_size,
        spectrogram_clipping_enabled=False,
        spectrogram_normalization_enabled=False)
    
    num_batches = int(round(total_num_examples / batch_size))
    show_dataset(dataset, num_batches)


class Preprocessor:
    
    
    def __init__(self, settings, output_feature_name='spectrogram'):
        
        self.settings = settings
        self.output_feature_name = output_feature_name
        
        (self.time_start_index, self.time_end_index, self.window_size,
         self.hop_size, self.dft_size, self.freq_start_index,
         self.freq_end_index) = get_low_level_preprocessing_settings(settings)
                
        self.window_fn = functools.partial(
            tf.contrib.signal.hann_window, periodic=True)
        
        
    def __call__(self, waveforms, labels):
        
        """Computes spectrograms for a batch of waveforms."""
        
        s = self.settings
        
        # Slice waveforms.
        waveforms = waveforms[
            ..., self.time_start_index:self.time_end_index]
        
        # At this point the `waveforms` tensor has an unknown final
        # dimension. We know that the dimension is the sliced waveform
        # length, however, so we set it. If the dimension remains
        # unknown, the `Classifier.create_cnn_model` method fails,
        # though the `Classifier.create_dnn_model` method does not.
        waveform_length = self.time_end_index - self.time_start_index
        dims = list(waveforms.shape.dims)
        dims[-1] = tf.Dimension(waveform_length)
        shape = tf.TensorShape(dims)
        waveforms.set_shape(shape)

        # Compute STFTs.
        waveforms = tf.cast(waveforms, tf.float32)
        stfts = tf.contrib.signal.stft(
            waveforms, self.window_size, self.hop_size,
            fft_length=self.dft_size, window_fn=self.window_fn)
        
        # Slice STFTs along frequency axis.
        stfts = stfts[..., self.freq_start_index:self.freq_end_index]
        
        # Get STFT magnitudes squared, i.e. squared spectrograms.
        grams = tf.real(stfts * tf.conj(stfts))
        # gram = tf.abs(stft) ** 2
        
        # Take natural log of squared spectrograms. Adding an epsilon
        # avoids log-of-zero errors.
        grams = tf.log(grams + s.spectrogram_log_epsilon)
        
        # Clip spectrograms if indicated.
        if s.spectrogram_clipping_enabled:
            grams = tf.clip_by_value(
                grams, s.spectrogram_clipping_min, s.spectrogram_clipping_max)
            
        # Normalize spectrograms if indicated.
        if s.spectrogram_normalization_enabled:
            grams = \
                s.spectrogram_normalization_scale_factor * grams + \
                s.spectrogram_normalization_offset
        
        if s.train_cnn:
            
            # Add channel dimension for Keras Conv2D layer compatibility.
            grams = tf.expand_dims(grams, 3)
            
        else:
            
            # Flatten spectrograms for Keras Dense layer compatibility.
            size = get_sliced_spectrogram_size(s)
            grams = tf.reshape(grams, (-1, size))

        
        # Create features dictionary.
        features = {self.output_feature_name: grams}
        
        # Reshape labels into a single 2D column.
        labels = tf.reshape(labels, (-1, 1))
        
        return features, labels
    
        
if __name__ == '__main__':
    main()
