# -*- coding: latin-1 -*-
# -----------------------------------------------------------------------------
# Copyright 2009-2015 Stephen Tiedemann <stephen.tiedemann@gmail.com>
#
# Licensed under the EUPL, Version 1.1 or - as soon they 
# will be approved by the European Commission - subsequent
# versions of the EUPL (the "Licence");
# You may not use this work except in compliance with the
# Licence.
# You may obtain a copy of the Licence at:
#
# http://www.osor.eu/eupl
#
# Unless required by applicable law or agreed to in
# writing, software distributed under the Licence is
# distributed on an "AS IS" basis,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied.
# See the Licence for the specific language governing
# permissions and limitations under the Licence.
# -----------------------------------------------------------------------------
#
# Driver for NXP PN532 based contactless readers.
#
import logging
log = logging.getLogger(__name__)

import time

import nfc.clf
from . import pn53x
            
class Chipset(pn53x.Chipset):
    CMD = {
        # Miscellaneous
        0x00: "Diagnose",
        0x02: "GetFirmwareVersion",
        0x04: "GetGeneralStatus",
        0x06: "ReadRegister",
        0x08: "WriteRegister",
        0x0C: "ReadGPIO",
        0x0E: "WriteGPIO",
        0x10: "SetSerialBaudrate",
        0x12: "SetParameters",
        0x14: "SAMConfiguration",
        0x16: "PowerDown",
        # RF communication
        0x32: "RFConfiguration",
        0x58: "RFRegulationTest",
        # Initiator
        0x56: "InJumpForDEP",
        0x46: "InJumpForPSL",
        0x4A: "InListPassiveTarget",
        0x50: "InATR",
        0x4E: "InPSL",
        0x40: "InDataExchange",
        0x42: "InCommunicateThru",
        0x44: "InDeselect",
        0x52: "InRelease",
        0x54: "InSelect",
        0x60: "InAutoPoll",
        # Target
        0x8C: "TgInitAsTarget",
        0x92: "TgSetGeneralBytes",
        0x86: "TgGetData",
        0x8E: "TgSetData",
        0x94: "TgSetMetaData",
        0x88: "TgGetInitiatorCommand",
        0x90: "TgResponseToInitiator",
        0x8A: "TgGetTargetStatus",
    }
    ERR = {
        0x01: "Time out, the Target has not answered",
        0x02: "Checksum error during RF communication",
        0x03: "Parity error during RF communication",
        0x04: "Erroneous bit count in anticollision",
        0x05: "Framing error during Mifare operation",
        0x06: "Abnormal bit collision in 106 kbps anticollision",
        0x07: "Insufficient communication buffer size",
        0x09: "RF buffer overflow detected by CIU",
        0x0a: "RF field not activated in time by active mode peer",
        0x0b: "Protocol error during RF communication",
        0x0d: "Overheated - antenna drivers deactivated",
        0x0e: "Internal buffer overflow",
        0x10: "Invalid command parameter",
        0x12: "Unsupported command from Initiator",
        0x13: "Format error during RF communication",
        0x14: "Mifare authentication error",
        0x23: "ISO/IEC14443-3 UID check byte is wrong",
        0x25: "Command invalid in current DEP state",
        0x26: "Operation not allowed in this configuration",
        0x27: "Command is not acceptable in the current context",
        0x29: "Released by Initiator while operating as Target",
        0x2A: "ISO/IEC14443-3B, the ID of the card does not match",
        0x2B: "ISO/IEC14443-3B, card previously activated has disappeared",
        0x2C: "NFCID3i and NFCID3t mismatch in DEP 212/424 kbps passive",
        0x2D: "An over-current event has been detected",
        0x2E: "NAD missing in DEP frame",
        0x7f: "Invalid command syntax - received error frame",
        0xff: "Insufficient data received from executing chip command",
    }

    host_command_frame_max_size = 265
    in_list_passive_target_max_target = 2
    in_list_passive_target_brty_range = (0, 1, 2, 3, 4)

    def _read_register(self, data):
        return self.command(0x06, data, timeout=250)

    def _write_register(self, data):
        self.command(0x08, data, timeout=250)
        
    def set_serial_baudrate(self, baudrate):
        br = (9600,19200,38400,57600,115200,230400,460800,921600,1288000)
        self.command(0x10, chr(br.index(baudrate)), timeout=100)
        self.write_frame(self.ACK)

    def sam_configuration(self, mode, timeout=0, irq=False):
        mode = ("normal", "virtual", "wired", "dual").index(mode) + 1
        self.command(0x14, bytearray([mode, timeout, int(irq)]), timeout=100)

    power_down_wakeup_src = ("INT0","INT1","rfu","RF","HSU","SPI","GPIO","I2C")
    def power_down(self, wakeup_enable, generate_irq=False):
        wakeup_set = 0
        for i, src in enumerate(self.power_down_wakeup_src):
            if src in wakeup_enable: wakeup_set |= 1 << i
        cmd_data = bytearray([wakeup_set, int(generate_irq)])
        data = self.command(0x16, cmd_data, timeout=100)
        if data[0] != 0: self.chipset_error(data)

    def in_auto_poll(self, poll_nr, period, *types):
        assert len(types) <= 15
        timeout = poll_nr * len(types) * period * 150 + 100
        data = chr(poll_nr) + chr(period) + bytearray(types)
        data = self.command(0x60, data, timeout=timeout)
        targets = []
        for i in data.pop(0):
            tg_type = data.pop(0)
            tg_data = data[:data.pop(0)]
            targets.append((tg_type, tg_data))
        return targets

    def tg_init_as_target(self, mode, mifare_params, felica_params, nfcid3t,
                          general_bytes='', historical_bytes='', timeout=None):
        assert type(mode) is int and mode & 0b11111000 == 0
        assert len(mifare_params) == 6
        assert len(felica_params) == 18
        assert len(nfcid3t) == 10

        data = (chr(mode) + mifare_params + felica_params + nfcid3t +
                chr(len(general_bytes)) + general_bytes +
                chr(len(historical_bytes)) + historical_bytes)
        return self.command(0x8c, data, timeout)

