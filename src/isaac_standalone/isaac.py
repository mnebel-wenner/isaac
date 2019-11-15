"""Main process module of Smart Trading Service."""
import asyncio

from os.path import isfile
import io
import json
import logging
import lzma

import aiomas

import isaac_standalone.config as config
import isaac_util.debug as debug
import isaac_util.util as util

from unit import UnitAgent
from controller.controller import ControllerAgent
from observer.observer import ObserverAgent


def main():
    """Open VPP multi-agent system."""
    try:
        # set log_level
        logging.getLogger('').setLevel('DEBUG')
        # set file handler
        logging.getLogger('').addHandler(util.get_log_file_handler('isaac_standalone.log'))
        # set console handler
        logging.getLogger('').addHandler(util.get_log_console_handler())
        print('[main] starting aiomas')
        aiomas.run(until=run())
    except KeyboardInterrupt:
        print('[main] Interrupting execution.')
    finally:
        print('[main] Simulation done')
        

def read_target_schedule(path_to_target_file, n_sim_steps=96):
    """
    Read taget file and return target schedule and weights
    """
    assert isfile(path_to_target_file)
    # open the target file and read the header
    my_open = lzma.open if path_to_target_file.endswith('.xz') else io.open
    target_file = my_open(path_to_target_file, 'rt')
    line = next(target_file).strip()
    targets_meta = json.loads(line)
    assert targets_meta['interval_minutes'] == 15

    # create initial lists
    target_schedule = [0.0] * n_sim_steps
    weights = [1.0] * n_sim_steps
    # load the target schedule
    for i in range(n_sim_steps):
        data = next(target_file).strip().split(',')
        target_schedule[i] = float(data[0])
        weights[i] = float(data[1])
    return target_schedule, weights


async def run():

    """Process handling."""
    # DEBUG: create container specific clock
    start = config.CLOCK['start']
    stop = config.CLOCK['stop']
    speed_up = config.CLOCK['speed_up']
    clock = debug.DebuggingClock(start, stop, speed_up)

    # Details for controller / observer
    my_controller_config = config.CTRL_CONFIG
    
    my_observer_cls = ObserverAgent
    my_observer_config = config.OBS_CONFIG

    # Details for unitModel and Planner
    my_unit_model_cls = config.UNIT_MODEL_CLS
    general_unit_model_config = config.UNIT_MODEL_CONFIG

    my_planner_cls = config.PLANNER_CLS
    my_planner_config = config.PLANNER_CONFIG
    
    # create local container for controller and observer 
    print('[run] Creating one container for Controller / Observer... ', end='')
    host = config.CTRL_OBS_CONTAINER['host']
    port = config.CTRL_OBS_CONTAINER['port']
    container_1 = await aiomas.Container.create(
        (host, port), codec=aiomas.MsgPack, clock=clock,
        extra_serializers=util.get_extra_serializers(), as_coro=True)
    print('Done!')
    
    # create local container for unitAgents
    print('[run] Creating %s container for unitAgents... ' % len(config.AGENT_CONTAINER), end='')
    container_config = config.AGENT_CONTAINER
    n_container = len(container_config)
    agent_container = []
    for i in range(n_container):
        host = container_config[i]['host']
        port = container_config[i]['port']
        container = await aiomas.Container.create(
            (host, port), codec=aiomas.MsgPack, clock=clock,
            extra_serializers=util.get_extra_serializers(), as_coro=True)
        agent_container.append(container)
    print('Done!')
    
    # instantiate controller / observer
    print('[run] Initializing Controller / Observer... ', end='')
    ctrl, obs = await ControllerAgent.factory(
        container_1,
        my_controller_config,
        my_observer_cls,
        my_observer_config
    )
    print('Done!')

    # instantiate UnitAgents
    print('[run] Initializing UnitAgents.')

    for i in range(config.N_AGENTS):
        # get details from general_unit_model_config set in config
        agents_unit_model_config = {key: value for key, value in general_unit_model_config.items()}
        # add details from GENERAL_AGENT_DETAILS provided in config
        for key, value in config.GENERAL_AGENT_DETAILS.items():
            agents_unit_model_config[key] = value

        # details for current agent are provided in config
        if i < len(config.SPECIFIC_AGENT_DETAILS):
            agent_details = config.SPECIFIC_AGENT_DETAILS[i]
            # pop unit name from dict first
            unit_name = agent_details.pop('name', None)
            # so far, all other details have to be passed to the unit model
            for key, value in agent_details.items():
                agents_unit_model_config[key] = value
        else:
            unit_name = None

        # make sure non-optional kwargs are provided
        assert 'get_schedules_from_files' in agents_unit_model_config.keys(),\
            'Non optional kwarg \'get_schedules_from_files\' is not provided for Agent {}'.format(str(i))
        if agents_unit_model_config['get_schedules_from_files']:
            assert 'schedule_dir' in agents_unit_model_config.keys(), \
                'No schedule directory specified for Agent {}'.format(str(i))

        # create uni_agent
        unit_agent = await UnitAgent.factory(
            agent_container[i % n_container],
            ctrl_agent_addr=ctrl.addr,
            obs_agent_addr=obs.addr,
            unit_model=(my_unit_model_cls, agents_unit_model_config),
            unit_if=None,
            planner=(my_planner_cls, my_planner_config),
            unit_name=unit_name
        )
        del unit_agent

    # run agents and services until manually cancelled or stop time is reached
    try:
        print('[run] Wait for all agents to be registered... ', end='')
        await ctrl._agents_registered
        await ctrl._observer_registered
        print('Done')
        
        print('[run] Call controller to run negotiation...')
        
        neg_counter = 0
        for negotiation in sorted(config.NEGOTIATIONS, key=lambda x: x['date']):
            neg_counter += 1
            target_file_path = negotiation['target']
            startdate = negotiation['date']
            # read the target schedule
            target_schedule, weights = read_target_schedule(target_file_path)
            print('\n**********  %s. NEGOTIATION ***********' % neg_counter)
            print('Date: %s\nTarget: %s\n' % (startdate, target_file_path))
            await ctrl.run_negotiation(startdate, target_schedule, weights)
            
        print('\n**********  END NEGOTIATIONS ***********\n') 

    except KeyboardInterrupt:
        print('[run] Interrupting execution.')
    finally:
        # gracefully cancel async processes
        print('[run] Stopping planner tasks if still running... ', end='')
        futs = [a.stop() for a in ctrl._agents.keys()]
        await asyncio.gather(*futs)
        print('Done!')
        
        print('[run] Stopping controller and observer tasks... ', end='')
        await ctrl.stop()
        await obs.stop()
        print('Done!')
    
        # close all connections and shutdown server
        print('[run] Shutting down containers... ', end='')
        await container_1.shutdown(as_coro=True)
        for i in range(n_container):
            await agent_container[i].shutdown(as_coro=True)
        print('Done!')


if __name__ == '__main__':
    main()
