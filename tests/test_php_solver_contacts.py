"""Check that a solved MuJoCo collision yields a real foot/terrain force."""

import unittest

import mujoco

from scripts.php_solver_contacts import geom_maps, snapshot


class SolverContactTest(unittest.TestCase):
    def test_live_collision_force_disappears_when_foot_lifts(self):
        model = mujoco.MjModel.from_xml_string("""
            <mujoco>
              <worldbody>
                <geom name="floor" type="plane" size="1 1 0.1"/>
                <body name="foot" pos="0 0 0.06">
                  <freejoint/>
                  <geom name="left_foot_collision" type="sphere" size="0.1" mass="1"/>
                </body>
              </worldbody>
            </mujoco>
        """)
        data = mujoco.MjData(model)
        terrain, feet = geom_maps(model)
        mujoco.mj_forward(model, data)
        contacts = snapshot(model, data, terrain, feet)
        self.assertEqual(len(contacts), 1)
        self.assertEqual((contacts[0]["terrain"], contacts[0]["foot"]),
                         ("floor", "left"))
        self.assertGreater(contacts[0]["normal_force_n"], 0)

        data.qpos[2] += 1.0
        mujoco.mj_forward(model, data)
        self.assertEqual(snapshot(model, data, terrain, feet), [])


if __name__ == "__main__":
    unittest.main()
