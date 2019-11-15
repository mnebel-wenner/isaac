import asyncio
from asyncio import coroutine
import random

from aiomas import expose
import aiomas


class UnitAgent(aiomas.Agent):
    """ The unitAgent is the center of the planning procedure.

    It has a model of the unit (defined by the interface *UnitModel*),
        which mainly generates schedules
    It has a *planner* (defined by the interface *Planner*), which
        is responsible for the negotiation
    It talks to the actual unit via its unit interface *unit_if*.

    """
    @classmethod
    async def factory(
            cls, container, *, ctrl_agent_addr, obs_agent_addr, unit_model,
            unit_if=None, planner, sleep_before_connect=True, unit_name=None):
        """
        Use this method to create a new unitAgent.
        After instantiating, the unitAgent will register itself at the 
                controller and observer.
        :param container: The container, in which the agent should live
        :param ctrl_agent_addr: Address of the controller agent
        :param obs_agent_addr: Address of the observer agent
        :param unit_model: A tuple of (classname, config) for the unitModel
        :param unit_if: A tuple of (classname, config) for the unit
        :param planner: A tuple of (classname, config) for the planner
        :param sleep_before_connect: If true, unitAgent will sleep some random
                time before connecting to controller/observer to avoid that all
                agents try to connect at the same time
        :return: The instance of the unitAgent
        
        """
        # Sleep a short time to avoid that all agents try to connect to the
        # ctrl_agent at the same time.
        if sleep_before_connect:
            await asyncio.sleep(
                float(sleep_before_connect) * random.random())

        ctrl_agent = await container.connect(ctrl_agent_addr)
        obs_agent = await container.connect(obs_agent_addr)
        agent = cls(container, ctrl_agent, obs_agent,
                    unit_model, unit_if, planner, unit_name)
        await ctrl_agent.register_unitAgent(agent, agent.addr, unit_name)
        await obs_agent.register_unitAgent(agent, agent.addr, unit_name)

        return agent

    def __init__(self, container, ctrl_agent, obs_agent, unit_model,
                 unit_if, planner, unit_name=None):
        """
        For normal system setup, do not directly initiate this class,
        but use the factory provided at `unit.UnitAgent.factory`
        """
        super().__init__(container)
        
        self.ctrl_agent = ctrl_agent
        self.obs_agent = obs_agent
        self.name = unit_name if unit_name else self.addr
        
        # create a unit_model
        clsname, config = unit_model
        cls = aiomas.util.obj_from_str(clsname)

        self.model = cls(**config)
        assert isinstance(self.model, UnitModel)

        # create the unit
        if unit_if:
            clsname, config = unit_if
            cls = aiomas.util.obj_from_str(clsname)
            self.unit = cls(self, **config)
            assert isinstance(self.unit, UnitInterface)
        else:
            self.unit = None

        # create the planner
        clsname, config = planner
        cls = aiomas.util.obj_from_str(clsname)
        self.planner = cls(self, **config)
        assert isinstance(self.planner, Planner)

        # Expose/alias functions for the ControllerAgent
        self.set_possible_schedules = self.model.set_possible_schedules

        self.store_topology = self.planner.store_topology
        self.init_negotiation = self.planner.init_negotiation
        self.stop_negotiation = self.planner.stop_negotiation

        if self.unit is not None:
            self.set_schedule = self.unit.set_schedule
            self.new_negotiation = self.unit.new_negotiation
            self.get_current_schedule = self.unit.get_current_schedule
        else:
           self.new_negotiation = self.get_current_schedule = aiomas.rpc.expose(lambda: None)
           self.set_schedule = aiomas.rpc.expose(lambda x: None)

        # Expose/alias function for other UnitAgents
        self.update = self.planner.update

    @expose  # Called by a Management agent (e.g., mosaik API)
    def stop(self):
        self.planner.stop()


class UnitModel:
    def __init__(self, **config):
        pass

    def get_schedule(self, schedule_id):
        raise NotImplementedError

    @expose
    def update_forecast(self, fc):
        raise NotImplementedError

    def generate_schedules(self, start, res, intervals, state):
        """Generate new schedule for the period specified by *start*, *res*
        and *intervals* based on the current unit *state*.

        :param start: The start of the schedule
        :param res: Temporal resolution of the schedule (might be different
                    from the model's internal resolution).
        :param intervals: Number of intervals in the schedule.
        :param state: The current state of the unit.
        :return: A list of tuples *(id, utility, data)*.

        """
        raise NotImplementedError


class UnitInterface:
    router = aiomas.rpc.Service()

    def __init__(self, agent, **config):
        pass

    @property
    def state(self):
        raise NotImplementedError

    @expose
    def update_state(self, data):
        raise NotImplementedError

    @expose
    def set_schedule(self, schedule_id):
        raise NotImplementedError

    @expose
    def get_setpoint(self, time):
        pass


class Planner:
    def __init__(self, agent, **config):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    @expose
    @coroutine
    def init_negotiation(self, neighbors, start, res, target_schedule, weights,
                         send_wm):
        raise NotImplementedError

    @expose
    def stop_negotiation(self):
        raise NotImplementedError

    @expose
    def update(self, sysconf_other, candidate_other):
        raise NotImplementedError
