"""Extension to Qahirah to adapt its generic XCB support to work specifically
with the xcffib binding.
"""
#+
# Copyright 2017, 2022 Lawrence D'Oliveiro <ldo@geek-central.gen.nz>.
# Licensed under the GNU Lesser General Public License v2.1 or later.
#-

# Useful XCB docs:
# <https://xcb.freedesktop.org/manual/modules.html>
# <https://xcb.freedesktop.org/PublicApi/>
# <https://www.x.org/releases/X11R7.5/doc/libxcb/tutorial/index.html>
# (linked from <https://www.x.org/releases/X11R7.5/doc/>)

import enum
from weakref import \
    ref as weak_ref, \
    WeakValueDictionary
import asyncio
import atexit
import qahirah
import cffi
import xcffib
from xcffib import \
    xproto, \
    render as xrender

#+
# Useful stuff
#-

if hasattr(asyncio, "get_running_loop") :
    # new in Python 3.7
    get_running_loop = asyncio.get_running_loop
else :
    # as long as I want to support pre-3.7...
    get_running_loop = asyncio.get_event_loop
#end if

def get_event_loop() :
    "Python docs indicate that asyncio.get_event_loop() is going away" \
    " in its current form. But I still need to be able to attach objects" \
    " to the default event loop from a non-coroutine context. So I" \
    " reimplement its original semantics here."
    return \
        asyncio.get_event_loop_policy().get_event_loop()
#end get_event_loop

assert qahirah.HAS.XCB_SURFACE, "Cairo is missing XCB support"

_ffi = cffi.FFI()
_ffi_size_t = _ffi.typeof("size_t")

def _get_conn(connection) :
    "gets the raw xcb_connection_t address from the xcffib.Connection object." \
    " Will this continue to work reliably in future? Who knows..."
    if not hasattr(connection, "_conn") :
        raise TypeError("connection does not have a _conn attribute")
    #end if
    return \
        int(_ffi.cast(_ffi_size_t, connection._conn))
#end _get_conn

KEYCODE_MIN = 8
KEYCODE_MAX = 255

