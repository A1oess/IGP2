import pytest
import numpy as np
import matplotlib.pyplot as plt

from igp2.agent import AgentState
from igp2.opendrive.map import Map
from igp2.opendrive.plot_map import plot_map
from igp2.planlibrary.macro_action import ChangeLaneLeft, ChangeLaneRight, Continue, Exit

SCENARIOS = {"heckstrasse": Map.parse_from_opendrive("scenarios/maps/heckstrasse.xodr"),
             "round": Map.parse_from_opendrive("scenarios/maps/round.xodr"),
             "test_lane_change": Map.parse_from_opendrive("scenarios/maps/test_change_lane.xodr")}


class TestMacroAction:
    def test_lane_change_heckstrasse(self):
        scenario_map = SCENARIOS["heckstrasse"]
        frame = {
            0: AgentState(time=0,
                          position=np.array([26.9, -19.3]),
                          velocity=5.5,
                          acceleration=0.0,
                          heading=np.pi),
            1: AgentState(time=0,
                          position=np.array([6.0, 0.7]),
                          velocity=1.5,
                          acceleration=0.0,
                          heading=-np.pi/8),
        }

        plot_map(scenario_map, markings=True)
        for agent_id, agent in frame.items():
            plt.plot(agent.position[0], agent.position[1], marker="o")

        lane_change = ChangeLaneRight(1, frame, scenario_map, True)
        trajectory = lane_change.get_trajectory().path
        plt.plot(trajectory[:, 0], trajectory[:, 1], color="orange")

        plt.show()

    def test_turn_heckstrasse(self):
        scenario_map = SCENARIOS["heckstrasse"]
        frame = {
            0: AgentState(time=0,
                          position=np.array([6.0, 0.7]),
                          velocity=1.5,
                          acceleration=0.0,
                          heading=np.pi),
            1: AgentState(time=0,
                          position=np.array([19.7, -13.5]),
                          velocity=8.5,
                          acceleration=0.0,
                          heading=np.pi),
            2: AgentState(time=0,
                          position=np.array([73.2, -47.1]),
                          velocity=11.5,
                          acceleration=0.0,
                          heading=np.pi),
        }
        plot_map(scenario_map, markings=True, midline=False)
        for agent_id, agent in frame.items():
            plt.plot(agent.position[0], agent.position[1], marker="o")

        lane_change = Exit(np.array([49.44, -23.1]), 0, frame, scenario_map, True)
        trajectory = lane_change.get_trajectory().path
        plt.plot(trajectory[:, 0], trajectory[:, 1], color="blue")

        lane_change = Exit(np.array([62.34, -46.67]), 1, frame, scenario_map, True)
        trajectory = lane_change.get_trajectory().path
        plt.plot(trajectory[:, 0], trajectory[:, 1], color="orange")

        lane_change = Exit(np.array([66.3, -17.8]), 2, frame, scenario_map, True)
        trajectory = lane_change.get_trajectory().path
        plt.plot(trajectory[:, 0], trajectory[:, 1], color="green")

        plt.show()

    def test_lane_change_test_map(self):
        scenario_map = SCENARIOS["test_lane_change"]
        frame = {
            0: AgentState(time=0,
                          position=np.array([89.9, 4.64]),
                          velocity=11.5,
                          acceleration=0.0,
                          heading=np.pi),
            1: AgentState(time=0,
                          position=np.array([79.7, 1.27]),
                          velocity=1.5,
                          acceleration=0.0,
                          heading=np.pi),
            2: AgentState(time=0,
                          position=np.array([71.7, 1.27]),
                          velocity=4.5,
                          acceleration=0.0,
                          heading=np.pi),
            3: AgentState(time=0,
                          position=np.array([111.0, -1.34]),
                          velocity=9.5,
                          acceleration=0.0,
                          heading=np.pi / 8.5),
            4: AgentState(time=0,
                          position=np.array([128.7, -0.49]),
                          velocity=4.5,
                          acceleration=0.0,
                          heading=np.pi / 6),
            5: AgentState(time=0,
                          position=np.array([137.0, 8.5]),
                          velocity=10.0,
                          acceleration=0.0,
                          heading=np.pi / 2),
        }
        plot_map(scenario_map, markings=True, midline=False)
        for agent_id, agent in frame.items():
            plt.plot(agent.position[0], agent.position[1], marker="o")

        lane_change = ChangeLaneLeft(0, frame, scenario_map, True)
        trajectory = lane_change.get_trajectory().path
        plt.plot(trajectory[:, 0], trajectory[:, 1], color="b")

        lane_change = ChangeLaneRight(1, frame, scenario_map, True)
        trajectory = lane_change.get_trajectory().path
        plt.plot(trajectory[:, 0], trajectory[:, 1], color="orange")

        lane_change = ChangeLaneRight(2, frame, scenario_map, True)
        trajectory = lane_change.get_trajectory().path
        plt.plot(trajectory[:, 0], trajectory[:, 1], color="green")

        lane_change = ChangeLaneRight(3, frame, scenario_map, True)
        trajectory = lane_change.get_trajectory().path
        plt.plot(trajectory[:, 0], trajectory[:, 1], color="red")

        lane_change = ChangeLaneLeft(4, frame, scenario_map, True)
        trajectory = lane_change.get_trajectory().path
        plt.plot(trajectory[:, 0], trajectory[:, 1], color="purple")

        lane_change = ChangeLaneRight(5, frame, scenario_map, True)
        trajectory = lane_change.get_trajectory().path
        plt.plot(trajectory[:, 0], trajectory[:, 1], color="brown")

        plt.show()