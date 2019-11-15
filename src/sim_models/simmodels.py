"""

"""

import io
import json
import arrow
import os
import lzma

from os import listdir
from os.path import isfile, join

from aiomas import expose

import numpy as np
from unit import UnitModel


class NoSuchScheduleException(Exception):
    pass


class DER(UnitModel):
    """
    Simulator for a number of DERs.
    """
    def __init__(self, *, get_schedules_from_files, schedule_dir=None, schedule_files=None, **config):
        """

        :param get_schedules_from_files: boolean indicating, whether schedules are gotten from files
        :param schedule_dir: Directory to schedule files (must be provided, if get_schedules_from_files == True)
        :param schedule_files: List of schedule files within der_schedules_dir. If none, all files are considered
        :param config: params for the super class
        """
        super().__init__(**config)
        self.get_schedules_from_files = get_schedules_from_files

        if get_schedules_from_files:
            assert schedule_dir is not None and os.path.isdir(schedule_dir),\
                'Schedules shall be generated from files, but the directory {dir} does not exist'.format(
                    dir=schedule_dir
                )

            # if der_schedule_files exists, evaluate only the given .csv files
            if schedule_files:
                self._schedule_files = [join(schedule_dir, f)
                                        for f in schedule_files
                                        if isfile(join(schedule_dir, f))
                                        if f.endswith('.csv')]
            # if der_schedule_files is None, choose all .csv files within that folder
            else:
                self._schedule_files = [join(schedule_dir, f)
                                        for f in listdir(schedule_dir)
                                        if isfile(join(schedule_dir, f)) and f.endswith('.csv')]
        self._possible_schedules = []
        self._schedule_dict = {}

    def generate_schedules(self, start, resolution, intervals, state):
        """
        This simple function does the following:
        - read files in schedule_dir and find schedule files with the requested start, resolution
          and intervals
        - extract schedules and update self._possible_schedules and
          self._schedule_dict
        - return self._possible_schedules
        - throw an exception if no schedule has been found

        """
        # preprocess parameters

        if not self.get_schedules_from_files:
            return self._possible_schedules


        start_date_requested = arrow.get(start).to('utc')


        # search for a schedule with the given parameters
        self._schedule_dict = {}
        self._possible_schedules = []
        for schedule_file_path in self._schedule_files:

            # open each production schedule_file_path and read the header
            schedule_file = lzma.open(schedule_file_path, 'rt') \
                if schedule_file_path.endswith('.xz') else \
                io.open(schedule_file_path, 'rt')
            header_line = next(schedule_file).strip()

            # parse and verify meta data
            headers = json.loads(header_line)
            start_date_parsed = arrow.get(headers['start_time']).to('utc')
            if start_date_parsed != start_date_requested:
                continue
            interval_seconds = headers['interval_minutes'] * 60
            if interval_seconds != resolution:
                continue

            # read and verify possible schedules
            content = schedule_file.readlines()
            if len(content) != intervals:
                continue

            # we found adequate schedules
            possible_schedules = []
            schedule_count = len(headers['cols'])
            for index in range(schedule_count):
                possible_schedules.append([])

            # extract the data per schedule
            for line in content:
                data = line.strip().split(',')
                for n in range(schedule_count):
                    possible_schedules[n].append(float(data[n]))

            # fill possible_schedules list and schedule_dict, shift index if there are schedules already found
            for index, schedule in enumerate(possible_schedules, len(self._possible_schedules)):
                schedule_new = np.array(schedule)
                self._schedule_dict[index] = schedule_new
                self._possible_schedules.append([index, 0, schedule_new])

        # raise exception if no schedule has been found.
        if not self._possible_schedules:
            raise NoSuchScheduleException('No adequate schedule has been found in {files} for {date}.'.format
                                          (files=self._schedule_files, date=start_date_requested))
        return self._possible_schedules

    @expose
    def set_possible_schedules(self, schedule_list):
        """
        Called if schedules are given from external simulators
        :param schedule_list: list of schedule array
        """

        self._possible_schedules = []
        self._schedule_dict = {}
        for index, schedule in enumerate(schedule_list):
            self._possible_schedules.append((index, 0, np.array(schedule)))
            self._schedule_dict [index] = np.array(schedule)

    def get_schedule(self, schedule_id):
        # returns None if schedule_id does not exist
        return self._schedule_dict.get(schedule_id)

    @expose
    def update_forecast(self, fc):
        pass  # Nothing to do so far