class XK :
    "some useful keysyms, extracted from /usr/include/X11/keysymdef.h."

    VoidSymbol = 0xffffff

    BackSpace = 0xff08
    Tab = 0xff09
    Linefeed = 0xff0a
    Clear = 0xff0b
    Return = 0xff0d
    Pause = 0xff13
    Scroll_Lock = 0xff14
    Sys_Req = 0xff15
    Escape = 0xff1b
    Delete = 0xffff

    Multi_key = 0xff20
    Codeinput = 0xff37
    SingleCandidate = 0xff3c
    MultipleCandidate = 0xff3d
    PreviousCandidate = 0xff3e

    Home = 0xff50
    Left = 0xff51
    Up = 0xff52
    Right = 0xff53
    Down = 0xff54
    Prior = Page_Up = 0xff55
    Next = Page_Down = 0xff56
    End = 0xff57
    Begin = 0xff58

    Select = 0xff60
    Print = 0xff61
    Execute = 0xff62
    Insert = 0xff63
    Undo = 0xff65
    Redo = 0xff66
    Menu = 0xff67
    Find = 0xff68
    Cancel = 0xff69
    Help = 0xff6a
    Break = 0xff6b
    Mode_switch = script_switch = 0xff7e
    Num_Lock = 0xff7f

    KP_Space = 0xff80
    KP_Tab = 0xff89
    KP_Enter = 0xff8d
    KP_F1 = 0xff91
    KP_F2 = 0xff92
    KP_F3 = 0xff93
    KP_F4 = 0xff94
    KP_Home = 0xff95
    KP_Left = 0xff96
    KP_Up = 0xff97
    KP_Right = 0xff98
    KP_Down = 0xff99
    KP_Prior = KP_Page_Up = 0xff9a
    KP_Next = KP_Page_Down = 0xff9b
    KP_End = 0xff9c
    KP_Begin = 0xff9d
    KP_Insert = 0xff9e
    KP_Delete = 0xff9f
    KP_Equal = 0xffbd
    KP_Multiply = 0xffaa
    KP_Add = 0xffab
    KP_Separator = 0xffac
    KP_Subtract = 0xffad
    KP_Decimal = 0xffae
    KP_Divide = 0xffaf

    KP_0 = 0xffb0
    KP_1 = 0xffb1
    KP_2 = 0xffb2
    KP_3 = 0xffb3
    KP_4 = 0xffb4
    KP_5 = 0xffb5
    KP_6 = 0xffb6
    KP_7 = 0xffb7
    KP_8 = 0xffb8
    KP_9 = 0xffb9

    F1 = 0xffbe
    F2 = 0xffbf
    F3 = 0xffc0
    F4 = 0xffc1
    F5 = 0xffc2
    F6 = 0xffc3
    F7 = 0xffc4
    F8 = 0xffc5
    F9 = 0xffc6
    F10 = 0xffc7
    F11 = L1 = 0xffc8
    F12 = L2 = 0xffc9
    F13 = L3 = 0xffca
    F14 = L4 = 0xffcb
    F15 = L5 = 0xffcc
    F16 = L6 = 0xffcd
    F17 = L7 = 0xffce
    F18 = L8 = 0xffcf
    F19 = L9 = 0xffd0
    F20 = L10 = 0xffd1
    F21 = R1 = 0xffd2
    F22 = R2 = 0xffd3
    F23 = R3 = 0xffd4
    F24 = R4 = 0xffd5
    F25 = R5 = 0xffd6
    F26 = R6 = 0xffd7
    F27 = R7 = 0xffd8
    F28 = R8 = 0xffd9
    F29 = R9 = 0xffda
    F30 = R10 = 0xffdb
    F31 = R11 = 0xffdc
    F32 = R12 = 0xffdd
    F33 = R13 = 0xffde
    F34 = R14 = 0xffdf
    F35 = R15 = 0xffe0

    Shift_L = 0xffe1
    Shift_R = 0xffe2
    Control_L = 0xffe3
    Control_R = 0xffe4
    Caps_Lock = 0xffe5
    Shift_Lock = 0xffe6

    Meta_L = 0xffe7
    Meta_R = 0xffe8
    Alt_L = 0xffe9
    Alt_R = 0xffea
    Super_L = 0xffeb
    Super_R = 0xffec
    Hyper_L = 0xffed
    Hyper_R = 0xffee

    ISO_Lock = 0xfe01
    ISO_Level2_Latch = 0xfe02
    ISO_Level3_Shift = 0xfe03
    ISO_Level3_Latch = 0xfe04
    ISO_Level3_Lock = 0xfe05
    ISO_Level5_Shift = 0xfe11
    ISO_Level5_Latch = 0xfe12
    ISO_Level5_Lock = 0xfe13
    ISO_Group_Shift = 0xff7e
    ISO_Group_Latch = 0xfe06
    ISO_Group_Lock = 0xfe07
    ISO_Next_Group = 0xfe08
    ISO_Next_Group_Lock = 0xfe09
    ISO_Prev_Group = 0xfe0a
    ISO_Prev_Group_Lock = 0xfe0b
    ISO_First_Group = 0xfe0c
    ISO_First_Group_Lock = 0xfe0d
    ISO_Last_Group = 0xfe0e
    ISO_Last_Group_Lock = 0xfe0f

    ISO_Left_Tab = 0xfe20
    ISO_Move_Line_Up = 0xfe21
    ISO_Move_Line_Down = 0xfe22
    ISO_Partial_Line_Up = 0xfe23
    ISO_Partial_Line_Down = 0xfe24
    ISO_Partial_Space_Left = 0xfe25
    ISO_Partial_Space_Right = 0xfe26
    ISO_Set_Margin_Left = 0xfe27
    ISO_Set_Margin_Right = 0xfe28
    ISO_Release_Margin_Left = 0xfe29
    ISO_Release_Margin_Right = 0xfe2a
    ISO_Release_Both_Margins = 0xfe2b
    ISO_Fast_Cursor_Left = 0xfe2c
    ISO_Fast_Cursor_Right = 0xfe2d
    ISO_Fast_Cursor_Up = 0xfe2e
    ISO_Fast_Cursor_Down = 0xfe2f
    ISO_Continuous_Underline = 0xfe30
    ISO_Discontinuous_Underline = 0xfe31
    ISO_Emphasize = 0xfe32
    ISO_Center_Object = 0xfe33
    ISO_Enter = 0xfe34

    dead_grave = 0xfe50
    dead_acute = 0xfe51
    dead_circumflex = 0xfe52
    dead_tilde = 0xfe53
    dead_perispomeni = 0xfe53
    dead_macron = 0xfe54
    dead_breve = 0xfe55
    dead_abovedot = 0xfe56
    dead_diaeresis = 0xfe57
    dead_abovering = 0xfe58
    dead_doubleacute = 0xfe59
    dead_caron = 0xfe5a
    dead_cedilla = 0xfe5b
    dead_ogonek = 0xfe5c
    dead_iota = 0xfe5d
    dead_voiced_sound = 0xfe5e
    dead_semivoiced_sound = 0xfe5f
    dead_belowdot = 0xfe60
    dead_hook = 0xfe61
    dead_horn = 0xfe62
    dead_stroke = 0xfe63
    dead_abovecomma = dead_psili = 0xfe64
    dead_abovereversedcomma = dead_dasia = 0xfe65
    dead_doublegrave = 0xfe66
    dead_belowring = 0xfe67
    dead_belowmacron = 0xfe68
    dead_belowcircumflex = 0xfe69
    dead_belowtilde = 0xfe6a
    dead_belowbreve = 0xfe6b
    dead_belowdiaeresis = 0xfe6c
    dead_invertedbreve = 0xfe6d
    dead_belowcomma = 0xfe6e
    dead_currency = 0xfe6f

    dead_lowline = 0xfe90
    dead_aboveverticalline = 0xfe91
    dead_belowverticalline = 0xfe92
    dead_longsolidusoverlay = 0xfe93

    dead_a = 0xfe80
    dead_A = 0xfe81
    dead_e = 0xfe82
    dead_E = 0xfe83
    dead_i = 0xfe84
    dead_I = 0xfe85
    dead_o = 0xfe86
    dead_O = 0xfe87
    dead_u = 0xfe88
    dead_U = 0xfe89
    dead_small_schwa = 0xfe8a
    dead_capital_schwa = 0xfe8b

    dead_greek = 0xfe8c

    First_Virtual_Screen = 0xfed0
    Prev_Virtual_Screen = 0xfed1
    Next_Virtual_Screen = 0xfed2
    Last_Virtual_Screen = 0xfed4
    Terminate_Server = 0xfed5

    AccessX_Enable = 0xfe70
    AccessX_Feedback_Enable = 0xfe71
    RepeatKeys_Enable = 0xfe72
    SlowKeys_Enable = 0xfe73
    BounceKeys_Enable = 0xfe74
    StickyKeys_Enable = 0xfe75
    MouseKeys_Enable = 0xfe76
    MouseKeys_Accel_Enable = 0xfe77
    Overlay1_Enable = 0xfe78
    Overlay2_Enable = 0xfe79
    AudibleBell_Enable = 0xfe7a

    Pointer_Left = 0xfee0
    Pointer_Right = 0xfee1
    Pointer_Up = 0xfee2
    Pointer_Down = 0xfee3
    Pointer_UpLeft = 0xfee4
    Pointer_UpRight = 0xfee5
    Pointer_DownLeft = 0xfee6
    Pointer_DownRight = 0xfee7
    Pointer_Button_Dflt = 0xfee8
    Pointer_Button1 = 0xfee9
    Pointer_Button2 = 0xfeea
    Pointer_Button3 = 0xfeeb
    Pointer_Button4 = 0xfeec
    Pointer_Button5 = 0xfeed
    Pointer_DblClick_Dflt = 0xfeee
    Pointer_DblClick1 = 0xfeef
    Pointer_DblClick2 = 0xfef0
    Pointer_DblClick3 = 0xfef1
    Pointer_DblClick4 = 0xfef2
    Pointer_DblClick5 = 0xfef3
    Pointer_Drag_Dflt = 0xfef4
    Pointer_Drag1 = 0xfef5
    Pointer_Drag2 = 0xfef6
    Pointer_Drag3 = 0xfef7
    Pointer_Drag4 = 0xfef8
    Pointer_Drag5 = 0xfefd

    Pointer_EnableKeys = 0xfef9
    Pointer_Accelerate = 0xfefa
    Pointer_DfltBtnNext = 0xfefb
    Pointer_DfltBtnPrev = 0xfefc

    ch = 0xfea0
    Ch = 0xfea1
    CH = 0xfea2
    c_h = 0xfea3
    C_h = 0xfea4
    C_H = 0xfea5

