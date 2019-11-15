"""Configuration for Smart Trading Service."""

import os

# path to project
PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

# path to data
DATA_PATH = os.path.join(PROJECT_PATH, 'data')

# path to result folder
RESULT_PATH = os.path.join(PROJECT_PATH, 'results')
# path to flexibility folder
FLEX_PATH = os.path.join(DATA_PATH, 'DER_schedules')
# path to db-file
DB_FILE = os.path.join(RESULT_PATH, 'results.hdf5')

# time zone
LOCAL_TZ = 'Europe/Berlin'

# optional configuration for debugging clock
CLOCK = {
    'start': '2016-04-01T00:30:00+02:00',
    'stop': '2016-07-31T23:30:00+02:00',
    'speed_up': 100,
}

# agent configs  
N_AGENTS = 5

# Agent details
# in GENERAL_AGENT_DETAILS details can be specified that will be applied for all agents
# SPECIFIC_AGENT_DETAILS is a list of dictionaries, where details for the specific agents can be assigned:
#   unit name,
#   are schedules generated from files?,
#   directory of the schedule files,
#   specific schedule files
#
# if N_AGENTS > len(SPECIFIC_AGENT_DETAILS), remaining agents will be created with details within GENERAL_AGENT_DETAILS

GENERAL_AGENT_DETAILS = {
    'get_schedules_from_files': True,
    'schedule_dir': FLEX_PATH,
}

SPECIFIC_AGENT_DETAILS = [
    {
        'name': 'Household_0',
        'schedule_files': ['der0_schedules.csv', 'der5_schedules.csv'],
    },

    {
        'name': 'Household_1',
        'schedule_files': ['der1_schedules.csv', 'der2_schedules.csv', 'der5_schedules.csv'],
    },
    {'name': 'Household_2', },
    {'name': 'Household_3', },
    {'name': 'Household_4', },
]

# container configs
CTRL_OBS_CONTAINER = {'host': 'localhost', 'port': 5555}
# container for unit agents
AGENT_CONTAINER = [
                    {'host': 'localhost', 'port': 5556},
                    {'host': 'localhost', 'port': 5557}
]

# controller and observer configs
CTRL_CONFIG = {
    'n_agents': N_AGENTS,
    'negotiation_single_start': True,
    'negotiation_timeout': 15 * 60,           # seconds
    'topology_manager': 'controller.core.management:TopologyManager',
    'topology_phi': 1,          # We'll get a ring topology plus *at most* n_agents * phi connections.
    'topology_seed': None,      # random seed used for topology creation
    'scheduling_res': 15 * 60,  # resolution in seconds
    'scheduling_period': 1 * 24 * 60 * 60   # one day
}

OBS_CONFIG = {
    'n_agents': N_AGENTS,
    'log_dbcls': 'observer.core.monitoring:Monitoring',
    'log_dbfile': DB_FILE,
    'termcls': 'observer.core.termination:MessageCounter'}

# details for unit model or planner
UNIT_MODEL_CLS = 'sim_models.simmodels:DER'
UNIT_MODEL_CONFIG = {}

PLANNER_CLS = 'planning:Planner'
PLANNER_CONFIG = {'check_inbox_interval': .1}

# negotiations
NEGOTIATIONS = (
                {
                    'date': '2017-07-05T00:00:00+00:00',
                    'target': os.path.join(DATA_PATH, 'targets', 'electrical_target1.csv')
                },
                {
                    'date': '2017-07-06T00:00:00+00:00',
                    'target': os.path.join(DATA_PATH, 'targets', 'electrical_target2.csv')
                }
)
