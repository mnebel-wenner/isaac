import collections
import asyncio

from aiomas import expose
import aiomas

from unit import UnitInterface


STATE_BUFSIZE = 15  # We want to store that many state updates from our unit


class MosaikInterface(UnitInterface):
    router = aiomas.rpc.Service()

    def __init__(self, agent, agent_id, unit_id):
        self._agent = agent
        self._utcnow = agent.container.clock.utcnow
        self._aid = agent_id
        self._uid = unit_id
        self._state = collections.deque(maxlen=STATE_BUFSIZE)
        self._schedule = None
        self._sid = None
        self._last_setpoint = None
        self._received_new_schedule = asyncio.Future()
        # Register the interface's router as subrouter of the agent:
        agent.router.set_sub_router(self.router, 'unit')

    @property
    def state(self):
        return self._state

    @expose
    def update_state(self, data):
        row = (self._utcnow(), data)
        self._state.append(row)
        
    @expose
    def get_sid(self):
        return self._sid

    @expose
    def get_aid(self):
        return self._aid

    @expose
    def get_uid(self):
        return self._uid

    # called by controller, so that unit knows that it expects a new schedule
    @expose
    def new_negotiation(self):
        self._received_new_schedule = asyncio.Future()

    @expose
    def set_schedule(self, schedule_id):
        self._sid = schedule_id
        self._schedule = self._agent.model.get_schedule(schedule_id)
        self._received_new_schedule.set_result(True)

    @expose
    async def get_current_schedule(self):
        """Return a tuple (aid, uid, schedule_id)"""
        # wait until current negotiation is done
        await self._received_new_schedule
        if self._schedule is None:
            return None
        return self._aid, self._uid, self._sid
