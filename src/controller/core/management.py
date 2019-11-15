import random


class TopologyManager:
    """Builds and manages the small world topology of a COHDA-based MAS.

    """
    def __init__(self, phi=1, seed=None):
        self._agent_addresses = None
        self._topology = None
        self._topology_phi = phi
        self._topology_seed = seed

    def make_topology(self, agents):
        # agent_addresses is a dict of agent proxies: agent address
        self._agent_addresses = agents
        assert self._agent_addresses is not None
        # All connections must be symetric and irreflexive.
        # That means, for each connection A -> B:
        # - A != B (no connection to self)
        # - If A connects to B, than B connects to A
        n_agents = len(self._agent_addresses)

        # Build list of agent proxies sorted by their address
        agent_list = [a for a, _ in sorted(self._agent_addresses.items(),
                                           key=lambda x: x[1])]
        # MNW: Does that not have to be {agent: set() for agent in agent_list}?
        self._topology = {agent: set() for agent in self._agent_addresses}
        if n_agents == 1:
            return self._topology

        self._build_ring(agent_list, n_agents)
        self._add_random_topology(agent_list)
        return self._topology

    def _build_ring(self, agent_list, n_agents):
        for i, agent in enumerate(agent_list):
            # Get left and right agent
            agent_left = agent_list[(i - 1) % n_agents]
            agent_right = agent_list[(i + 1) % n_agents]

            # Add addresses of left and right to the agents connect-set
            self._topology[agent].add(self._agent_addresses[agent_left])
            self._topology[agent].add(self._agent_addresses[agent_right])

    def _add_random_topology(self, agent_list):
        rnd = random.Random(self._topology_seed)

        # Add some random connections ("small world")
        for _ in range(int(len(agent_list) * self._topology_phi)):
            # We'll get *at most* n_agent * phi connections.

            agent_a = rnd.choice(agent_list)
            agent_b = rnd.choice(agent_list)

            if agent_a is agent_b:
                continue

            self._topology[agent_a].add(self._agent_addresses[agent_b])
            self._topology[agent_b].add(self._agent_addresses[agent_a])

    def topology_as_list(self, agent_names):
        """Return the topology as list of tuples (agent_1, agent_2), to
        be understood as bidirectional
        :param agent_names: dictionary mapping from agent_addr to agent

        """
        assert self._topology is not None
        assert self._agent_addresses is not None

        connections = set()
        for agent_proxy, remotes in self._topology.items():
            # Convert proxy to str
            agent_addr = self._agent_addresses[agent_proxy]
            for others_addr in remotes:  # remotes is already list of addresses as string
                # Merge two directed connections into one bidirectional one
                con = (agent_names[agent_addr], agent_names[others_addr]) if agent_addr < others_addr else (agent_names[others_addr], agent_names[agent_addr])
                connections.add(con)
        topology_list = sorted(connections)
        return topology_list
