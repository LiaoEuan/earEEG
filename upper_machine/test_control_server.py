import unittest

from upper_machine.lsl_proxy.control_server import ProxyController, ProxyStatus


class FakeClient:
    def __init__(self):
        self.connected = True
        self.started = 0
        self.stopped = 0
        self.impedance_commands = []
        self.impedance_stopped = 0

    def start_acquisition(self):
        self.started += 1
        return True

    def stop_acquisition(self):
        self.stopped += 1
        return True

    def set_impedance(self, command):
        self.impedance_commands.append(command)
        return True

    def stop_impedance(self):
        self.impedance_stopped += 1
        return True


class ProxyControllerTest(unittest.TestCase):
    def test_acquisition_state_and_status(self):
        client = FakeClient()
        controller = None

        def status_provider():
            return ProxyStatus(
                connected=client.connected,
                acquiring=controller.acquiring,
                frame_count=250,
                lost_packets=1,
                fps=250.0,
                loss_percent=0.4,
                last_error=controller.last_error,
            )

        controller = ProxyController(client, status_provider)

        self.assertEqual(controller.start_acquisition(), {"ok": True, "acquiring": True})
        self.assertTrue(controller.acquiring)
        self.assertEqual(client.started, 1)
        self.assertEqual(controller.status()["frameCount"], 250)

        self.assertEqual(controller.stop_acquisition(), {"ok": True, "acquiring": False})
        self.assertFalse(controller.acquiring)
        self.assertEqual(client.stopped, 1)

    def test_rejects_commands_when_disconnected(self):
        client = FakeClient()
        client.connected = False
        controller = ProxyController(
            client,
            lambda: ProxyStatus(False, False, 0, 0, 0.0, 0.0, ""),
        )

        result = controller.start_acquisition()

        self.assertFalse(result["ok"])
        self.assertIn("not connected", result["error"])
        self.assertEqual(client.started, 0)

    def test_impedance_commands_use_the_shared_client(self):
        client = FakeClient()
        controller = ProxyController(
            client,
            lambda: ProxyStatus(True, False, 0, 0, 0.0, 0.0, ""),
        )

        self.assertTrue(controller.set_impedance("z110Z")["ok"])
        self.assertTrue(controller.stop_impedance()["ok"])
        self.assertEqual(client.impedance_commands, ["z110Z"])
        self.assertEqual(client.impedance_stopped, 1)

    def test_audio_errors_are_reported(self):
        client = FakeClient()
        controller = ProxyController(
            client,
            lambda: ProxyStatus(True, False, 0, 0, 0.0, 0.0, ""),
        )

        missing = controller.play_audio("missing.wav")
        paused = controller.pause_audio()

        self.assertFalse(missing["ok"])
        self.assertIn("not found", missing["error"])
        self.assertFalse(paused["ok"])
        self.assertIn("no audio playback", paused["error"])


if __name__ == "__main__":
    unittest.main()