#end XK

KEYSYM_NAME = dict \
  ( # keysym value to name
    (getattr(XK, n), n)
    for n in dir(XK)
    if not n.startswith("_")
  )

KEYSYM_KEYPAD = frozenset \
  (
    getattr(XK, n)
    for n in dir(XK)
    if n.startswith("KP_")
  )

class STATE(enum.IntEnum) :
    "modifier bits."
    SHIFT = 0
    LOCK = 1
    CTRL = 2
    MOD1 = 3 # PC keyboards: Alt or Meta
    MOD2 = 4 # PC keyboards: Num Lock
    MOD3 = 5
    MOD4 = 6 # Super (PC keyboards: logo key)
    MOD5 = 7
    BUTTON1 = 8
    BUTTON2 = 9
    BUTTON3 = 10
    BUTTON4 = 11
    BUTTON5 = 12

    @property
    def mask(self) :
        return 1 << self.value
    #end mask

#end STATE

#+
# Needed Cairo interface types
#-

def def_xcffib_subclass(base_class, xcffib_name, substructs = None) :
    # defines a subclass of base_class that adds an ensure_struct
    # method for converting from the xcffib wrapper objects.

    name = base_class.__name__

    class result_class(base_class) :

        def ensure_struct(celf, s) :
            if not isinstance(s, base_class) :
                fields = dict \
                  (
                    (name, getattr(s, name))
                    for name, cttype in celf._ctstruct._fields_
                    if celf._ignore == None or name not in celf._ignore
                  )
                if substructs != None :
                    for field_name, field_type in substructs.items() :
                        fields[field_name] = field_type.ensure_struct(fields[field_name])
                    #end for
                #end if
                s = celf(**fields)
            #end if
            return \
                s
        #end ensure_struct
        ensure_struct.__doc__ = \
            (
                    "accepts either a %s xcffib object or one of this %s class;"
                    " converts the former to the latter, and returns the latter unchanged."
                %
                    (xcffib_name, name)
            )
          # interesting that this can’t be assigned after class definition has finished,
          # and that setting it is ignored after applying classmethod decorator.
        ensure_struct = classmethod(ensure_struct)

    #end result_class

#begin def_xcffib_subclass
    result_class.__name__ = name
    result_class.__doc__ = \
        (
                "Subclass of qahirah.%s which adds the ensure_struct classmethod to"
                " decode the xcffib representation."
            %
                name
        )
    return \
        result_class
#end def_xcffib_subclass

XCBVisualType = def_xcffib_subclass \
  (
    base_class = qahirah.XCBVisualType,
    xcffib_name = "VISUALTYPE"
  )
XCBRenderDirectFormat = def_xcffib_subclass \
  (
    base_class = qahirah.XCBRenderDirectFormat,
    xcffib_name = "DIRECTFORMAT"
  )
XCBScreen = def_xcffib_subclass \
  (
    base_class = qahirah.XCBScreen,
    xcffib_name = "SCREEN"
  )
XCBRenderPictFormInfo = def_xcffib_subclass \
  (
    base_class = qahirah.XCBRenderPictFormInfo,
    xcffib_name = "PICTFORMINFO",
    substructs = {"direct" : XCBRenderDirectFormat}
  )

del def_xcffib_subclass # my work is done

class XCBSurface(qahirah.XCBSurface) :
    "overrides qahirah.XCBSurface with create methods that take xcffib.Connection" \
    " objects to represent the XCB connections."

    __slots__ = () # to forestall typos

    @classmethod
    def create(celf, connection, drawable, visual, width, height) :
        conn = _get_conn(connection)
        visual = XCBVisualType.ensure_struct(visual)
        return \
            super().create \
              (
                connection = conn,
                drawable = drawable,
                visual = visual,
                width = width,
                height = height
              )
    #end create

    @classmethod
    def create_for_bitmap(celf, connection, screen, bitmap, width, height) :
        conn = _get_conn(connection)
        screen = XCBScreen.ensure_struct(screen)
        return \
            super().create_for_bitmap \
              (
                connection = conn,
                screen = screen,
                bitmap = bitmap,
                width = width,
                height = height
              )
    #end create_for_bitmap

    @classmethod
    def create_with_xrender_format(celf, connection, screen, drawable, format, width, height) :
        conn = _get_conn(connection)
        screen = XCBScreen.ensure_struct(screen)
        format = XCBRenderPictFormInfo.ensure_struct(format)
        return \
            super().create_with_xrender_format \
              (
                connection = conn,
                screen = screen,
                drawable = drawable,
                format = format,
                width = width,
                height = height
              )
    #end create_with_xrender_format

    def flush(self) :
        super().flush() # docs say to do this ...
        xcffib.lib.xcb_flush(xcffib.ffi.cast("xcb_connection_t *", self.device.xcb_connection))
          # ... though this is what really seems to be essential
    #end flush

