# Copyright (c) 2020 Microsoft Corporation. All rights reserved.
# Licensed under the MIT License

import concurrent.futures
import logging
import os
import random

import h5py
import numpy
import torch

from .arguments import args
from . import distributed

# require at top-level so no pickling errors
def _singlefile_dataloader_factory(filepath, batch_size, shuffle, num_workers):
    distributed.ensure_no_core_restriction()
    return torch.utils.data.DataLoader(
        BertSingleFileDataset(filepath, shuffle),
        batch_size = batch_size,
        num_workers = num_workers,
        pin_memory = True, 
        drop_last = True)

class BertMultiFileDataloader:

    def __init__(self, files, batch_size=1, shuffle=False, loop=False, num_workers=1):
        super().__init__()
        self.num_workers = num_workers
        self.files = files
        self.batch_size = batch_size
        self.loop = loop
        self.shuffle = shuffle
        if self.shuffle:
            random.shuffle(self.files)

        self.file_index = 0
        self.sample_index = 0
        self.pool = None
        self.dataset = None
        self.future_dataset = None

    def forward(self, count):
        for idx, _ in enumerate(self):
            if count <= idx:
                break
        logging.debug('Forwarded dataset to file_index {}, sample_index {}'.format(
            self.file_index, self.sample_index))
        self._destroy_datasets_if_exist()
        self._destroy_poolworker_if_exists()

    def reset(self):
        self.file_index = 0
        self.sample_index = 0
        self._destroy_datasets_if_exist()
        self._destroy_poolworker_if_exists()

    # note: iterator invoked by worker process (not the contructing process)
    # note: state of iterator resumes from (self.file_index, self.sample_index)
    def __iter__(self):
        self._create_poolworker_if_not_exists()
        self._fetch_future_dataset_or_none(self.file_index)

        while self.future_dataset is not None:
            del self.dataset
            self.dataset = self.future_dataset.result(timeout=None)
            self._fetch_future_dataset_or_none(self.file_index + 1)

            for batch in self.dataset:
                yield batch
                self.sample_index += self.batch_size

            self.file_index += 1
            self.sample_index = 0

        self.reset()

    def _create_poolworker_if_not_exists(self):
        if self.pool is None:
            self.pool = concurrent.futures.ProcessPoolExecutor(1)            

    def _fetch_future_dataset_or_none(self, index):
        if self.loop or index < len(self.files):
            next_file = self.files[index % len(self.files)]
            logging.debug('Requesting {}'.format(next_file))
            self.future_dataset = self.pool.submit(
                _singlefile_dataloader_factory, 
                next_file, 
                self.batch_size, 
                self.shuffle, 
                self.num_workers)
        else:
            self.future_dataset = None

    def _destroy_poolworker_if_exists(self):
        if self.pool is not None:
            del self.pool
        self.pool = None
    
    def _destroy_datasets_if_exist(self):
        if self.dataset is not None:
            del self.dataset
        self.dataset = None
        if self.future_dataset is not None:
            del self.future_dataset
        self.future_dataset = None

class BertSingleFileDataset(torch.utils.data.Dataset):

    def __init__(self, hdf5_filepath, shuffle=False):
        super().__init__()

        distributed.ensure_no_core_restriction()

        # refer bert_model.py for description of input meanings
        self.input_names = [
            'input_ids',
            'segment_ids',
            'input_mask',
            'masked_lm_positions',
            'masked_lm_ids',
            'next_sentence_labels'
        ]

        # load file data into memory as numpy arrays
        # len(self.bulk_data['input_ids]') = <number of samples>
        self.bulk_data = {}
        with h5py.File(hdf5_filepath, 'r') as hdf5_data:
            for name in self.input_names:
                self.bulk_data[name] = numpy.asarray(hdf5_data[name][:])

        # shuffle the samples
        if shuffle:
            indices = numpy.arange(len(self.bulk_data['input_ids']))
            numpy.random.shuffle(indices)
            for name in self.input_names:
                self.bulk_data[name] = self.bulk_data[name][indices]
            
        logging.debug('Loaded {} samples from {}'.format(
            len(self.bulk_data['input_ids']), hdf5_filepath))

    def __len__(self):
        return len(self.bulk_data['input_ids'])

    def __getitem__(self, index):
        sample = {}
        for name in self.input_names:
            sample[name] = torch.from_numpy(numpy.asarray(self.bulk_data[name][index], dtype=numpy.int64))
        masked_lm_labels = self._build_masked_lm_labels(sample['masked_lm_positions'], sample['masked_lm_ids'])

        return [
            sample['input_ids'],
            sample['segment_ids'], 
            sample['input_mask'], 
            masked_lm_labels, 
            sample['next_sentence_labels']
        ]

    # construct masked_lm_labels from masked_lm_positions and masked_lm_ids
    def _build_masked_lm_labels(self, masked_lm_positions, masked_lm_ids):
        masked_token_count = self._get_masked_token_count(masked_lm_positions)

        masked_lm_labels = torch.ones([args.max_seq_length], dtype=torch.int64) * -1
        masked_lm_labels[masked_lm_positions[:masked_token_count]] = masked_lm_ids[:masked_token_count]
        return masked_lm_labels

    def _get_masked_token_count(self, masked_lm_positions):
        masked_token_count = args.max_predictions_per_seq
        padded_mask_indices = (masked_lm_positions == 0).nonzero(as_tuple=False)
        if len(padded_mask_indices) != 0:
            masked_token_count = padded_mask_indices[0].item()
        return masked_token_count
