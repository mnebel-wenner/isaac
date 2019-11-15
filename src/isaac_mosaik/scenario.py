import os.path
import mosaik

ISAAC_LOG_FILE = 'isaac.log'
ISAAC_DEBUG_MODE = 'debug'


SIM_CONFIG = {
    'ExampleDERSim': {
        'python': 'external_simulator:ExampleDERSim',
    },
    'MAS': {
        'cmd': 'isaac-mosaik -l {mode} -lf {file} %(addr)s'.format(mode=ISAAC_DEBUG_MODE, file=ISAAC_LOG_FILE),
    },
}

MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR

# date of simulation
START = '2010-04-08 00:00:00'
END = 3 * DAY

# how many example DERs do we have
N_EXAMPLE_DER = 6
# how many schedule files do we have
N_SCHEDULE_FILES = 6
# shall we start ISAAC?
START_AGENTS = True

# data directory
LOCAL_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(LOCAL_DIR)), 'data')
TARGET_FILE = os.path.join(DATA_DIR, 'targets', 'electrical_target3.csv')

# log directory
LOG_DIR = LOCAL_DIR
RESULT_DIR = os.path.join(os.path.dirname(os.path.dirname(LOCAL_DIR)), 'results')

# fill list with path to schedule files for example simulator
SCHEDULE_FILES = [os.path.join(DATA_DIR, 'DER_schedules', 'der%s_schedules.csv' % i) for i in range(N_SCHEDULE_FILES)]


AGENT_CONFIG = {
    'UnitModel_cls': 'sim_models.simmodels:DER',
    'UnitIf_cls': 'isaac_mosaik.unit_interfaces:MosaikInterface',
    'Planner_cls': 'planning:Planner',
    'ControllerAgent': {
        'n_agents': N_EXAMPLE_DER,
        'topology_phi': 1,
        'topology_seed': 23,                 # random seed for topology creation
        'negotiation_single_start': True,    # should only one agent trigger the negotiation?
        'negotiation_timeout': 30 * MINUTE,  # after how many seconds should the negotiation be interrupted
        'scheduling_res': 15 * MINUTE,       # resolution of schedules
        'scheduling_period': 1 * DAY,        # how much time does one schedule cover
    },
    'ObserverAgent': {
        'n_agents': N_EXAMPLE_DER,
        'log_dbfile': os.path.join(RESULT_DIR, 'isaac_%s.hdf5' % START),
    },
    'Planner': {
        'check_inbox_interval': .1,  # [s]
    },
    'Negotiation_details': {
        'step_size': 1 * DAY,                  # step size: how frequently shall a new negotiation be triggered?
        'target_file': TARGET_FILE,
    },

    'UnitModel': {
        'get_schedules_from_files': False,
    }

}


def main():
    world = mosaik.World(SIM_CONFIG)
    create_scenario(world)
    world.run(until=END)


def create_scenario(world):
    # setup ExampleDERs
    exampleDERs = setup_exampleDERs(world)
    if START_AGENTS:
        # setup ISAAC
        setup_mas(world, exampleDERs)


def setup_exampleDERs(world):
    """Set-up the exampleDER and return a list of the entities."""
    exampleDERSim = world.start('ExampleDERSim')
    
    exampleDERs = [] # list of entities
    for i in range(N_EXAMPLE_DER):
        file_path = SCHEDULE_FILES[i % N_SCHEDULE_FILES] # determine schedule file for agent
        # create one example DER with corresponding schedule_file_path
        exampleDERs += exampleDERSim.ExampleDER.create(1, **{'schedule_file_path': file_path})
    
    return exampleDERs


def setup_mas(world, ders):
    """Set-up the multi-agent system ISAAC"""
    mas = world.start('MAS', start_date=START, n_agents=N_EXAMPLE_DER,
                      config=AGENT_CONFIG)
    agents = mas.Agent.create(N_EXAMPLE_DER)

    # connect DERs with der agents from ISAAC
    for der, agent in zip(ders, agents):
        world.connect(der, agent, 'possible_schedules', async_requests=True)


if __name__ == '__main__':
    main()
