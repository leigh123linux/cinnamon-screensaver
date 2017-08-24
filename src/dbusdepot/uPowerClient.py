#!/usr/bin/python3

from gi.repository import Gio, GObject, CScreensaver, GLib
from enum import IntEnum

from dbusdepot.baseClient import BaseClient

class DeviceType(IntEnum):
    Unknown = 0
    LinePower = 1
    Battery = 2
    Ups = 3
    Monitor = 4
    Mouse = 5
    Keyboard = 6
    Pda = 7
    Phone = 8

class DeviceState(IntEnum):
    Unknown = 0
    Charging = 1
    Discharging = 2
    Empty = 3
    FullyCharged = 4
    PendingCharge = 5
    PendingDischarge = 6

class UPowerClient(BaseClient):
    """
    This client communicates with the upower provider, tracking the power
    state of the system (laptops - are we on battery or plugged in?)
    """
    __gsignals__ = {
        'power-state-changed': (GObject.SignalFlags.RUN_LAST, None, ()),
        'percentage-changed': (GObject.SignalFlags.RUN_LAST, None, (GObject.Object,))
    }

    UPOWER_SERVICE = "org.freedesktop.UPower"
    UPOWER_PATH    = "/org/freedesktop/UPower"

    def __init__(self):
        super(UPowerClient, self).__init__(Gio.BusType.SYSTEM,
                                           CScreensaver.UPowerProxy,
                                           self.UPOWER_SERVICE,
                                           self.UPOWER_PATH)

        self.have_battery = False
        self.plugged_in = False

        self.update_state_id = 0
        self.devices_dirty = True

        self.relevant_devices = []

    def on_client_setup_complete(self):
        self.proxy.connect("device-removed", self.on_device_added_or_removed)
        self.proxy.connect("device-added", self.on_device_added_or_removed)
        self.proxy.connect("notify::on-battery", self.on_battery_changed)

        self.queue_update_state()

    def on_device_added_or_removed(self, proxy, path):
        self.devices_dirty = True
        self.queue_update_state()

    def on_battery_changed(self, proxy, pspec, data=None):
        self.queue_update_state()

    def queue_update_state(self):
        if self.update_state_id > 0:
            GObject.source_remove(self.update_state_id)
            self.update_state_id = 0

        GObject.idle_add(self.idle_update_cb)

    def idle_update_cb(self, data=None):
        if self.devices_dirty:
            self.rescan_devices()

        self.devices_dirty = False

        if self.update_state():
            self.emit_changed()

    def rescan_devices(self):
        if len(self.relevant_devices) > 0:
            for path, dev in self.relevant_devices:
                dev.disconnect(dev.prop_changed_id)
                del dev
                del path

        self.relevant_devices = []

        try:
            # The return type for this call has to be overridden in gdbus-codegen
            # (See the Makefile.am) - or else we get utf-8 errors (python3 issue?)
            for path in self.proxy.call_enumerate_devices_sync():
                try:
                    dev = CScreensaver.UPowerDeviceProxy.new_for_bus_sync(Gio.BusType.SYSTEM,
                                                                          Gio.DBusProxyFlags.NONE,
                                                                          self.UPOWER_SERVICE,
                                                                          path,
                                                                          None)

                    if dev.get_property("type") in (DeviceType.Battery, DeviceType.LinePower):
                        self.relevant_devices.append((path, dev))
                        dev.prop_changed_id = dev.connect("notify", self.on_device_properties_changed)
                except GLib.Error:
                    print("UPowerClient had trouble connecting with device:", path, " - skipping it")
        except GLib.Error:
            print("UPowerClient had trouble enumerating through devices.  The battery indicator will be disabled")

        self.queue_update_state()

    def update_state(self):
        changes = False

        old_plugged_in = self.plugged_in
        old_have_battery = self.have_battery

        # UPower doesn't necessarily have a LinePower device if there are no batteries.
        # Default to plugged in, then.
        new_plugged_in = True
        new_have_battery = False

        for path, dev in self.relevant_devices:
            if dev.get_property("type") == DeviceType.LinePower:
                new_plugged_in = dev.get_property("online")
            if dev.get_property("type") == DeviceType.Battery:
                new_have_battery = True

        if (new_plugged_in != old_plugged_in) or (new_have_battery != old_have_battery):
            changes = True
            self.have_battery = new_have_battery
            self.plugged_in = new_plugged_in

        return changes

    def on_device_properties_changed(self, proxy, pspec, data=None):
        if pspec.name in ("online", "icon-name", "state"):
            self.queue_update_state()

        if pspec.name == "percentage":
            self.emit_percentage_changed(proxy)

    def emit_changed(self):
        self.emit("power-state-changed")

    def emit_percentage_changed(self, battery):
        self.emit("percentage-changed", battery)

    def get_batteries(self):
        if len(self.relevant_devices) == 0:
            return []

        ret = []

        for path, dev in self.relevant_devices:
            if dev.get_property("type") == DeviceType.Battery:
                ret.append((path, dev))

        return ret

    def full_and_on_ac_or_no_batteries(self):
        """
        This figures out whether the power widget should be shown or not -
        currently we only show the widget if we have batteries and are not
        plugged in.
        """
        batteries = self.get_batteries()

        if batteries == []:
            return True

        all_batteries_full = True

        for path, dev in batteries:
            if dev.get_property("state") not in (DeviceState.FullyCharged, DeviceState.Unknown):
                all_batteries_full = False
                break

        return self.plugged_in and all_batteries_full

    def on_failure(self, *args):
        print("Failed to establish a connection with UPower - the battery indicator will be disabled.")