#end XCBSurface

#+
# Main classes
#-

class CW_BIT(enum.IntEnum) :
    "bit numbers corresponding to bit masks for window attributes to" \
    " create_window calls."
    # Note: must be specified in strictly increasing order
    BACKPIXMAP = 0
    BACKPIXEL = 1
    BORDERPIXMAP = 2
    BORDERPIXEL = 3
    BITGRAVITY = 4
    WINGRAVITY = 5
    BACKINGSTORE = 6
    BACKINGPLANES = 7
    BACKINGPIXEL = 8
    OVERRIDEREDIRECT = 9
    SAVEUNDER = 10
    EVENTMASK = 11
    DONTPROPAGATE = 12
    COLOURMAP = 13
    CURSOR = 14

    @property
    def mask(self) :
        return 1 << self.value
    #end mask

#end CW_BIT
CW_BIT.COLORMAP = CW_BIT.COLOURMAP # if you prefer

class ConnWrapper :

    __slots__ = \
        (
            "__weakref__",
            "conn",
            "loop",
            "user_data",
            "_conn_fd",
            "_event_filters",
            "_reply_queue",
            "last_sequence",
        ) # to forestall typos

    sequence_jump = 1 << 30
      # hopefully sequence numbers should never jump by this much at once

    def __init__(self, conn, loop = None) :
        _get_conn(conn) # just a sanity check
        if loop == None :
            loop = get_event_loop()
        #end if
        self.conn = conn
        self.loop = loop
        self.user_data = qahirah.UserDataDict()
        self._conn_fd = conn.get_file_descriptor()
          # keep my own copy because conn.get_file_descriptor()
          # could return an error later
        self._event_filters = []
        self._reply_queue = []
          # wait queue for replies to requests
          # within limitations of xcffib, namely:
          #   * I can block waiting for an event, or I can poll, but
          #   * I can only block waiting for a reply to a request
          #     (xcffib doesn’t provide a wrapper for xcb_poll_for_reply).
        self.last_sequence = None
    #end __init__

    @classmethod
    def open(celf, loop = None) :
        "opens an xcffib.Connection and returns a ConnWrapper for it."
        conn = xcffib.Connection()
        return \
            celf(conn, loop)
    #end open

    def close(self) :
        if self.conn != None :
            self.conn.disconnect()
            self._conn_fd = None
            self.conn = None
        #end if
    #end close

    @staticmethod
    def _handle_conn_readable(w_self) :
        # common fd-readable callback for monitoring server connection
        # for input.
        self = w_self()
        assert self != None, "parent ConnWrapper has gone away"

        had_event = False
        if len(self._event_filters) != 0 :
            try :
                event = self.conn.poll_for_event()
            except xcffib.XcffibException :
                event = None
            #end try
            had_event = event != None
            if had_event :
                event_filters = self._event_filters[:]
                  # copy in case actions make changes
                while True :
                    try :
                        action, arg = event_filters.pop(0)
                    except IndexError :
                        break
                    #end try
                    action(event, arg)
                #end while
            else :
                if self.conn.has_error() :
                    # raise RuntimeError("error on XCB connection")
                    had_event = True # don’t bother looking for request replies
                #end if
            #end if
        #end if

        if not had_event and len(self._reply_queue) != 0 :
            action, arg = self._reply_queue.pop(0)
            action(self, arg)
        #end if

        # always remove, then add back again if needed, to avoid
        # oddities with endless spurious calls
        self.loop.remove_reader(self._conn_fd)
        conn_err = None
        try :
            self.conn.get_file_descriptor()
              # just to check connection is still OK
        except xcffib.ConnectionException as err :
            conn_err = err
            self._conn_fd = None
        #end try
        if self._conn_fd != None :
            if len(self._event_filters) + len(self._reply_queue) != 0 :
                self.loop.add_reader(self._conn_fd, self._handle_conn_readable, w_self)
            #end if
        else :
            assert conn_err != None
            for action, arg in self._event_filters[:] :
              # copy in case actions make changes
                action(conn_err, arg)
            #end for
        #end if
    #end _handle_conn_readable

    def add_event_filter(self, action, arg) :
        "installs a filter which gets to see all incoming events. It is invoked" \
        " as “action(event, arg)“ where the meaning of arg is up to you."
        if (
            any
              (
                elt == (action, arg)
                for i in range(len(self._event_filters))
                for elt in (self._event_filters[i],)
              )
        ) :
            raise KeyError("attempt to install duplicate action+arg")
        #end if
        newelt = (action, arg)
        if len(self._event_filters) + len(self._reply_queue) == 0 :
            print("add_event_filter: add_reader") # debug
            self.loop.add_reader \
              (
                self._conn_fd,
                self._handle_conn_readable,
                weak_ref(self)
              )
        #end if
        self._event_filters.append(newelt)
    #end add_event_filter

    def remove_event_filter(self, action, arg, optional : bool) :
        "removes a previously-installed event filter. optional indicates" \
        " not to report an error if no such filter is installed."
        pos = list \
          (
            i
            for i in range(len(self._event_filters))
            for elt in (self._event_filters[i],)
            if elt == (action, arg)
          )
        assert len(pos) <= 1
        if len(pos) == 1 :
            self._event_filters.pop(pos[0])
            if self._conn_fd != None and len(self._event_filters) + len(self._reply_queue) == 0 :
                self.loop.remove_reader(self._conn_fd)
            #end if
        elif not optional :
            raise KeyError("specified action+arg was not installed as an event filter")
        #end if
    #end remove_event_filter

    def wait_for_event(self) :
        "returns a Future that can be awaited to obtain the next input event." \
        " Note that, once an event is received, it is delivered to all pending" \
        " waiters."

        w_self = weak_ref(self)
        result = self.loop.create_future()

        def event_ready_action(event, result) :
            self = w_self()
            assert self != None, "parent ConnWrapper has gone away"
            self.remove_event_filter(event_ready_action, result, optional = False)
            if isinstance(event, Exception) :
                result.set_exception(event)
            elif isinstance(event, xcffib.Event) :
                result.set_result(event)
            else :
                raise TypeError("unexpected type of event object %s" % repr(event))
            #end if
        #end event_ready_action

    #begin wait_for_event
        self.add_event_filter(event_ready_action, result)
        return result
    #end wait_for_event

    def wait_for_reply(self, request_cookie) :
        "returns a Future that can be awaited to return the response from" \
        " an async request. In xcffib, these request calls return (some" \
        " subclass of) the “Cookie” type, which you pass here as the" \
        " request_cookie. This gets filled in with the reply to the request."

        if not isinstance(request_cookie, xcffib.Cookie) :
            raise TypeError("request_cookie is not a Cookie")
        #end if

        result = self.loop.create_future()

        def reply_ready_action(self, result) :
            # makes the synchronous xcffib call to retrieve the reply
            # from the request cookie. This shouldn’t actually block,
            # provided the reply is already available.
            reply = request_cookie.reply()
            has_error = self.conn.has_error()
            if has_error :
                result.set_exception(RuntimeError("error on XCB connection"))
            else :
                result.set_result(reply)
            #end if
        #end reply_ready_action

    #begin wait_for_reply
        last_sequence = self.last_sequence
        incr_sequence = \
            (
                last_sequence == None
            or
                request_cookie.sequence > last_sequence
            or
                request_cookie.sequence + self.sequence_jump < last_sequence
                  # assumed wraparound
            )
        if incr_sequence :
            self.last_sequence = request_cookie.sequence
        #end if
        if isinstance(request_cookie, xcffib.VoidCookie) :
            result.set_result(None)
        elif not incr_sequence :
            # reply should already be available
            reply_ready_action(self, result)
        else :
            newelt = (reply_ready_action, result)
            if len(self._event_filters) + len(self._reply_queue) == 0 :
                print("wait_for_reply: add_reader") # debug
                self.loop.add_reader \
                  (
                    self._conn_fd,
                    self._handle_conn_readable,
                    weak_ref(self)
                  )
            #end if
            self._reply_queue.append(newelt)
        #end if
        return result
    #end wait_for_reply

    def _easy_create_window(self, bounds : qahirah.Rect, border_width : int, set_attrs) :
        # common code for both easy_create_window and easy_create_window_async.
        if (
                not isinstance(set_attrs, (tuple, list))
            or
                not all
                  (
                        len(i) == 2
                    and
                        isinstance(i[0], CW_BIT)
                    and
                        isinstance(i[1], int)
                    for i in set_attrs
                  )
        ) :
            raise TypeError("set_attrs is not sequence of (CW_BIT.xxx, value) pairs")
        #end if
        default_screen = self.conn.get_screen_pointers()[0]
        use_root = self.conn.get_setup().roots[0]
        window = self.conn.generate_id()
        value_mask = 0
        value_list = []
        default_set_attrs = \
            ( # defaults if not specified by user
                (CW_BIT.BACKPIXEL, use_root.white_pixel),
                (CW_BIT.BORDERPIXEL, use_root.black_pixel),
            )
        user_specified = set(i[0] for i in set_attrs)
        set_attrs = \
            (
                tuple(set_attrs)
            +
                tuple(i for i in default_set_attrs if i[0] not in user_specified)
            )
        for bit_nr, value in sorted(set_attrs, key = lambda x : x[0]) :
            value_mask |= bit_nr.mask
            value_list.append(value)
        #end for
        res = self.conn.core.CreateWindow \
          (
            depth = xcffib.XCB_COPY_FROM_PARENT,
            wid = window,
            parent = default_screen.root,
            x = bounds.left,
            y = bounds.top,
            width = bounds.width,
            height = bounds.height,
            border_width = border_width,
            _class = xcffib.XCB_COPY_FROM_PARENT,
            visual = use_root.root_visual, # xcffib.XCB_COPY_FROM_PARENT,
            value_mask = value_mask,
            value_list = value_list
          )
        return \
            window, res
    #end _easy_create_window

    def easy_create_window(self, bounds : qahirah.Rect, border_width : int, set_attrs) :
        "convenience wrapper which handles a lot of the seeming repetitive tasks" \
        " associated with window creation. set_attrs is a sequence of" \
        " («bit_nr», «value») pairs where each bit_nr is a member of the CW_BIT" \
        " enumeration identifying a window attribute, and «value» is the" \
        " corresponding integer value to set for that attribute. Attributes may" \
        " be specified in any order."
        window, res = self._easy_create_window(bounds, border_width, set_attrs)
        self.conn.request_check(res.sequence)
        return \
            window
    #end easy_create_window

    async def easy_create_window_async(self, bounds : qahirah.Rect, border_width : int, set_attrs) :
        "async version of easy_create_window convenience wrapper."
        window, res = self._easy_create_window(bounds, border_width, set_attrs)
        await self.wait_for_reply(res)
        return \
            window
    #end easy_create_window_async

    def easy_create_surface(self, window, use_xrender : bool) :
        "convenience routine which creates an XCBSurface for drawing" \
        " with Cairo into the specified window, with the option of" \
        " using xrender.\n" \
        "\n" \
        "Note that the surface is initially created with dummy dimensions;" \
        " these will need to be fixed up with a set_size() call when you" \
        " receive a ConfigureNotifyEvent for the window."
        default_screen = self.conn.get_screen_pointers()[0]
        use_root = self.conn.get_setup().roots[0]
        if use_xrender :
            conn_xrender = self.conn(xrender.key)
            res = conn_xrender.QueryPictFormats()
            reply = res.reply() # could offer async alternative here
            use_pictformats = list \
              (
                info
                for info in reply.formats
                if
                        info.type == qahirah.XCB.RENDER_PICT_TYPE_DIRECT
                    and
                        info.depth == 24 # 32 doesn’t seem to work with Cairo
                    and
                        info.direct.red_shift == 16
                    and
                        info.direct.green_shift == 8
                    and
                        info.direct.blue_shift == 0
              )
            assert len(use_pictformats) > 0, "no suitable pictformats found"
            surface = XCBSurface.create_with_xrender_format \
              (
                connection = self.conn,
                screen = default_screen,
                drawable = window,
                format = use_pictformats[0],
                width = 10, # correct these on ConfigureNotifyEvent
                height = 10
              )
        else :
            use_visuals = list \
              (
                vis
                for depth in use_root.allowed_depths
                for vis in depth.visuals
                if vis.visual_id == use_root.root_visual
              )
            assert len(use_visuals) > 0, "no suitable visuals found"
            surface = XCBSurface.create \
              (
                connection = self.conn,
                drawable = window,
                visual = use_visuals[0],
                width = 10, # correct these on ConfigureNotifyEvent
                height = 10
              )
        #end if
        return \
            surface
    #end easy_create_surface

