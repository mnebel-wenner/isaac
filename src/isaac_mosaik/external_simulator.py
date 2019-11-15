import io
import json
import mosaik_api
import logging


logger = logging.getLogger(__name__)


class ExampleDER:
    """
    Example DER that sends schedules from .csv files.
    Just for demonstration purpose.
    It will send the same schedules every day
    """
    def __init__(self, schedule_file_path):
        self.schedule_file_path = schedule_file_path
        self.possible_schedules = []
        self._schedule_dict = {}
        self.chosen_schedule = -1

        # open the schedule_file_path and read the header
        with io.open(schedule_file_path, 'rt') as schedule_file:
                
            header_line = next(schedule_file).strip()
            headers = json.loads(header_line)

            # read and verify possible schedules
            content = schedule_file.readlines()
            schedule_count = len(headers['cols'])
            for _ in range(schedule_count):
                self.possible_schedules.append([])

            # extract the data per schedule
            for line in content:
                data = line.strip().split(',')
                for n in range(schedule_count):
                    self.possible_schedules[n].append(float(data[n]))

            # fill schedule_dict
            for index, schedule in enumerate(self.possible_schedules):
                self._schedule_dict[index] = schedule


class ExampleDERSim(mosaik_api.Simulator):
    def __init__(self):
        meta = {
            'models': {
                'ExampleDER': {
                    'public': True,
                    'params': [
                        'schedule_file_path',
                    ],
                    'attrs': [
                        'possible_schedules',
                        'chosen_schedule',
                    ],
                },
            },
        }
        super().__init__(meta)
        logging.basicConfig(level=logging.DEBUG,
                            format='%(asctime)s:%(msecs)03d %(name)-25s %(levelname)-8s %(message)s',
                            datefmt='%d-%m-%y %H:%M:%S',
                            filename='exampleDER.log',
                            filemode='w')

        # create console handler and set level to info
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        # add handler to root logger
        logging.getLogger('').addHandler(handler)

        self._n_exampeDERs = None
        self._exampleDERs = None

    def init(self, sid):
        self._n_exampeDERs = 0
        self._exampleDERs = {}
        return self.meta
    
    def create(self, num, model, **params):
        entities = []
        for i in range(self._n_exampeDERs, self._n_exampeDERs + num):
            eid = 'exampleDER_{}'.format(str(i))
            self._exampleDERs[eid] = ExampleDER(params['schedule_file_path'])
            entities.append({'eid': eid, 'type': model})
            logger.debug('Created %s' % eid)
        
        self._n_exampeDERs += num
        return entities

    def step(self, time, inputs):
        # set data from *inputs* to *ders*
        for eid, values in inputs.items():
            exampleDER_instance = self._exampleDERs[eid]
            if 'chosen_schedule' in values:
                _, schedule_id = values['chosen_schedule'].popitem()
                logger.debug('Chosen schedule for %s is %s' % (eid, schedule_id))
                exampleDER_instance.chosen_schedule = schedule_id
                logger.debug('step(): %s received schedule_id %s' % (eid, schedule_id))
        # step of 15 minutes
        return time + 15 * 60

    # prepare date to send to other simulators
    def get_data(self, outputs):
        data = {}
        for eid, attrs in outputs.items():
            if eid not in self._exampleDERs:
                raise ValueError('Unknown entity ID "%s"' % eid)

            exampleDER_instance = self._exampleDERs[eid]
            data[eid] = {}
            for attr in attrs:
                if 'possible_schedules' in attr:
                    data[eid][attr] = exampleDER_instance.possible_schedules
        return data


def main():
    return mosaik_api.start_simulation(ExampleDERSim(), 'Example DER simulator')
            
        
if __name__ == '__main__':
    main()
