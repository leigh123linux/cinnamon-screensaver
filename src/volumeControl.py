#!/usr/bin/python3

import gi
gi.require_version('Cvc', '1.0')

from gi.repository import Gtk, Cvc, Gdk

from widgets.volumeSlider import VolumeSlider
from util import trackers, utils

class VolumeControl(Gtk.Box):
    """
    A direct child of the AudioPanel, it provides the volume slider.  This shows
    any time we are Awake, regardless of any media player connections.  We use libcvc
    to interact with the audio subsystem.
    """
    def __init__(self):
        super(VolumeControl, self).__init__(orientation=Gtk.Orientation.HORIZONTAL)

        self.output = None
        self.controller = None

        self.volume_slider = VolumeSlider()
        self.volume_slider.show_all()

        self.set_no_show_all(True)

        self.pack_start(self.volume_slider, False, False, 6)

        self.initialize_sound_controller()

    def initialize_sound_controller(self):
        self.controller = Cvc.MixerControl(name="cinnamon-screensaver")
        trackers.con_tracker_get().connect(self.controller,
                                           "state-changed",
                                           self.on_state_changed)

        trackers.con_tracker_get().connect(self.controller,
                                           "default-sink-changed",
                                           self.on_state_changed)

        self.controller.open()
        self.on_state_changed()

    def on_state_changed(self, controller=None, state=0):
        if controller and controller != self.controller:
            old = self.controller
            self.controller = controller
            del old
        if self.controller.get_state() == Cvc.MixerControlState.READY:
            new = self.controller.get_default_sink()
            if new is not None:
                if self.output and self.output != new:
                    old = self.output
                    self.output = new
                    del old
                else:
                    self.output = new
                trackers.con_tracker_get().connect(self.output,
                                                   "notify::is-muted",
                                                   self.on_volume_changed)
                trackers.con_tracker_get().connect(self.output,
                                                   "notify::volume",
                                                   self.on_volume_changed)
                trackers.con_tracker_get().connect(self.volume_slider,
                                                   "value-changed",
                                                   self.on_volume_slider_changed)
                trackers.con_tracker_get().connect(self.volume_slider,
                                                   "button-press-event",
                                                   self.on_button_press_event)
                if not utils.have_gtk_version("3.18.0"):
                    trackers.con_tracker_get().connect(self.volume_slider,
                                                       "scroll-event",
                                                       self.on_scroll_event)

                self.on_volume_changed(None, None)
                self.show()
                return

        self.hide()

    def on_volume_changed(self, output, pspec):
        vol = self.output.props.volume
        muted = self.output.get_is_muted()
        max_vol = self.controller.get_vol_max_norm()

        normalized_volume = int(min((vol / max_vol * 100), 100))

        self.update_slider(normalized_volume, muted)

    def update_slider(self, volume, muted):

        trackers.con_tracker_get().handler_block(self.volume_slider,
                                                 "value-changed",
                                                 self.on_volume_slider_changed)

        self.volume_slider.set_muted(muted)
        self.volume_slider.set_value(volume)

        trackers.con_tracker_get().handler_unblock(self.volume_slider,
                                                   "value-changed",
                                                   self.on_volume_slider_changed)

    def on_volume_slider_changed(self, range, data=None):
        value = self.volume_slider.get_value()
        max_norm = self.controller.get_vol_max_norm()

        denormalized_volume = utils.CLAMP((value / 100) * max_norm, 0, max_norm)

        trackers.con_tracker_get().handler_block(self.output,
                                                 "notify::volume",
                                                 self.on_volume_changed)
        trackers.con_tracker_get().handler_block(self.output,
                                                 "notify::is-muted",
                                                 self.on_volume_changed)
        self.output.set_volume(denormalized_volume)
        self.output.push_volume()
        self.output.change_is_muted(False)
        trackers.con_tracker_get().handler_unblock(self.output,
                                                   "notify::volume",
                                                   self.on_volume_changed)
        trackers.con_tracker_get().handler_unblock(self.output,
                                                   "notify::is-muted",
                                                   self.on_volume_changed)

    def on_button_press_event(self, widget, event):
        if event.button == 2:
            self.output.set_is_muted(not self.volume_slider.muted)

        return Gdk.EVENT_PROPAGATE

    def on_scroll_event(self, widget, event):
        success, dx, dy = event.get_scroll_deltas()
        step = self.volume_slider.get_adjustment().get_step_increment()

        if dy < 0:
            self.volume_slider.set_value(self.volume_slider.get_value() + step)
        elif dy > 0:
            self.volume_slider.set_value(self.volume_slider.get_value() - step)

        return Gdk.EVENT_STOP