#end ConnWrapper

class AtomCache :
    "two-way mapping between atom IDs and corresponding name strings, with" \
    " caching to reduce communication with X server."

    __slots__ = \
        (
            "__weakref__",
            "conn",
            "name_to_atom",
            "atom_to_name",
            "_lookup_process",
            "_lookup_queue",
            "_name_lookup_pending",
            "_atom_lookup_pending",
        ) # to forestall typos

    def __init__(self, conn) :
        if not isinstance(conn, ConnWrapper) :
            raise TypeError("conn must be a ConnWrapper")
        #end if
        self.conn = conn
        self.name_to_atom = {}
        self.atom_to_name = {}
        self._lookup_process = None
        self._lookup_queue = []
        self._name_lookup_pending = {}
        self._atom_lookup_pending = {}
    #end __init__

    def __repr__(self) :
        return \
            "(%s)" % ", ".join \
              (
                "(%s, %d)" % (repr(k), self.name_to_atom[k])
                for k in self.name_to_atom
              )
    #end __repr__

    @staticmethod
    async def _process_queue(w_self) :
        self = w_self()
        assert self != None, "parent ConnWrapper has gone away"
        print("AtomCache._process_queue starting up") # debug
        while True :
            try :
                entry = self._lookup_queue.pop(0)
            except IndexError :
                break
            #end try
            print("AtomCache._process_queue awaiting %s" % repr(entry)) # debug
            await entry
            print("AtomCache._process_queue entry %s done" % repr(entry)) # debug
        #end while
        print("AtomCache._process_queue shutting down") # debug
        self._lookup_process = None
        # and terminate
    #end _process_queue

    def intern_atom(self, name, create_if = True) :
        "maps a name string to an atom ID, creating a new mapping unless" \
        " not create_if. Returns None if there is no such mapping."
        if isinstance(name, str) :
            name = name.encode()
        elif not isinstance(name, (bytes, bytearray)) :
            raise TypeError("name must be str or bytes")
        #end if
        if name in self.name_to_atom :
            result = self.name_to_atom[name]
        else :
            res = self.conn.conn.core.InternAtom \
              (
                only_if_exists = not create_if,
                name_len = len(name),
                name = name
              )
            result = res.reply().atom
            if result != 0 :
                self.name_to_atom[name] = result
                self.atom_to_name[result] = name
            else :
                result = None
            #end if
        #end if
        return \
            result
    #end intern_atom

    async def intern_atom_async(self, name, create_if = True) :
        "maps a name string to an atom ID, creating a new mapping unless" \
        " not create_if. Returns None if there is no such mapping."
        if isinstance(name, str) :
            name = name.encode()
        elif not isinstance(name, (bytes, bytearray)) :
            raise TypeError("name must be str or bytes")
        #end if
        if name in self.name_to_atom :
            result = self.name_to_atom[name]
            print("intern_atom_async found in %s in cache => %d" % (repr(name), result)) # debug
        elif name in self._name_lookup_pending :
            print("intern_atom_async lookup for %s already in progress" % repr(name)) # debug
            result = await self._name_lookup_pending[name]
        else :
            async def do_lookup(w_self, lookup_done) :
                self = w_self()
                assert self != None, "parent ConnWrapper has gone away"
                print("intern_atom_async: about to lookup %s" % repr(name)) # debug
                res = self.conn.conn.core.InternAtom \
                  (
                    only_if_exists = not create_if,
                    name_len = len(name),
                    name = name
                  )
                self.conn.conn.flush()
                reply = await self.conn.wait_for_reply(res)
                result = reply.atom
                print("intern_atom_async: looked up %s, got %d" % (repr(name), result)) # debug
                if result != 0 :
                    self.name_to_atom[name] = result
                    self.atom_to_name[result] = name
                else :
                    result = None
                #end if
                lookup_done.set_result(result)
            #end do_lookup

            lookup_done = self.conn.loop.create_future()
            self._lookup_queue.append(do_lookup(weak_ref(self), lookup_done))
            self._name_lookup_pending[name] = lookup_done
            if self._lookup_process == None :
                self._lookup_process = self.conn.loop.create_task \
                  (
                    self._process_queue(weak_ref(self))
                  )
            #end if
            result = await lookup_done
            assert self._name_lookup_pending[name] == lookup_done
            del self._name_lookup_pending[name]
        #end if
        return \
            result
    #end intern_atom_async

    def get_atom_name(self, atom : int, decode = True) :
        "maps an atom ID to a name string. The atom must have already been defined."
        if not isinstance(atom, int) :
            raise TypeError("atom must be an int")
        #end if
        if atom in self.atom_to_name :
            result = self.atom_to_name[atom]
        else :
            res = self.conn.conn.core.GetAtomName(atom)
            result = b"".join(res.reply().name)
            self.name_to_atom[result] = atom
            self.atom_to_name[atom] = result
        #end if
        if decode :
            result = result.decode()
        #end if
        return \
            result
    #end get_atom_name

    async def get_atom_name_async(self, atom : int, decode = True) :
        "maps an atom ID to a name string. The atom must have already been defined."
        if not isinstance(atom, int) :
            raise TypeError("atom must be an int")
        #end if
        if atom in self.atom_to_name :
            result = self.atom_to_name[atom]
        elif atom in self._atom_lookup_pending :
            result = await self._atom_lookup_pending[atom]
        else :
            async def do_lookup(w_self, lookup_done) :
                self = w_self()
                assert self != None, "parent ConnWrapper has gone away"
                res = self.conn.conn.core.GetAtomName(atom)
                self.conn.conn.flush()
                reply = await self.conn.wait_for_reply(res)
                result = b"".join(reply.name)
                self.name_to_atom[result] = atom
                self.atom_to_name[atom] = result
                lookup_done.set_result(result)
            #end do_lookup

            lookup_done = self.conn.loop.create_future()
            self._lookup_queue.append(do_lookup(weak_ref(self), lookup_done))
            self._atom_lookup_pending[atom] = lookup_done
            if self._lookup_process == None :
                self._lookup_process = self.conn.loop.create_task \
                  (
                    self._process_queue(weak_ref(self))
                  )
            #end if
            result = await lookup_done
            assert self._atom_lookup_pending[atom] == lookup_done
            del self._atom_lookup_pending[atom]
        #end if
        if decode :
            result = result.decode()
        #end if
        return \
            result
    #end get_atom_name_async

    def flush(self) :
        "invalidates all cache entries."
        self.name_to_atom.clear()
        self.atom_to_name.clear()
    #end flush

