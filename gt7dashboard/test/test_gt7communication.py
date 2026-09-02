import os
import struct
import time
import unittest

from Crypto.Cipher import Salsa20

from gt7dashboard import gt7communication
from gt7dashboard.gt7lap import Lap

PLAYSTATION_IP = "ps5wifi"


class RecordingSocket:
    def __init__(self):
        self.sent = []

    def sendto(self, data, address):
        self.sent.append((data, address))


def encrypt_packet(plaintext, xor_key, iv1=0x12345678):
    """Create a GT7-compatible encrypted packet for decoder tests."""
    nonce = struct.pack('<II', iv1 ^ xor_key, iv1)
    cipher = Salsa20.new(b'Simulator Interface Packet GT7 ver 0.0'[:32], nonce)
    encrypted = bytearray(cipher.encrypt(plaintext))
    # GT7 exposes this nonce seed in the UDP packet so that clients can decrypt it.
    encrypted[0x40:0x44] = struct.pack('<I', iv1)
    return bytes(encrypted)


def packet_for_format(packet_format, magic=gt7communication.PACKET_MAGIC):
    packet_size, xor_key = gt7communication.PACKET_FORMATS[packet_format]
    plaintext = bytearray(packet_size)
    struct.pack_into('<I', plaintext, 0x00, magic)
    struct.pack_into('<I', plaintext, 0x70, 42)
    return encrypt_packet(plaintext, xor_key)


class PacketDecoderTest(unittest.TestCase):
    def test_decodes_each_known_packet_format(self):
        for packet_format in gt7communication.PACKET_FORMATS:
            with self.subTest(packet_format=packet_format):
                decoded = gt7communication.salsa20_dec(packet_for_format(packet_format))
                self.assertIsNotNone(decoded)
                self.assertEqual(gt7communication.PACKET_MAGIC,
                                 struct.unpack('<I', decoded[0:4])[0])
                self.assertEqual(
                    packet_format,
                    gt7communication.PACKET_FORMATS_BY_SIZE[len(decoded)][0],
                )

    def test_rejects_unknown_size_and_invalid_magic(self):
        self.assertIsNone(gt7communication.salsa20_dec(b'not a GT7 packet'))
        self.assertIsNone(gt7communication.salsa20_dec(packet_for_format('C', 0)))

    def test_decodes_packet_c_fields(self):
        packet_size, xor_key = gt7communication.PACKET_FORMATS['C']
        plaintext = bytearray(packet_size)
        struct.pack_into('<I', plaintext, 0x00, gt7communication.PACKET_MAGIC)
        struct.pack_into('<I', plaintext, 0x70, 42)
        struct.pack_into('<fffff', plaintext, 0x128, 1.25, 2.5, -3.75, 4.0, 5.5)
        plaintext[0x13C:0x140] = b'TCGS'
        struct.pack_into('<I', plaintext, 0x140, 91234)
        struct.pack_into('<ff', plaintext, 0x144, -0.25, 0.5)
        struct.pack_into('<f', plaintext, 0x14C, 2.65)
        plaintext[0x150:0x154] = b'GR3\0'

        decoded = gt7communication.salsa20_dec(encrypt_packet(plaintext, xor_key))
        data = gt7communication.GTData(decoded)

        self.assertEqual('C', data.packet_format)
        self.assertEqual(('T', 'C', 'G', 'S'), data.surface_type)
        self.assertEqual(91234, data.current_lap_time_ms)
        self.assertAlmostEqual(-0.25, data.front_wheel_steering_angle_rad[0])
        self.assertAlmostEqual(0.5, data.front_wheel_steering_angle_rad[1])
        self.assertAlmostEqual(2.65, data.wheel_base_m, places=6)
        self.assertEqual('GR3', data.car_category)
        self.assertAlmostEqual(1.25, data.wheel_rotation_rad)
        self.assertAlmostEqual(2.5, data.steering_angular_velocity_rad_s)
        self.assertAlmostEqual(-3.75, data.sway_acceleration)
        self.assertAlmostEqual(4.0, data.heave_acceleration)
        self.assertAlmostEqual(5.5, data.surge_acceleration)
        self.assertIsNone(data.throttle_filtered_percent)
        self.assertIsNone(data.torque_vectors)

    def test_decodes_packet_b_fields(self):
        packet_size, xor_key = gt7communication.PACKET_FORMATS['B']
        plaintext = bytearray(packet_size)
        struct.pack_into('<I', plaintext, 0x00, gt7communication.PACKET_MAGIC)
        struct.pack_into('<I', plaintext, 0x70, 42)
        struct.pack_into('<fffff', plaintext, 0x128, 1.25, 2.5, -3.75, 4.0, 5.5)

        data = gt7communication.GTData(
            gt7communication.salsa20_dec(encrypt_packet(plaintext, xor_key))
        )

        self.assertEqual('B', data.packet_format)
        self.assertAlmostEqual(1.25, data.wheel_rotation_rad)
        self.assertAlmostEqual(2.5, data.steering_angular_velocity_rad_s)
        self.assertAlmostEqual(-3.75, data.sway_acceleration)
        self.assertAlmostEqual(4.0, data.heave_acceleration)
        self.assertAlmostEqual(5.5, data.surge_acceleration)
        self.assertIsNone(data.throttle_filtered_percent)

    def test_decodes_packet_tilde_fields(self):
        packet_size, xor_key = gt7communication.PACKET_FORMATS['~']
        plaintext = bytearray(packet_size)
        struct.pack_into('<I', plaintext, 0x00, gt7communication.PACKET_MAGIC)
        struct.pack_into('<I', plaintext, 0x70, 42)
        plaintext[0x13C:0x13E] = bytes((128, 64))
        struct.pack_into('<ffff', plaintext, 0x140, 1.0, -2.0, 3.0, -4.0)
        struct.pack_into('<f', plaintext, 0x150, 0.75)

        data = gt7communication.GTData(
            gt7communication.salsa20_dec(encrypt_packet(plaintext, xor_key))
        )

        self.assertEqual('~', data.packet_format)
        self.assertAlmostEqual(128 / 2.55, data.throttle_filtered_percent)
        self.assertAlmostEqual(64 / 2.55, data.brake_filtered_percent)
        self.assertEqual((1.0, -2.0, 3.0, -4.0), data.torque_vectors)
        self.assertAlmostEqual(0.75, data.energy_recovery)
        self.assertAlmostEqual(0.0, data.wheel_rotation_rad)
        self.assertIsNone(data.surface_type)

    def test_a_packet_keeps_c_fields_empty(self):
        data = gt7communication.GTData(gt7communication.salsa20_dec(packet_for_format('A')))
        self.assertEqual('A', data.packet_format)
        self.assertIsNone(data.wheel_rotation_rad)
        self.assertIsNone(data.throttle_filtered_percent)
        self.assertIsNone(data.surface_type)
        self.assertIsNone(data.current_lap_time_ms)

    def test_packet_format_selects_heartbeat(self):
        socket = RecordingSocket()
        communication = gt7communication.GT7Communication('192.0.2.1', 'C')
        communication._send_hb(socket)
        self.assertEqual([(b'C', ('192.0.2.1', 33739))], socket.sent)

    def test_packet_format_validation(self):
        self.assertEqual('C', gt7communication.normalise_packet_format(' c '))
        with self.assertRaises(ValueError):
            gt7communication.GT7Communication('192.0.2.1', 'D')


