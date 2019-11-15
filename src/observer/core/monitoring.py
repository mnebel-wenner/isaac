from asyncio import coroutine

import h5py

import numpy as np


class Monitoring:
    """Database for the storage of all agent and negotiation related
    data in the system.

    Stores values during negotiation and writes them to hdf5-database at
    the end of a negotiation.
    """
    def __init__(self, dbfile):
        self._db = h5py.File(dbfile, mode='w')
        self._db.create_group('dap')
        self._topgroup = None
        self._agent_addresses = {}
        self._agent_names = {}
        self._dap_data = []

    def setup(self, date, agent_addresses, agent_names):
        """Setup monitoring for a new run / negotiation.

        :param agent_names:
        :param agent_addresses:
        :param date: The begin date of the target_schedule for the
        negotiation.
        """
        self._agent_addresses = agent_addresses
        self._agent_names = agent_names
        self._dap_data = []

        group_name = date.format('YYYYMMDD')
        db_group = self._db['/dap'].create_group(group_name)
        self._topgroup = db_group

    @coroutine
    def flush(self, target_schedule, weights, solution):
        """Writes *target_schedule*, *weights*, *solution* and collected
        negotation data to hdf5 database.

        :param target_schedule: A list of values indicating the
        electrical target for the negotiation.
        :param weights: A list of weights [0,1] indicating the
        optimization weight of the respective value in the
        *target_schedule*
        :param solution: Cluster schedule as
        :class:`openvpp_agents.planning.Candidate`
        """
        dap_data, self._dap_data = self._dap_data, []

        # Extract DAP data to be stored
        db_group = self._topgroup
        target_weight_data = [tuple(i) for i in zip(target_schedule, weights)]
        dtype = np.dtype([
            ('target schedule', 'float64'),
            ('weights', 'float64')
        ])
        target_weight_data = np.array(target_weight_data, dtype=dtype)
        db_group.create_dataset('ts', data=target_weight_data)
        db_group.create_dataset('cs', data=solution.cs)

        agent_details = [''] * len(solution.idx)
        for agent_addr, index in solution.idx.items():
            agent_details[index] = (self._agent_names[agent_addr].encode(), agent_addr.encode(), index, solution.sids[index])
        dtype = np.dtype([
            ('Name', 'S100'),
            ('Address', 'S100'),
            ('Index in cs', 'int'),
            ('Internal Schedule ID', 'int')
        ])
        agent_data = np.array(agent_details, dtype=dtype)
        db_group.create_dataset('Agent details', data=agent_data)

        self._store_data(db_group, dap_data)
        self._db.flush()

    def close(self):
        """Close the database."""
        self._db.close()

    def append(self, row):
        """Store *row* in Database, but do not flush - this is done in
        either :meth:stop or :meth:flush_collected_data
        """
        self._dap_data.append(row)

    def store_topology(self, connections):
        """Write topology between unit agents specified by *connections*
        to hdf5 database using dap/*date* as group.

        :param connections: The topology as list of tuples
        (agent_1, agent_2), to be understood as bidirectional
        connections.
        """
        assert self._topgroup
        # create encoded data set
        dtype = np.dtype([
            ('agent 1', 'S100'),
            ('agent 2', 'S100'),
        ])
        conn_data = np.array([(a.encode(), b.encode())
                         for a, b in connections], dtype = dtype)
        # store data in group
        self._topgroup.create_dataset('topology', data=conn_data)

    def _store_data(self, group, dap_data):
        
        dtype = np.dtype([
            ('t', 'float64'),
            ('agent', 'S100'),
            ('perf', 'float64'),
            ('complete', bool),
            ('msgs_out', 'uint64'),
            ('msgs_in', 'uint64'),
            ('msg_sent', bool),
        ])
        dap_data = [(t, a.encode(), perf, complete, mo, mi, ms)
                    for t, a, perf, complete, mo, mi, ms in dap_data]
        dap_data = np.array(dap_data, dtype=dtype)
        group.create_dataset('dap_data', data=dap_data)