#end AtomCache

class KeyMapping :
    "implements the rules for mapping keycodes to keysyms as per" \
    " the X11 spec. lock_is_shift_lock is True to interpret the Lock" \
    " modifier as shift lock, False to interpret as caps lock."

    __slots__ = \
        (
            "__weakref__",
            "_code_syms",
            "user_data", # dict, initially empty, may be used by caller for any purpose
            "mode_switch_mod",
            "numlock_mod",
            "lock_is_shift_lock",
        ) # to forestall typos

    def __init__(self, mapping, start_keycode) :
        "mapping is the reply object from a GetKeyboardMapping request."
        code_syms = {}
        keysyms = list(mapping.keysyms)
        for i in range(len(keysyms) // mapping.keysyms_per_keycode) :
            seg = keysyms \
              [i * mapping.keysyms_per_keycode : (i + 1) * mapping.keysyms_per_keycode] \
              [:4]
            # According to X11 core spec, first two entries form “group 1”, next two
            # form “group 2”. Spec does not define what to do with rest, so I forget
            # them.
            seg += [0] * (4 - len(seg))
            for j in range(1, len(seg)) :
                # propagate defaults
                if seg[j] == 0 :
                    seg[j] = seg[j - 1]
                #end if
            #end for
            if seg[0] != 0 : # <=> all entries are nonzero
                code_syms[i + start_keycode] = seg
            #end if
        #end for
        self._code_syms = code_syms
        self.user_data = qahirah.UserDataDict()
        self.mode_switch_mod = None
        self.numlock_mod = STATE.MOD2
        self.lock_is_shift_lock = False
    #end __init__

    @classmethod
    def obtain_from(celf, conn : ConnWrapper) :
        if not isinstance(conn, ConnWrapper) :
            raise TypeError("conn must be a ConnWrapper")
        #end if
        res = conn.conn.core.GetKeyboardMapping(KEYCODE_MIN, KEYCODE_MAX - KEYCODE_MIN + 1)
        mapping = res.reply()
        return \
            celf(mapping, KEYCODE_MIN)
    #end obtain_from

    @classmethod
    async def obtain_from_async(celf, conn : ConnWrapper) :
        if not isinstance(conn, ConnWrapper) :
            raise TypeError("conn must be a ConnWrapper")
        #end if
        mapping = await conn.wait_for_reply \
          (
            conn.conn.core.GetKeyboardMapping(KEYCODE_MIN, KEYCODE_MAX - KEYCODE_MIN + 1)
          )
        return \
            celf(mapping, KEYCODE_MIN)
    #end obtain_from_async

    def map_simple(self, evt : xproto.KeyPressEvent) :
        "maps a given key-press event to an appropriate keysym according" \
        " to the rules in the core X11 spec."
        if not isinstance(evt, xproto.KeyPressEvent) :
            raise TypeError("evt is not a KeyPressEvent")
        #end if
        if self.mode_switch_mod != None and not isinstance(self.mode_switch_mod, STATE) :
            raise TypeError("mode_switch_mod must be a STATE enum")
        #end if
        if self.numlock_mod != None and not isinstance(self.numlock_mod, STATE) :
            raise TypeError("numlock_mod must be a STATE enum")
        #end if
        keysym = XK.VoidSymbol # to begin with
        entry = self._code_syms.get(evt.detail)
        if entry != None :
            if self.mode_switch_mod != None and evt.state & mode_switch_mod.mask != 0 :
                entry = entry[2:4]
            else :
                entry = entry[0:2]
            #end if
            shift = evt.state & STATE.SHIFT.mask != 0
            lock = evt.state & STATE.LOCK.mask != 0
            numlock = self.numlock_mod != None and evt.state & self.numlock_mod.mask != 0
            if numlock and entry[1] in KEYSYM_KEYPAD :
                if shift or lock and self.lock_is_shift_lock :
                    keysym = entry[0]
                else :
                    keysym = entry[1]
                #end if
            elif not (shift or lock) :
                keysym = entry[0]
            elif lock and not self.lock_is_shift_lock :
                if shift :
                    keysym = entry[1]
                else :
                    keysym = entry[0]
                #end if
                if ord("a") <= keysym <= ord("z") :
                    keysym -= ord("a") - ord("A")
                #end if
            elif shift or lock and self.lock_is_shift_lock :
                keysym = entry[1]
            #end if
        #end if
        return \
            keysym
    #end map_simple

#end KeyMapping

class WindowWrapper :
    "convenience wrapper object around a specific X11 window, with" \
    " appropriately-filtered event dispatching."

    __slots__ = \
        (
            "__weakref__",
            "window",
            "conn",
            "loop",
            "user_data", # dict, initially empty, may be used by caller for any purpose
            "_event_filters",
        ) # to forestall typos

    _instances = WeakValueDictionary()
    _ud_refs = WeakValueDictionary()

    def __new__(celf, conn, window) :
        self = celf._instances.get(window)
        if self == None :
            self = super().__new__(celf)
            self.conn = conn
            self.window = window
            user_data = celf._ud_refs.get(window)
            if user_data == None :
                user_data = qahirah.UserDataDict()
                celf._ud_refs[window] = user_data
            #end if
            self.user_data = user_data
            self._event_filters = []
            self.loop = conn.loop
            celf._instances[window] = self
            self.conn.add_event_filter(self._conn_event_filter, weak_ref(self))
        #end if
        return \
            self
    #end __new__

    def __del__(self) :
        if self.conn != None :
            self.conn.remove_event_filter(self._conn_event_filter, weak_ref(self), optional = True)
            self.conn = None
            del type(self)._instances[self.window]
        #end if
    #end __del__

    @classmethod
    def get_window(celf, window) :
        "given an X11 window ID, returns the corresponding WindowWrapper object." \
        " Assumes one already exists!"
        return \
            celf._instances[window]
    #end get_window

    @staticmethod
    def _conn_event_filter(event, w_self) :
        self = w_self()
        assert self != None, "parent WindowWrapper has gone away"
        if isinstance(event, Exception) or event.window == self.window :
            event_filters = self._event_filters[:]
              # copy in case actions make changes
            while True :
                try :
                    action, arg = event_filters.pop(0)
                except IndexError :
                    break
                #end try
                action(self, event, arg)
            #end while
        #end if
    #end _conn_event_filter

    def add_event_filter(self, action, arg) :
        "installs a filter which gets to see all incoming events for this window." \
        " It is invoked as “action(window, event, arg)” where the meaning of arg" \
        " is up to you."
        if (
            any
              (
                elt == (action, arg)
                for i in range(len(self._event_filters))
                for elt in (self._event_filters[i],)
              )
        ) :
            raise KeyError("attempt to install duplicate action+arg")
        #end if
        self._event_filters.append((action, arg))
    #end add_event_filter

    def remove_event_filter(self, action, arg, optional : bool) :
        "removes a previously-installed event filter. optional indicates" \
        " not to report an error if no such filter is installed."
        pos = list \
          (
            i
            for i in range(len(self._event_filters))
            for elt in (self._event_filters[i],)
            if elt == (action, arg)
          )
        assert len(pos) <= 1
        if len(pos) == 1 :
            self._event_filters.pop(pos[0])
        elif not optional :
            raise KeyError("specified action+arg was not installed as an event filter")
        #end if
    #end remove_event_filter

    @classmethod
    def easy_create(celf, conn, bounds : qahirah.Rect, border_width : int, set_attrs) :
        if not isinstance(conn, ConnWrapper) :
            raise TypeError("conn must be a ConnWrapper")
        #end if
        window = conn.easy_create_window(bounds, border_width, set_attrs)
        return \
            celf(conn, window)
    #end easy_create

    @classmethod
    async def easy_create_async(celf, conn, bounds : qahirah.Rect, border_width : int, set_attrs) :
        if not isinstance(conn, ConnWrapper) :
            raise TypeError("conn must be a ConnWrapper")
        #end if
        window = await conn.easy_create_window_async(bounds, border_width, set_attrs)
        return \
            celf(conn, window)
    #end easy_create_async

    def destroy(self) :
        res = self.conn.core.DestroyWindow(self.window)
        self.conn.request_check(res.sequence)
    #end destroy

    def destroy_async(self) :
        res = self.conn.core.DestroyWindow(self.window)
        return \
            self.conn.wait_for_reply(res)
    #end destroy_async

    def wait_for_event(self) :
        "returns a Future that can be awaited to obtain the next input event for" \
        " this window. Note that, once an event is received, it is delivered to" \
        " all pending waiters."

        result = self.loop.create_future()

        def event_ready_action(self, event, result) :
            self.remove_event_filter(event_ready_action, result, optional = False)
            if isinstance(event, Exception) :
                result.set_exception(event)
            elif isinstance(event, xcffib.Event) :
                result.set_result(event)
            else :
                raise TypeError("unexpected type of event object %s" % repr(event))
            #end if
        #end event_ready_action

    #begin wait_for_event
        self.add_event_filter(event_ready_action, result)
        return result
    #end wait_for_event

    def easy_create_surface(self, use_xrender : bool) :
        "convenience routine which creates an XCBSurface for drawing" \
        " with Cairo into this window, with the option of using xrender.\n" \
        "\n" \
        "Note that the surface is initially created with dummy dimensions;" \
        " these will need to be fixed up with a set_size() call when you" \
        " receive a ConfigureNotifyEvent for the window."
        return \
            self.conn.easy_create_surface(self.window, use_xrender)
    #end easy_create_surface

#end WindowWrapper

#+
# Cleanup
#-

def _atexit() :
    # disable all __del__ methods at process termination to avoid segfaults
    for cłass in (WindowWrapper,) :
        delattr(cłass, "__del__")
    #end for
#end _atexit
atexit.register(_atexit)
del _atexit