# check if host is up
def is_host_up(ip: str) -> bool:
    response = os.system("ping -c 1 " + PLAYSTATION_IP)

    #and then check the response...
    if response == 0:
        return True
    else:
        return False


@unittest.skipIf(not is_host_up(PLAYSTATION_IP),
                 "Playstation host is not up on %s" % (PLAYSTATION_IP))
class GT7CommunicationTest(unittest.TestCase):
    @classmethod
    def setUpClass(self) -> None:
        self.gt7comm = gt7communication.GT7Communication(PLAYSTATION_IP)
        # Do not quit with the main process
        self.gt7comm.daemon = False
        self.gt7comm.start()
        # Sleep until connection is setup
        # TODO Add timeout
        while not self.gt7comm.is_connected():
            time.sleep(0.1)

    @classmethod
    def tearDownClass(self) -> None:
        self.gt7comm.stop()

    def test_get_water_temp(self):
        car_data = self.gt7comm.get_last_data()
        self.assertTrue(self.gt7comm.is_connected())
        # is always 85
        self.assertEqual(85, car_data.water_temp)

    # def test_run_add_debug(self):
    #     while self.gt7comm.is_connected():
    #         car_data = self.gt7comm.get_last_data()
    #         # print(car_data.rpm, car_data.in_race)

    def test_load_laps(self):
        self.gt7comm.laps = [Lap()]
        self.gt7comm.laps[0].number = 0

        laps = [Lap(), Lap()]
        laps[0].number = 1
        laps[1].number = 2

        self.gt7comm.load_laps(laps, to_last_position=True)
        self.assertEqual(3, len(self.gt7comm.laps))
        self.assertEqual(1, self.gt7comm.laps[1].number)

        self.gt7comm.load_laps(laps, to_first_position=True)
        self.assertEqual(5, len(self.gt7comm.laps))
        self.assertEqual(1, self.gt7comm.laps[3].number)

        self.gt7comm.load_laps(laps, replace_other_laps=True)
        self.assertEqual(2, len(self.gt7comm.laps))
        self.assertEqual(1, self.gt7comm.laps[0].number)