class Device(pn53x.Device):
    """Device driver for PN532 based contactless frontends."""

    supported_bitrate_type_list = ("106A", "106B", "212F", "424F")
    
    def __init__(self, transport):
        chipset = Chipset(transport, logger=log)
        super(Device, self).__init__(chipset, logger=log)
        
        ic, ver, rev, support = self.chipset.get_firmware_version()
        self._chipset_name = "PN5{0:02x}v{1}.{2}".format(ic, ver, rev)
        log.debug("chipset is a {0}".format(self._chipset_name))

        if self.chipset.read_register(0x6103) & 0b00101111 == 0b00000100:
            # The Multi Interface (MIF) register says we're using HSU.
            log.debug("connected via high speed uart at {0} baud"
                      .format(self.chipset.transport.baudrate))
            self.chipset.set_serial_baudrate(921600)
            time.sleep(0.001)
            self.chipset.transport.baudrate = 921600
            log.debug("changed high speed uart speed to {0} baud"
                      .format(self.chipset.transport.baudrate))

        self.chipset.sam_configuration("normal")
        self.chipset.set_parameters(0b00000000)
        self.chipset.rf_configuration(0x02, "\x00\x0B\x0A")
        self.chipset.rf_configuration(0x04, "\x00")
        self.chipset.rf_configuration(0x05, "\x01\x00\x01")
        
        # The default value of CIU_ModGsP does not work with the Texas
        # Instruments RF430CL330H Type B NFC Interface Transponder. It
        # works when setting ModGsP to 0x10.
        log.debug("write analog settings for type B")
        self.chipset.rf_configuration(0x0C, "\xFF\x10\x85") # ModGsP
        
        self.mute()

    def close(self):
        if self.chipset.read_register(0x6103) & 0b00101111 == 0b00000100:
            # The Multi Interface (MIF) register says we're using HSU.
            self.chipset.set_serial_baudrate(115200)
            time.sleep(0.001)
            self.chipset.transport.baudrate = 115200
        self.chipset.power_down(wakeup_enable=("I2C", "SPI", "HSU"))

    def sense_tta(self, target):
        """Search for a Type A Target.

        The PN532 can discover all kinds of Type A Targets (Type 1
        Tag, Type 2 Tag, and Type 4A Tag) at 106 kbps.

        """
        return self._sense_tta(target)

    def sense_ttb(self, target):
        """Search for a Type B Target.

        The PN532 can discover Type B Targets (Type 4B Tag) at 106
        kbps. For a Type 4B Tag the firmware automatically sends an
        ATTRIB command that configures the use of DID and 64 byte
        maximum frame size. The driver reverts this configuration with
        a DESELECT and WUPB command to return the target prepared for
        activation (which nfcpy does in the tag activation code).

        """
        return self._sense_ttb(target, brty=3, did='\x01')
    
    def sense_ttf(self, target):
        """Search for a Type F Target.

        The PN532 can discover Type F Targets (Type 3 Tag) at 212 and
        424 kbps. The driver uses the default polling command
        ``06FFFF0000`` if no ``target.sens_req`` is supplied.

        """
        return self._sense_ttf(target)

    def sense_dep(self, target, passive_target=None):
        """Search for a DEP Target in active or passive communication mode.

        Active communication mode is used if *passive_target* is
        None. To use passive communication mode the *passive_target*
        must be previously discovered Type A or Type F Target.

        """
        return self._sense_dep(target, passive_target)
        
    def old_sense_dep(self, target):
        br = target.bitrate

        if self.remote_target is not None:
            data = chr(len(target.atr_req)+1) + target.atr_req
            data = '\xF0' + data if br == 106 else data
            try:
                data = self.exchange(data, timeout=1.238)
            except nfc.clf.DigitalError:
                self.mute()
            else:
                log.info("running in {0} kbps passive mode".format(br))
                target.atr_res = data[2:] if br == 106 else data[1:]
                if br == 106 and target.atr_res[16] & 0x30 == 0x30:
                    # PN533 can only send 253 byte payload in 106A
                    target.atr_res[16] = (target.atr_res[16] & 0xCF) | 0x20
                if target.bitrate != self.target.bitrate:
                    log.warning("parameter selection not supported")
                    target.bitrate = self.target.bitrate
                return target
        else:
            gi, nfcid3 = (target.atr_req[16:], target.atr_req[2:12])
            try:
                rsp = self.chipset.in_jump_for_dep('active', br, '', nfcid3, gi)
            except Chipset.Error as error:
                self.mute()
            else:
                log.info("running in {0} kbps active mode".format(br))
                target.atr_res = '\xD5\x01' + rsp
                return target

    def _tt1_send_cmd_recv_rsp(self, data, timeout):
        # Special handling for Tag Type 1 (Jewel/Topaz) card commands.
        
        if data[0] in (0x00, 0x01, 0x1A, 0x53, 0x72):
            # These commands are implemented by the chipset.
            return self.chipset.in_data_exchange(data, timeout)[0]

        if data[0] == 0x10:
            # RSEG implementation does not accept any segment other
            # than 0. Unfortunately we can not directly issue this
            # command to the CIU because the response is 128 byte and
            # we're not fast enough to read it from the 64 byte FIFO.
            rsp = data[1:2]
            for block in range((data[1]>>4)*16, (data[1]>>4)*16+16):
                cmd = "\x02" + chr(block) + data[2:]
                rsp += self._tt1_send_cmd_recv_rsp(cmd, timeout)[1:9]
            return rsp

        # Remaining commands READ8, WRITE-E8, WRITE-NE8 are not
        # implemented by the chipset. Fortunately we can directly
        # program the CIU through register read/write. Each TT1
        # command byte must be send as a separate TTA frame, the first
        # must be a short frame with only 7 data bits and the rest is
        # normal frames. Reading is also a bit complicated because for
        # sending we have to disable the parity generator which means
        # that we will also receive the parity bits, thus 9 bits
        # received per 8 data bits. And because they are already
        # reversed in the FIFO we must swap before parity removal and
        # afterwards (maybe this could be optimized a bit)
        data = self.add_crc_b(data)
        register_write = []
        register_write.append(("CIU_FIFOData",   data[0])) # CMD_CODE
        register_write.append(("CIU_BitFraming",    0x07)) # 7 bits
        register_write.append(("CIU_Command",       0x04)) # Transmit
        register_write.append(("CIU_BitFraming",    0x00)) # 8 bits
        register_write.append(("CIU_ManualRCV",     0x30)) # ParityDisable
        for i in range(1, len(data)):
            register_write.append(("CIU_FIFOData", data[i])) # CMD_DATA
            register_write.append(("CIU_Command",     0x04)) # Transmit
            register_write.append(("CIU_Command",     0x07)) # NoCmdChange
        register_write.append(("CIU_Command",       0x08)) # Receive
        self.chipset.write_register(*register_write)
        if data[0] == 0x54: # WRITE-E8
            time.sleep(0.006) # assuming same response time as WRITE-E
        if data[0] == 0x1B: # WRITE-NE8
            time.sleep(0.003) # assuming same response time as WRITE-NE
        self.chipset.write_register(("CIU_ManualRCV", 0x20)) # enable parity
        fifo_level = self.chipset.read_register("CIU_FIFOLevel")
        if fifo_level == 0: raise nfc.clf.TimeoutError
        data = self.chipset.read_register(*(fifo_level * ["CIU_FIFOData"]))
        data = ''.join(["{:08b}".format(octet)[::-1] for octet in data])
        data = [int(data[i:i+8][::-1], 2) for i in range(0, len(data)-8, 9)]
        if self.check_crc_b(data) is False:
            raise nfc.clf.TransmissionError("crc_b check error")
        return bytearray(data[0:-2])

    def listen_tta(self, target, timeout):
        """Listen as Type A Target is not supported."""
        info = "{device} does not support listen as Type A Target"
        raise NotImplementedError(info.format(device=self))

    def listen_ttb(self, target, timeout):
        """Listen as Type B Target is not supported."""
        info = "{device} does not support listen as Type B Target"
        raise NotImplementedError(info.format(device=self))

    def listen_ttf(self, target, timeout):
        """Listen as Type F Target is not supported."""
        info = "{device} does not support listen as Type F Target"
        raise NotImplementedError(info.format(device=self))

    def listen_dep(self, target, timeout):
        """Listen *timeout* seconds to become initialized as a DEP Target.
        
        The PN532 can be set to listen as a DEP Target for passive and
        active communication mode.

        """
        return self._listen_dep(target, timeout)

    def _init_as_target(self, mode, tta_params, ttf_params, timeout):
        nfcid3t = ttf_params[0:8] + "\x00\x00"
        args = (mode, tta_params, ttf_params, nfcid3t, '', '', timeout)
        return self.chipset.tg_init_as_target(*args)

def init(transport):
    if transport.TYPE == "TTY":
        # wakeup from power down and delay to operational state
        transport.write(bytearray([0x55, 0x00, 0x00, 0x00, 0x00]))

    return Device(transport)
