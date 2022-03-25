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
# <https://www.x.org/releases/X11R7.7/doc/libxcb/tutorial/index.html>
# General X11 docs: <https://www.x.org/releases/X11R7.7/doc/index.html>

import struct
import enum
from weakref import \
    ref as weak_ref, \
    WeakValueDictionary
import asyncio
import atexit
import qahirah
from qahirah import \
    Vector, \
    Rect
import cffi
import xcffib
from xcffib import \
    xproto, \
    xfixes, \
    render as xrender, \
    shape as xshape

#+
# Useful stuff
#-

def _wderef(wself, parent) :
    self = wself()
    assert self != None, "parent %s has gone away" % parent
    return \
        self
#end _wderef

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

class Colour(qahirah.Colour) :
    "extend qahirah.Colour with conversions to/from X11 format."

    @classmethod
    def from_colour(celf, c) :
        "converts a superclass instance to an instance of this class."
        return \
            celf(*tuple(c))
    #end from_colour

    def to_card16_rgb(self) :
        "returns (r, g, b) tuple where each component is a card16."
        return \
            tuple(round(c * 65535) for c in (self.r, self.g, self.b))
    #end to_card16_rgb

    @classmethod
    def from_card16_rgb(celf, components) :
        "converts (r, g, b) tuple where each component is a card16 to a Colour."
        if (
                not isinstance(components, (tuple, list))
            or
                len(components) != 3
            or
                not all(isinstance(c, int) for c in components)
            or
                not all(0 <= c < 65536 for c in components)
        ) :
            raise TypeError("components must be an (r, g, b) of card16 values")
        #end if
        return \
            celf(*tuple(c / 65535 for c in components) + (1,))
    #end from_card16_rgb

    def to_pixel(self) :
        "returns an integer combining suitably-shifted Cairo-compatible r, g and b components."
        return \
            (
                round(self.r * 255) << 16
            |
                round(self.g * 255) << 8
            |
                round(self.b * 255)
            )
    #end to_pixel

    @classmethod
    def from_pixel(celf, pixel) :
        "converts an integer combining suitably-shifted Cairo-compatible" \
        " r, g and b components to a Colour."
        return \
            celf((pixel >> 16 & 255) / 255, (pixel >> 8 & 255) / 255, (pixel & 255) / 255, 1)
    #end from_pixel

#end Colour
Colour.x11 = Colour.X11_Colours(Colour)

#+
# X11 protocol definitions
#-

XID = int
  # ID codes used for identifying objects created in the server
  # connection; codes are assigned by client.

class X :
    "various X11 protocol codes, taken from /usr/include/X11/Xproto.h" \
    " and /usr/include/X11/X.h."

    # X11 reply codes
    Reply = 1 # success
    Error = 0 # failure

    # X11 request codes
    CreateWindow = 1
    ChangeWindowAttributes = 2
    GetWindowAttributes = 3
    DestroyWindow = 4
    DestroySubwindows = 5
    ChangeSaveSet = 6
    ReparentWindow = 7
    MapWindow = 8
    MapSubwindows = 9
    UnmapWindow = 10
    UnmapSubwindows = 11
    ConfigureWindow = 12
    CirculateWindow = 13
    GetGeometry = 14
    QueryTree = 15
    InternAtom = 16
    GetAtomName = 17
    ChangeProperty = 18
    DeleteProperty = 19
    GetProperty = 20
    ListProperties = 21
    SetSelectionOwner = 22
    GetSelectionOwner = 23
    ConvertSelection = 24
    SendEvent = 25
    GrabPointer = 26
    UngrabPointer = 27
    GrabButton = 28
    UngrabButton = 29
    ChangeActivePointerGrab = 30
    GrabKeyboard = 31
    UngrabKeyboard = 32
    GrabKey = 33
    UngrabKey = 34
    AllowEvents = 35
    GrabServer = 36
    UngrabServer = 37
    QueryPointer = 38
    GetMotionEvents = 39
    TranslateCoords = 40
    WarpPointer = 41
    SetInputFocus = 42
    GetInputFocus = 43
    QueryKeymap = 44
    OpenFont = 45
    CloseFont = 46
    QueryFont = 47
    QueryTextExtents = 48
    ListFonts = 49
    ListFontsWithInfo = 50
    SetFontPath = 51
    GetFontPath = 52
    CreatePixmap = 53
    FreePixmap = 54
    CreateGC = 55
    ChangeGC = 56
    CopyGC = 57
    SetDashes = 58
    SetClipRectangles = 59
    FreeGC = 60
    ClearArea = 61
    CopyArea = 62
    CopyPlane = 63
    PolyPoint = 64
    PolyLine = 65
    PolySegment = 66
    PolyRectangle = 67
    PolyArc = 68
    FillPoly = 69
    PolyFillRectangle = 70
    PolyFillArc = 71
    PutImage = 72
    GetImage = 73
    PolyText8 = 74
    PolyText16 = 75
    ImageText8 = 76
    ImageText16 = 77
    CreateColormap = 78
    FreeColormap = 79
    CopyColormapAndFree = 80
    InstallColormap = 81
    UninstallColormap = 82
    ListInstalledColormaps = 83
    AllocColor = 84
    AllocNamedColor = 85
    AllocColorCells = 86
    AllocColorPlanes = 87
    FreeColors = 88
    StoreColors = 89
    StoreNamedColor = 90
    QueryColors = 91
    LookupColor = 92
    CreateCursor = 93
    CreateGlyphCursor = 94
    FreeCursor = 95
    RecolorCursor = 96
    QueryBestSize = 97
    QueryExtension = 98
    ListExtensions = 99
    ChangeKeyboardMapping = 100
    GetKeyboardMapping = 101
    ChangeKeyboardControl = 102
    GetKeyboardControl = 103
    Bell = 104
    ChangePointerControl = 105
    GetPointerControl = 106
    SetScreenSaver = 107
    GetScreenSaver = 108
    ChangeHosts = 109
    ListHosts = 110
    SetAccessControl = 111
    SetCloseDownMode = 112
    KillClient = 113
    RotateProperties = 114
    ForceScreenSaver = 115
    SetPointerMapping = 116
    GetPointerMapping = 117
    SetModifierMapping = 118
    GetModifierMapping = 119
    NoOperation = 127

    # X11 event codes, starting from 2 to avoid confusion with reply codes
    KeyPress = 2
    KeyRelease = 3
    ButtonPress = 4
    ButtonRelease = 5
    MotionNotify = 6
    EnterNotify = 7
    LeaveNotify = 8
    FocusIn = 9
    FocusOut = 10
    KeymapNotify = 11
    Expose = 12
    GraphicsExpose = 13
    NoExpose = 14
    VisibilityNotify = 15
    CreateNotify = 16
    DestroyNotify = 17
    UnmapNotify = 18
    MapNotify = 19
    MapRequest = 20
    ReparentNotify = 21
    ConfigureNotify = 22
    ConfigureRequest = 23
    GravityNotify = 24
    ResizeRequest = 25
    CirculateNotify = 26
    CirculateRequest = 27
    PropertyNotify = 28
    SelectionClear = 29
    SelectionRequest = 30
    SelectionNotify = 31
    ColormapNotify = 32
    ClientMessage = 33
    MappingNotify = 34
    GenericEvent = 35
    LASTEvent = 36 # one beyond last defined event number

    ALL_EVENTS = frozenset(range(KeyPress, LASTEvent))

#end X

class XA :
    "predefined atoms, extracted from /usr/include/X11/Xatom.h."
    PRIMARY = 1
    SECONDARY = 2
    ARC = 3
    ATOM = 4
    BITMAP = 5
    CARDINAL = 6
    COLORMAP = 7
    CURSOR = 8
    CUT_BUFFER0 = 9
    CUT_BUFFER1 = 10
    CUT_BUFFER2 = 11
    CUT_BUFFER3 = 12
    CUT_BUFFER4 = 13
    CUT_BUFFER5 = 14
    CUT_BUFFER6 = 15
    CUT_BUFFER7 = 16
    DRAWABLE = 17
    FONT = 18
    INTEGER = 19
    PIXMAP = 20
    POINT = 21
    RECTANGLE = 22
    RESOURCE_MANAGER = 23
    RGB_COLOR_MAP = 24
    RGB_BEST_MAP = 25
    RGB_BLUE_MAP = 26
    RGB_DEFAULT_MAP = 27
    RGB_GRAY_MAP = 28
    RGB_GREEN_MAP = 29
    RGB_RED_MAP = 30
    STRING = 31
    VISUALID = 32
    WINDOW = 33
    WM_COMMAND = 34
    WM_HINTS = 35
    WM_CLIENT_MACHINE = 36
    WM_ICON_NAME = 37
    WM_ICON_SIZE = 38
    WM_NAME = 39
    WM_NORMAL_HINTS = 40
    WM_SIZE_HINTS = 41
    WM_ZOOM_HINTS = 42
    MIN_SPACE = 43
    NORM_SPACE = 44
    MAX_SPACE = 45
    END_SPACE = 46
    SUPERSCRIPT_X = 47
    SUPERSCRIPT_Y = 48
    SUBSCRIPT_X = 49
    SUBSCRIPT_Y = 50
    UNDERLINE_POSITION = 51
    UNDERLINE_THICKNESS = 52
    STRIKEOUT_ASCENT = 53
    STRIKEOUT_DESCENT = 54
    ITALIC_ANGLE = 55
    X_HEIGHT = 56
    QUAD_WIDTH = 57
    WEIGHT = 58
    POINT_SIZE = 59
    RESOLUTION = 60
    COPYRIGHT = 61
    NOTICE = 62
    FONT_NAME = 63
    FAMILY_NAME = 64
    FULL_NAME = 65
    CAP_HEIGHT = 66
    WM_CLASS = 67
    WM_TRANSIENT_FOR = 68

    LAST_PREDEFINED = 68
#end XA

XA_NAME = dict \
  ( # atom value to name
    (n, getattr(XA, n))
    for n in dir(XA)
    if not n.startswith("_") and n != "LAST_PREDEFINED"
  )

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

class MaskAttr(enum.IntEnum) :
    "Base class for various X11 data which is passed as a bitmask" \
    " indicating which values are present, followed by a list of" \
    " those (integer) values in order of increasing bit number. I" \
    " define a more convenient form, where you pass a sequence of" \
    " pairs, each element of which is a bit number followed by the" \
    " corresponding value, allowing the bit numbers to be in any" \
    " order, the values being automatically sorted into the right" \
    " order as the bit mask is generated from the bit numbers by" \
    " calling the pack_attributes method."

    @property
    def mask(self) :
        "the mask for this bit number."
        return 1 << self.value
    #end mask

    @classmethod
    def pack_attributes(celf, attrs, default_attrs = None) :
        "converts attributes from my sequence/dict-of-key+value form" \
        " to the mask+ordered-value-list form that X11 expects. If not" \
        " None, default_attrs is used to fill in defaults not specified" \
        " in attrs."
        if isinstance(attrs, dict) :
            attrs = tuple(attrs.items())
        #end if
        if isinstance(default_attrs, dict) :
            default_attrs = tuple(default_attrs.items())
        #end if
        if (
                not all
                  (
                        isinstance(a, (tuple, list))
                    and
                        all
                          (
                                len(i) == 2
                            and
                                isinstance(i[0], celf)
                            and
                                isinstance(i[1], int)
                            for i in a
                          )
                    for a in (attrs,) + ((), (default_attrs,))[default_attrs != None]
                  )
            or
                len(set(i[0] for i in attrs)) != len(attrs)
        ) :
            raise TypeError \
              (
                    "attributes are not unique-keyed sequence of (%s.xxx, value) pairs"
                %
                    celf.__name__
              )
        #end if
        value_mask = 0
        value_list = []
        attrs = tuple(attrs)
        if default_attrs != None :
            specified = set(i[0] for i in attrs)
            attrs += tuple(i for i in default_attrs if i[0] not in specified)
        #end if
        for bit_nr, value in sorted(attrs, key = lambda x : x[0]) :
            value_mask |= bit_nr.mask
            value_list.append(value)
        #end for
        return \
            value_mask, value_list
    #end pack_attributes

    @classmethod
    def make_mask(celf, attrs) :
        "constructs a mask from the attribute bits in attrs."
        value_mask = 0
        for a in attrs :
            if not isinstance(a, celf) :
                raise TypeError("elements of attrs are not %s" % celf.__name__)
            #end if
            value_mask |= a.mask
        #end for
        return \
            value_mask
    #end make_mask

#end MaskAttr

class WINATTR(MaskAttr) :
    "bit numbers corresponding to bit masks for window attributes to" \
    " create_window calls."
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

#end WINATTR
WINATTR.COLORMAP = WINATTR.COLOURMAP # if you prefer

class GCATTR(MaskAttr) :
    "bit numbers corresponding to bit masks for GC attributes to" \
    " create_gc calls."
    FUNCTION = 0
    PLANEMASK = 1
    FOREGROUND = 2
    BACKGROUND = 3
    LINEWIDTH = 4
    LINESTYLE = 5
    CAPSTYLE = 6
    JOINSTYLE = 7
    FILLSTYLE = 8
    FILLRULE = 9
    TILE = 10
    STIPPLE = 11
    TILESTIPXORIGIN = 12
    TILESTIPYORIGIN = 13
    FONT = 14
    SUBWINDOWMODE = 15
    GRAPHICSEXPOSURES = 16
    CLIPXORIGIN = 17
    CLIPYORIGIN = 18
    CLIPMASK = 19
    DASHOFFSET = 20
    DASHLIST = 21
    ARCMODE = 22

#end GCATTR

class WINCONFIG(MaskAttr) :
    "bit numbers corresponding to bit masks for attributes to" \
    " ConfigWindow call."
    X = 0
    Y = 1
    WIDTH = 2
    HEIGHT = 3
    BORDERWIDTH = 4
    SIBLING = 5
    STACKMODE = 6

#end WINCONFIG

class Connection :
    "wraps an XCB connection to the X server. You can instantiate directly," \
    " passing the result from xcffib.Connection(), or you can use the open()" \
    " method."

    __slots__ = \
        (
            "__weakref__",
            "conn",
            "loop",
            "atom_cache",
            "user_data",
            "_conn_fd",
            "_ext_inited",
            "_event_filters",
            "_reply_queue",
            "last_sequence",
        ) # to forestall typos

    sequence_jump = 1 << 30
      # hopefully sequence numbers should never jump by this much at once

    def __init__(self, conn, loop = None) :

        def def_query_version(key, args) :

            def do_query(self) :
                res = getattr(self.conn(key), "QueryVersion")(*args)
                reply = res.reply()
            #end do_query

        #begin def_query_version
            return \
                do_query
        #end def_query_version

    #begin __init__
        _get_conn(conn) # just a sanity check
        if loop == None :
            loop = get_event_loop()
        #end if
        self.conn = conn
        self.loop = loop
        self.atom_cache = AtomCache(self)
        self.user_data = qahirah.UserDataDict()
        self._conn_fd = conn.get_file_descriptor()
          # keep my own copy because conn.get_file_descriptor()
          # could return an error later
        self._ext_inited = dict \
          (
            (key, {"query" : def_query_version(key, args), "done" : False})
            for key, args in
                (
                    (xfixes.key, (xfixes.MAJOR_VERSION, xfixes.MINOR_VERSION)),
                    (xrender.key, (xrender.MAJOR_VERSION, xrender.MINOR_VERSION)),
                    (xshape.key, ()),
                )
          )
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
    def open(celf, loop = None, *, display = None, fd = -1, auth = None) :
        "opens an xcffib.Connection and returns a Connection for it."
        conn = xcffib.Connection(display = display, fd = fd, auth = auth)
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

    def init_ext(self, key) :
        "initializes the specified extension for use on this Connection, if not" \
        " already done. key is one of the xcffib.«module».key values identifying" \
        " the extension. Only a limited subset of these is recognized for now."
        if key not in self._ext_inited :
            raise KeyError \
              (
                    "unknown extension %s"
                %
                    (lambda : repr(key), lambda : key.name)[hasattr(key, "name")]()
              )
        #end if
        entry = self._ext_inited[key]
        if not entry["done"] :
            entry["query"](self)
            entry["done"] = True
        #end if
    #end init_ext

    @staticmethod
    def _handle_conn_readable(w_self) :
        # common fd-readable callback for monitoring server connection
        # for input.
        self = _wderef(w_self, "Connection")

        # need to check for request replies first, before events,
        # otherwise these could be held up indefinitely by a
        # never-ending stream of events
        if len(self._reply_queue) != 0 :
            action, args = self._reply_queue.pop(0)
            action(self, *args)
        #end if

        while True :
            if len(self._event_filters) == 0 :
                break
            try :
                event = self.conn.poll_for_event()
            except xcffib.XcffibException :
                event = None
            #end try
            if event == None :
                break
            event_filters = self._event_filters[:]
              # copy in case actions make changes
            while True :
                try :
                    action, args = event_filters.pop(0)
                except IndexError :
                    break
                #end try
                action(event, *args)
            #end while
        #end while

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
            for action, args in self._event_filters[:] :
              # copy in case actions make changes
                action(conn_err, *args)
            #end for
        #end if
    #end _handle_conn_readable

    def add_event_filter(self, action, args = ()) :
        "installs a filter which gets to see all incoming events. It is invoked" \
        " as “action(event, *args)“ where the meaning of args is up to you."
        if (
            any
              (
                elt == (action, args)
                for i in range(len(self._event_filters))
                for elt in (self._event_filters[i],)
              )
        ) :
            raise KeyError("attempt to install duplicate action+args")
        #end if
        newelt = (action, args)
        if len(self._event_filters) + len(self._reply_queue) == 0 :
            self.loop.add_reader \
              (
                self._conn_fd,
                self._handle_conn_readable,
                weak_ref(self)
              )
        #end if
        self._event_filters.append(newelt)
    #end add_event_filter

    def remove_event_filter(self, action, args = (), *, optional : bool) :
        "removes a previously-installed event filter. optional indicates" \
        " not to report an error if no such filter is installed."
        pos = list \
          (
            i
            for i in range(len(self._event_filters))
            for elt in (self._event_filters[i],)
            if elt == (action, args)
          )
        assert len(pos) <= 1
        if len(pos) == 1 :
            self._event_filters.pop(pos[0])
            if self._conn_fd != None and len(self._event_filters) + len(self._reply_queue) == 0 :
                self.loop.remove_reader(self._conn_fd)
            #end if
        elif not optional :
            raise KeyError("specified action+args was not installed as an event filter")
        #end if
    #end remove_event_filter

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
            newelt = (reply_ready_action, (result,))
            if len(self._event_filters) + len(self._reply_queue) == 0 :
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

    def root_window(self, rootnr) :
        "returns a Window object representing the root window."
        return \
            Window.root_window(self, rootnr)
    #end root_window

    def _create_pixmap(self, drawable : XID, depth : int, dimensions : Vector) :
        # common code for create_pixmap routines.
        pixmap_id = self.conn.generate_id()
        dimensions = Vector.from_tuple(dimensions)
        res = self.conn.core.CreatePixmap \
          (
            pid = pixmap_id,
            drawable = drawable,
            depth = depth,
            width = dimensions.x,
            height = dimensions.y
          )
        return \
            pixmap_id, res
    #end _create_pixmap

    def _create_window(self, depth : int, parent, bounds : Rect, border_width : int, window_class, visual, set_attrs) :
        if not isinstance(parent, Window) :
            raise TypeError("parent must be a Window")
        #end if
        id = self.conn.generate_id()
        value_mask, value_list = WINATTR.pack_attributes(set_attrs)
        res = self.conn.core.CreateWindow \
          (
            depth = depth,
            wid = id,
            parent = parent.id,
            x = bounds.left,
            y = bounds.top,
            width = bounds.width,
            height = bounds.height,
            border_width = border_width,
            _class = window_class,
            visual = visual,
            value_mask = value_mask,
            value_list = value_list
          )
        return \
            id, res
    #end _create_window

    def create_window(self, depth : int, parent, bounds : Rect, border_width : int, window_class, visual, set_attrs) :
        window, res = self._create_window(depth, parent, bounds, border_width, window_class, visual, set_attrs)
        self.conn.request_check(res.sequence)
        return \
            window
    #end create_window

    async def create_window_async(self, depth : int, parent, bounds : Rect, border_width : int, window_class, visual, set_attrs) :
        window, res = self._create_window(depth, parent, bounds, border_width, window_class, visual, set_attrs)
        await self.wait_for_reply(res)
        return \
            window
    #end create_window_async

    def create_surface(self, screenindex : int, drawable : XID, dimensions, use_xrender : bool) :
        "convenience routine which creates an XCBSurface for drawing" \
        " with Cairo into the specified drawable, with the option of" \
        " using xrender."
        dimensions = Vector.from_tuple(dimensions)
        if use_xrender :
            use_screen = self.conn.get_screen_pointers()[screenindex]
            self.init_ext(xrender.key)
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
                screen = use_screen,
                drawable = drawable,
                format = use_pictformats[0],
                width = dimensions.x,
                height = dimensions.y
              )
        else :
            use_root = self.conn.setup.roots[screenindex]
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
                drawable = drawable,
                visual = use_visuals[0],
                width = dimensions.x,
                height = dimensions.y
              )
        #end if
        return \
            surface
    #end create_surface

    def get_geometry(self, drawable : XID) :
        res = self.conn.core.GetGeometry(drawable)
        result = res.reply()
        result.bounds = Rect(result.x, result.y, result.width, result.height)
        return \
            result
    #end get_geometry

    async def get_geometry_async(self, drawable : XID) :
        res = self.conn.core.GetGeometry(drawable)
        result = await self.wait_for_reply(res)
        result.bounds = Rect(result.x, result.y, result.width, result.height)
        return \
            result
    #end get_geometry_async

#end Connection

class AtomCache :
    "two-way mapping between atom IDs and corresponding name strings, with" \
    " caching to reduce communication with the X server. Instantiate with a" \
    " Connection object which will be used to communicate with the server." \
    " Both synchronous and asynchronous versions of intern_atom and" \
    " get_atom_name calls are provided."

    __slots__ = \
        (
            "__weakref__",
            "_w_conn",
            "name_to_atom",
            "atom_to_name",
            "preload_standard",
            "_lookup_process",
            "_lookup_queue",
            "_name_lookup_pending",
            "_atom_lookup_pending",
        ) # to forestall typos

    def _do_preload_standard(self) :
        # preload standard atoms if specified
        if self.preload_standard :
            for key, value in XA_NAME.items() :
                self.name_to_atom[key] = value
                self.atom_to_name[value] = key
            #end for
        #end if
    #end _do_preload_standard

    def __init__(self, conn, preload_standard = True) :
        if not isinstance(conn, Connection) :
            raise TypeError("conn must be a Connection")
        #end if
        self._w_conn = weak_ref(conn)
        self.name_to_atom = {}
        self.atom_to_name = {}
        self.preload_standard = preload_standard
        self._lookup_process = None
        self._lookup_queue = []
        self._name_lookup_pending = {}
        self._atom_lookup_pending = {}
        self._do_preload_standard()
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
        self = _wderef(w_self, "Connection")
        while True :
            try :
                entry = self._lookup_queue.pop(0)
            except IndexError :
                break
            #end try
            await entry
        #end while
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
            res = _wderef(self._w_conn, "Connection").conn.core.InternAtom \
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
        elif name in self._name_lookup_pending :
            result = await self._name_lookup_pending[name]
        else :
            async def do_lookup(w_self, lookup_done) :
                self = _wderef(w_self, "Connection")
                conn = _wderef(self._w_conn, "Connection")
                res = conn.conn.core.InternAtom \
                  (
                    only_if_exists = not create_if,
                    name_len = len(name),
                    name = name
                  )
                conn.conn.flush()
                reply = await conn.wait_for_reply(res)
                result = reply.atom
                if result != 0 :
                    self.name_to_atom[name] = result
                    self.atom_to_name[result] = name
                else :
                    result = None
                #end if
                lookup_done.set_result(result)
            #end do_lookup

            conn = _wderef(self._w_conn, "Connection")
            lookup_done = conn.loop.create_future()
            self._lookup_queue.append(do_lookup(weak_ref(self), lookup_done))
            self._name_lookup_pending[name] = lookup_done
            if self._lookup_process == None :
                self._lookup_process = conn.loop.create_task \
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
            res = _wderef(self._w_conn, "Connection").conn.core.GetAtomName(atom)
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
                self = _wderef(w_self, "Connection")
                conn = _wderef(self._w_conn, "Connection")
                res = conn.conn.core.GetAtomName(atom)
                conn.conn.flush()
                reply = await conn.wait_for_reply(res)
                result = b"".join(reply.name)
                self.name_to_atom[result] = atom
                self.atom_to_name[atom] = result
                lookup_done.set_result(result)
            #end do_lookup

            conn = _wderef(self._w_conn, "Connection")
            lookup_done = conn.loop.create_future()
            self._lookup_queue.append(do_lookup(weak_ref(self), lookup_done))
            self._atom_lookup_pending[atom] = lookup_done
            if self._lookup_process == None :
                self._lookup_process = conn.loop.create_task \
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
        self._do_preload_standard()
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
    def obtain_from(celf, conn : Connection) :
        "queries the specified X server connection for its current key mapping" \
        " and returns a KeyMapping object based on that."
        if not isinstance(conn, Connection) :
            raise TypeError("conn must be a Connection")
        #end if
        res = conn.conn.core.GetKeyboardMapping(KEYCODE_MIN, KEYCODE_MAX - KEYCODE_MIN + 1)
        mapping = res.reply()
        return \
            celf(mapping, KEYCODE_MIN)
    #end obtain_from

    @classmethod
    async def obtain_from_async(celf, conn : Connection) :
        "queries the specified X server connection for its current key mapping" \
        " and returns a KeyMapping object based on that."
        if not isinstance(conn, Connection) :
            raise TypeError("conn must be a Connection")
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
        " to the rules in the core X11 spec as applied to this mapping."
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

class Pixmap :
    "wraps a Pixmap, with an associated surface already created for Cairo drawing." \
    " Do not instantiate directly; get from Window.create_pixmap()."

    def __init__(self, id, surface, conn) :
        self.id = id
        self.surface = surface
        self.conn = conn
    #end __init__

    def destroy(self) :
        if self.id != None :
            self.surface = None
            res = self.conn.conn.core.FreePixmap(self.id)
            self.conn.conn.request_check(res.sequence)
            self.id = None
            self.conn = None
        #end if
    #end destroy

    def __del__(self) :
        self.destroy()
    #end __del__(self)

    def convert_to_1bit(self, dimensions : Vector, use_xrender : bool) :
        "assuming this is an RGB Pixmap, creates a new 1-bit Pixmap containing" \
        " a bilevel conversion of the image."
        use_screen = self.conn.conn.pref_screen
        result = self.conn.root_window(use_screen) \
            .create_pixmap(use_screen, 1, dimensions, use_xrender)
        cursgc = GContext.create \
          (
            conn = self.conn,
            drawable_id = result.id,
            set_attrs = ()
          )
        cursgc.copy_to_1bit(self.id, result.id, dimensions)
        return \
            result
    #end convert_to_1bit

#end Pixmap

class Cursor :

    __slots__ = \
        (
            "__weakref__",
            "conn",
            "id",
            "user_data", # dict, initially empty, may be used by caller for any purpose
        ) # to forestall typos

    _instances = WeakValueDictionary()
    _ud_refs = WeakValueDictionary()

    def __new__(celf, conn, id) :
        self = celf._instances.get(id)
        if self == None :
            self = super().__new__(celf)
            self.conn = conn
            self.id = id
            user_data = celf._ud_refs.get(id)
            if user_data == None :
                user_data = qahirah.UserDataDict()
                celf._ud_refs[id] = user_data
            #end if
            self.user_data = user_data
            celf._instances[id] = self
        #end if
        return \
            self
    #end __new__

    @classmethod
    def create \
      (
        celf,
        conn : Connection,
        source : Pixmap,
        mask : Pixmap, # optional
        forecolour : Colour,
        backcolour : Colour,
        hotspot : Vector
      ) :
        "creates a Cursor from the specified settings. the source and (if specified)" \
        " mask pixmaps must be 1-bit deep."
        if (
                not isinstance(conn, Connection)
            or
                not isinstance(source, Pixmap)
            or
                mask != None and not isinstance(mask, Pixmap)
            or
                not isinstance(forecolour, qahirah.Colour)
            or
                not isinstance(backcolour, qahirah.Colour)
            or
                not isinstance(hotspot, Vector)
            or
                not all(isinstance(x, int) and 0 <= x < 65536 for x in tuple(hotspot))
        ) :
            raise TypeError("bad args")
        #end if
        id = conn.conn.generate_id()
        fore_rgb = Colour.from_colour(forecolour).to_card16_rgb()
        back_rgb = Colour.from_colour(backcolour).to_card16_rgb()
        res = conn.conn.core.CreateCursor \
          (
            cid = id,
            source = source.id,
            mask =
                (
                    lambda : 0,
                    lambda : mask.id,
                )[mask != None](),
            fore_red = fore_rgb[0],
            fore_green = fore_rgb[1],
            fore_blue = fore_rgb[2],
            back_red = back_rgb[0],
            back_green = back_rgb[1],
            back_blue = back_rgb[2],
            x = hotspot.x,
            y = hotspot.y
          )
        conn.conn.request_check(res.sequence)
        return \
            celf(conn, id)
    #end create

    @classmethod
    def create_from_rgb \
      (
        celf,
        conn : Connection,
        source : Pixmap,
        mask : Pixmap, # optional
        dimensions : Vector,
        forecolour : Colour,
        backcolour : Colour,
        hotspot : Vector,
        use_xrender : bool
      ) :
        "creates a Cursor from the specified settings. The source and (if specified)" \
        " mask Pixmaps are assumed to be 24 bits deep (suitable for Cairo to draw" \
        " into); they will be down-converted to 1 bit before use."
        use_screen = conn.conn.pref_screen
        src1bit = conn.root_window(use_screen).create_pixmap(use_screen, 1, dimensions, use_xrender)
        if mask != None :
            mask1bit = conn.root_window(use_screen).create_pixmap(use_screen, 1, dimensions, use_xrender)
        else :
            mask1bit = None
        #end if
        cursgc = GContext.create \
          (
            conn = conn,
            drawable_id = src1bit.id,
            set_attrs = ()
          )
        for srcpix, dstpix in \
            (
                (
                    (source, src1bit),
                )
            +
                (
                    (),
                    ((mask, mask1bit),),
                )[mask != None]
            ) \
        :
            cursgc.copy_to_1bit(srcpix.id, dstpix.id, dimensions)
        #end for
        return \
            celf.create(conn, src1bit, mask1bit, forecolour, backcolour, hotspot)
    #end create_from_rgb

    def __del__(self) :
        if self.conn != None :
            if self.id != None :
                res = self.conn.conn.core.FreeCursor(self.id)
                self.conn.conn.request_check(res.sequence)
                self.id = None
            #end if
            self.conn = None
        #end if
    #end __del__

    def recolour(self, forecolour : Colour, backcolour : Colour) :
        if (
                not isinstance(forecolour, qahirah.Colour)
            or
                not isinstance(backcolour, qahirah.Colour)
        ) :
            raise TypeError("colours must be Colour values")
        #end if
        fore_rgb = Colour.from_colour(forecolour).to_card16_rgb()
        back_rgb = Colour.from_colour(backcolour).to_card16_rgb()
        res = self.conn.conn.core.RecolorCursor \
          (
            cursor = self.id,
            fore_red = fore_rgb[0],
            fore_green = fore_rgb[1],
            fore_blue = fore_rgb[2],
            back_red = back_rgb[0],
            back_green = back_rgb[1],
            back_blue = back_rgb[2]
          )
        self.conn.conn.request_check(res.sequence)
    #end recolour

#end Cursor

class Window :
    "convenience wrapper object around a specific X11 window, with" \
    " appropriately-filtered event dispatching. Do not instantiate" \
    " directly; get from the create() or create_async() methods."

    __slots__ = \
        (
            "__weakref__",
            "id",
            "conn",
            "loop",
            "gcontext",
            "user_data", # dict, initially empty, may be used by caller for any purpose
            "_event_filters",
            "_parent",
            "_children",
        ) # to forestall typos

    _instances = WeakValueDictionary()
    _ud_refs = WeakValueDictionary()

    def __new__(celf, conn, id) :
        self = celf._instances.get(id)
        if self == None :
            self = super().__new__(celf)
            self.conn = conn
            self.id = id
            user_data = celf._ud_refs.get(id)
            if user_data == None :
                user_data = qahirah.UserDataDict()
                celf._ud_refs[id] = user_data
            #end if
            self.user_data = user_data
            self._event_filters = []
            self._parent = None
            self._children = set()
            self.loop = conn.loop
            self.gcontext = GContext.create(conn, id)
            celf._instances[id] = self
        #end if
        return \
            self
    #end __new__

    def __del__(self) :
        if self.conn != None :
            self.conn.remove_event_filter(self._conn_event_filter, weak_ref(self), optional = True)
            self.conn = None
            del type(self)._instances[self.id]
        #end if
    #end __del__

    @classmethod
    def root_window(celf, conn, rootnr) :
        "returns a Window object representing the root window."
        return \
            celf(conn, conn.conn.setup.roots[rootnr].root)
    #end root_window

    def set_mapped(self, mapped : bool) :
        "sets the window’s mapped (visible) state."
        if mapped :
            res = self.conn.conn.core.MapWindow(self.id)
        else :
            res = self.conn.conn.core.UnmapWindow(self.id)
        #end if
        self.conn.conn.request_check(res.sequence)
    #end set_mapped

    def set_parent(self, other, pos : Vector) :
        "does a reparent of this window to the other one."
        if not isinstance(other, Window) or other.conn != self.conn :
            raise TypeError("other is not a Window or on a different Connection")
        #end if
        if self._parent != None :
            self.get_window(self._parent)._children.discard(self.id)
        #end if
        other._children.add(self.id)
        self._parent = other.id
        pos = Vector.from_tuple(pos)
        res = self.conn.conn.core.ReparentWindow \
          (
            window = self.id,
            parent = other.id,
            x = pos.x,
            y = pos.y
          )
        self.conn.conn.request_check(res.sequence)
    #end set_parent

    @classmethod
    def get_window(celf, id) :
        "given an X11 window ID, returns the corresponding Window object." \
        " Assumes one already exists!"
        return \
            celf._instances[id]
    #end get_window

    @staticmethod
    def _conn_event_filter(event, w_self) :
        self = w_self()
        if self != None :
            if isinstance(event, xcffib.Event) :
                event_window = set \
                  (
                    getattr(event, e)
                    for e in ("child", "event", "window")
                    if hasattr(event, e)
                  )
            else :
                event_window = set()
            #end if
            if len(event_window) == 0 or self.id in event_window :
                event_filters = self._event_filters[:]
                  # copy in case actions make changes
                while True :
                    try :
                        action, args, selevents = event_filters.pop(0)
                    except IndexError :
                        break
                    #end try
                    if selevents != None and hasattr(event, "response_type") :
                        response_type = event.response_type & 127
                          # strip off synthetic bit
                    else :
                        response_type = None
                    #end if
                    if selevents == None or response_type in selevents :
                        action(self, event, *args)
                    #end if
                #end while
            #end if
            if len(event_window) != 0 :
                for child in self._children :
                    child = self.get_window(child)
                    child._conn_event_filter(event, weak_ref(child))
                #end if
            #end if
        #end if
    #end _conn_event_filter

    def add_event_filter(self, action, args = (), selevents = None) :
        "installs a filter which gets to see the specified incoming events (or all" \
        " events if not specified) for this window. It is invoked as" \
        " “action(window, event, *args)” where the meaning of args is up to you." \
        "\n" \
        "Only one instance of any action+args combination is allowed to be" \
        " installed at a time. If there is an existing entry, selevents will be" \
        " added to its event set, provided it was not None."
        if isinstance(selevents, int) :
            selevents = {selevents}
        #end if
        if (
                selevents != None
            and
                not all(isinstance(e, int) and e >= 2 for e in selevents)
        ) :
            raise TypeError("selevents is not a set or sequence of integer event codes")
        #end if
        filters = self._event_filters
        add_conn_filter = len(filters) == 0
        pos = tuple \
          (
            i
            for i in range(len(filters))
            for elt in (filters[i],)
            if elt[:2] == (action, args)
          )
        if len(pos) != 0 :
            pos = pos[0]
            if (filters[pos][2] != None) != (selevents != None) :
                raise ValueError("incompatible change to wildcard selevents")
            #end if
            if selevents != None :
                filters[pos] = \
                    (
                        filters[pos][:2]
                    +
                        (filters[pos][2] | selevents,)
                    )
            #end if
        else :
            if selevents != None :
                selevents = set(selevents) # ensure it’s a unique copy
            #end if
            filters.append((action, args, selevents))
        #end if
        if add_conn_filter :
            self.conn.add_event_filter(self._conn_event_filter, (weak_ref(self),))
        #end if
    #end add_event_filter

    def remove_event_filter(self, action, args = (), selevents = None) :
        "removes the specified events from the event set for a previously-installed" \
        " event filter; if the resulting event set is empty, the filter is removed.\n" \
        "\n" \
        "If, say, the filter was installed with an event set of X.ALL_EVENTS," \
        " then events can be selectively removed from this set. But if the event" \
        " set was None, then the filter can only be removed in its entirety" \
        " by setting selevents to None."
        filters = self._event_filters
        pos = tuple \
          (
            i
            for i in range(len(filters))
            for elt in (filters[i],)
            if elt[:2] == (action, args)
          )
        if len(pos) != 0 :
            pos = pos[0]
            eventset = filters[pos][2]
            if isinstance(selevents, int) :
                selevents = {selevents}
            #end if
            if (eventset != None) != (selevents != None) :
                raise ValueError("incompatible change to wildcard selevents")
            #end if
            if selevents != None :
                eventset -= selevents
            #end if
            if eventset != None and len(eventset) != 0 :
                filters[pos] = filters[pos][:2] + (eventset,)
            else :
                filters[:] = filters[:pos] + filters[pos + 1:]
                if len(filters) == 0 :
                    self.conn.remove_event_filter \
                        (self._conn_event_filter, (weak_ref(self),), optional = True)
                #end if
            #end if
        #end if
    #end remove_event_filter

    @classmethod
    def create(celf, conn : Connection, depth : int, parent, bounds : Rect, border_width : int, window_class, visual, set_attrs) :
        if not isinstance(conn, Connection) :
            raise TypeError("conn must be a Connection")
        #end if
        return \
            celf \
              (
                conn,
                conn.create_window
                    (depth, parent, bounds, border_width, window_class, visual, set_attrs)
              )
    #end create

    @classmethod
    async def create_async(celf, conn : Connection, depth : int, parent, bounds : Rect, border_width : int, window_class, visual, set_attrs) :
        if not isinstance(conn, Connection) :
            raise TypeError("conn must be a Connection")
        #end if
        return \
            celf \
              (
                conn,
                await conn.create_window_async
                    (depth, parent, bounds, border_width, window_class, visual, set_attrs)
              )
    #end create_async

    def destroy(self) :
        res = self.conn.core.DestroyWindow(self.id)
        self.conn.request_check(res.sequence)
    #end destroy

    def destroy_async(self) :
        res = self.conn.core.DestroyWindow(self.id)
        return \
            self.conn.wait_for_reply(res)
    #end destroy_async

    def get_geometry(self) :
        return \
            self.conn.get_geometry(self.id)
    #end get_geometry

    async def get_geometry_async(self) :
        return \
            await self.conn.get_geometry_async(self.id)
    #end get_geometry_async

    def configure(self, config_attrs) :
        value_mask, value_list = WINCONFIG.pack_attributes(config_attrs)
        res = self.conn.conn.core.ConfigureWindow(self.id, value_mask, value_list)
        self.conn.conn.request_check(res.sequence)
    #end configure

    def set_shape_region(self, kind, offset : Vector, shape) :
        offset = Vector.from_tuple(offset)
        if not isinstance(shape, Region) :
            raise TypeError("shape must be a Region")
        #end if
        self.conn.init_ext(xfixes.key)
        self.conn.init_ext(xshape.key) # ?
        res = self.conn.conn(xfixes.key).SetWindowShapeRegion \
          (
            dest = self.id,
            dest_kind = kind,
            x_offset = offset.x,
            y_offset = offset.y,
            region = shape.id
          )
        self.conn.conn.request_check(res.sequence)
    #end set_shape_region

    def create_surface(self, screenindex : int, dimensions : Vector, use_xrender : bool) :
        "convenience routine which creates an XCBSurface for drawing" \
        " with Cairo into this window, with the option of using xrender."
        return \
            self.conn.create_surface(screenindex, self.id, dimensions, use_xrender)
    #end create_surface

    def create_pixmap(self, screenindex : int, depth : int, dimensions : Vector, use_xrender : bool) :
        "creates a Pixmap with the specified depth and root visual. Note that" \
        " Cairo only seems able to draw into pixmaps with a depth of 24, while" \
        " Cursor.create() wants pixmaps with a depth of 1. Alternatively, you can" \
        " use Cursor.create_from_rgb(), which will downconvert from depth 24 to" \
        " depth 1."
        pixmap_id, res = self.conn._create_pixmap(self.id, depth, dimensions)
        self.conn.conn.request_check(res.sequence)
        surface = self.conn.create_surface(screenindex, pixmap_id, dimensions, use_xrender)
        return \
            Pixmap(pixmap_id, surface, self.conn)
    #end create_pixmap

    async def create_pixmap_async(self, screenindex : int, depth : int, dimensions : Vector, use_xrender : bool) :
        # should I bother with async version, given no actual reply is returned from server?
        pixmap_id, res = self.conn._create_pixmap(self.id, depth, dimensions)
        await self.wait_for_reply(res)
        surface = self.conn.create_surface(screenindex, pixmap_id, dimensions, use_xrender)
        return \
            Pixmap(pixmap_id, surface, self.conn)
    #end create_pixmap

    def invalidate(self, area : Rect = None) :
        if area == None :
            area = Rect(0, 0, 0, 0) # does actual area matter?
        #end if
        res = self.conn.conn.core.SendEvent \
          (
            propagate = False,
            destination = self.id,
            event_mask = 0,
            event =
                xproto.ExposeEvent.synthetic
                  (
                    window = self.id,
                    x = area.left,
                    y = area.top,
                    width = area.width,
                    height = area.height,
                    count = 0
                  ).pack()
          )
        self.conn.conn.request_check(res.sequence)
        #self.conn.conn.flush() # could try if above gives trouble
    #end invalidate

    def clear_area(self, bounds : Rect, exposures : bool) :
        "does a ClearArea call on the specified area of the window."
        res = self.conn.ClearArea(exposures, bounds.x, bounds.y, bounds.width, bounds.height)
        self.conn.request_check(res.sequence)
    #end clear_area

    def copy_pix_area \
      (
        self,
        src : Pixmap,
        src_pos : Vector,
        dst_pos : Vector,
        dimensions : Vector
      ) :
        "does a CopyArea call from the specified part of the source" \
        " Pixmap to the specified position within the window."
        if not isinstance(src, Pixmap) :
            raise TypeError("src must be a Pixmap")
        #end if
        src_pos = Vector.from_tuple(src_pos)
        dst_pos = Vector.from_tuple(dst_pos)
        dimensions = Vector.from_tuple(dimensions)
        res = self.conn.CopyArea \
          (
            src_drawable = src.id,
            dst_drawable = self.id,
            gc = self.gcontext.id,
            src_x = src_pos.x,
            src_y = src_pos.y,
            dst_x = dst_pos.x,
            dst_y = dst_pos.y,
            width = dimensions.x,
            height = dimensions.y
          )
        self.conn.request_check(res.sequence)
    #end copy_pix_area

    def get_attributes(self) :
        res = self.conn.conn.core.GetWindowAttributes(self.id)
        return \
            res.reply()
    #end get_attributes

    def get_attributes_async(self) :
        res = self.conn.conn.core.GetWindowAttributes(self.id)
        self.conn.conn.flush()
        return \
            self.conn.wait_for_reply(res)
    #end get_attributes_async

    def set_attributes(self, attrs) :
        value_mask, value_list = WINATTR.pack_attributes(attrs)
        res = self.conn.conn.core.ChangeWindowAttributes \
          (
            window = self.id,
            value_mask = value_mask,
            value_list = value_list
          )
        self.conn.conn.request_check(res.sequence)
    #end set_attributes

    def set_name(self, name) :
        "sets the displayed window name."
        c_name = name.encode()
        res = self.conn.conn.core.ChangeProperty \
          (
            mode = xproto.PropMode.Replace,
            window = self.id,
            property = XA.WM_NAME,
            type = XA.STRING,
            format = 8,
            data_len = len(c_name),
            data = name
          )
        self.conn.conn.flush()
    #end set_name

    @staticmethod
    def _decode_property(propval, propformat, proptype) :
        if propval != None and (propformat != 8 or proptype != XA.STRING) :
            assert propformat % 8 == 0
            bytes_per_elt = propformat // 8
            assert len(propval) % bytes_per_elt == 0
            nr_elts = len(propval) // bytes_per_elt
            result = struct.unpack \
              (
                "=" + {1 : "B", 2 : "H", 4 : "L", 8 : "Q"}[bytes_per_elt] * nr_elts,
                propval
              )
        else :
            result = propval
        #end if
        return \
            result
    #end _decode_property

    def get_property(self, property, expect_type) :
        "retrieves the entire value of the specified window property," \
        " as a bytestring or tuple of elements."
        propval = b""
        propformat = proptype = None
        length = 16 # something convenient to begin with
        while True :
            res = self.conn.conn.core.GetProperty \
              (
                delete = False,
                window = self.id,
                property = property,
                type = expect_type,
                long_offset = len(propval),
                long_length = length
              )
            reply = res.reply()
            if reply.type == 0 :
                # nonexistent property
                assert propformat == None and proptype == None
                propval = None
                break
            #end if
            propformat = reply.format
            proptype = reply.type
            if reply.value_len == 0 :
                # wrong expected type
                propval = None
                break
            #end if
            propval += b"".join(reply.value)
            if reply.bytes_after == 0 :
                # got it all
                break
            # more to read
            length = reply.bytes_after
        #end while
        return \
            propformat, proptype, self._decode_property(propval, propformat, proptype)
    #end get_property

    async def get_property_async(self, property, expect_type) :
        "retrieves the entire value of the specified window property," \
        " as a bytestring or tuple of elements."
        propval = b""
        propformat = proptype = None
        length = 16 # something convenient to begin with
        while True :
            res = self.conn.conn.core.GetProperty \
              (
                delete = False,
                window = self.id,
                property = property,
                type = expect_type,
                long_offset = len(propval),
                long_length = length
              )
            self.conn.conn.flush()
            reply = await self.conn.wait_for_reply(res)
            if reply.type == 0 :
                # nonexistent property
                assert propformat == None and proptype == None
                propval = None
                break
            #end if
            propformat = reply.format
            proptype = reply.type
            if reply.value_len == 0 :
                # wrong expected type
                propval = None
                break
            #end if
            propval += b"".join(reply.value)
            if reply.bytes_after == 0 :
                # got it all
                break
            # more to read
            length = reply.bytes_after
        #end while
        return \
            propformat, proptype, self._decode_property(propval, propformat, proptype)
    #end get_property_async

    def set_property(self, propid, proptype, propformat, data) :
        "replaces the entire value of the specified window property."
        res = self.conn.conn.core.ChangeProperty \
          (
            mode = xproto.PropMode.Replace,
            window = self.id,
            property = propid,
            type = proptype,
            format = propformat,
            data_len = len(data),
            data = data
          )
        self.conn.conn.request_check(res.sequence)
    #end set_property

    def delete_property(self, propid) :
        res = self.conn.conn.core.DeleteProperty \
          (
            window = self.id,
            property = propid
          )
        self.conn.conn.request_check(res.sequence)
    #end delete_property

    def get_protocols(self, decode = True) :
        propformat, proptype, protocols = self.get_property \
          (
            property = self.conn.atom_cache.intern_atom("WM_PROTOCOLS"),
            expect_type = XA.ATOM
          )
        if protocols == None :
            protocols = []
        else :
            protocols = list \
              (
                self.conn.atom_cache.get_atom_name(p, decode)
                for p in protocols
              )
        #end if
        return \
            protocols
    #end get_protocols

    async def get_protocols_async(self, decode = True) :
        propformat, proptype, proplist = await self.get_property_async \
          (
            property = await self.conn.atom_cache.intern_atom_async("WM_PROTOCOLS"),
            expect_type = XA.ATOM
          )
        # for some reason attempt to construct result directly as a list comprehension
        # results in “TypeError: 'async_generator' object is not iterable”
        protocols = []
        if proplist != None :
            for p in proplist :
                protocols.append(await self.conn.atom_cache.get_atom_name_async(p, decode))
            #end for
        #end if
        return \
            protocols
    #end get_protocols_async

    def set_protocols(self, protocols) :
        proplist = list \
          (
            self.conn.atom_cache.intern_atom(name)
            for name in protocols
          )
        propid = self.conn.atom_cache.intern_atom("WM_PROTOCOLS")
        if len(proplist) != 0 :
            self.set_property(propid, XA.ATOM, 32, proplist)
        else :
            self.delete_property(propid)
        #end if
    #end set_protocols

    async def set_protocols_async(self, protocols) :
        # for some reason attempt to construct proplist directly as a list comprehension
        # results in “TypeError: 'async_generator' object is not iterable”
        proplist = []
        for name in protocols :
            proplist.append(await self.conn.atom_cache.intern_atom_async(name))
        #end for
        propid = await self.conn.atom_cache.intern_atom_async("WM_PROTOCOLS")
        # no set/delete_property_async -- should I bother?
        if len(proplist) != 0 :
            self.set_property(propid, XA.ATOM, 32, proplist)
        else :
            self.delete_property(propid)
        #end if
    #end set_protocols_async

#end Window

class GContext :
    "convenient wrapper object around an X11 graphics context.\n" \
    "\n" \
    "Note that only a subset of X11 drawing calls are supported;" \
    " the expectation is that the bulk of drawing will be done with" \
    " Cairo. So only the minimum of calls necessary to interface" \
    " Cairo-rendered graphics with the X server are implemented here."

    __slots__ = \
        (
            "__weakref__",
            "id",
            "conn",
            "user_data", # dict, initially empty, may be used by caller for any purpose
        ) # to forestall typos

    _instances = WeakValueDictionary()
    _ud_refs = WeakValueDictionary()

    def __new__(celf, conn, id) :
        self = celf._instances.get(id)
        if self == None :
            self = super().__new__(celf)
            self.conn = conn
            self.id = id
            user_data = celf._ud_refs.get(id)
            if user_data == None :
                user_data = qahirah.UserDataDict()
                celf._ud_refs[id] = user_data
            #end if
            self.user_data = user_data
            celf._instances[id] = self
        #end if
        return \
            self
    #end __new__

    @classmethod
    def create(celf, conn, drawable_id, set_attrs = None) :
        if set_attrs == None :
            set_attrs = ()
        #end if
        id = conn.conn.generate_id()
        value_mask, value_list = GCATTR.pack_attributes(set_attrs)
        res = conn.conn.core.CreateGC(id, drawable_id, value_mask, value_list)
        conn.conn.request_check(res.sequence)
        return \
            celf(conn, id)
    #end create

    def set_attributes(self, attrs) :
        value_mask, value_list = GCATTR.pack_attributes(attrs)
        res = self.conn.conn.core.ChangeGCAttributes \
          (
            gc = self.id,
            value_mask = value_mask,
            value_list = value_list
          )
        self.conn.conn.request_check(res.sequence)
    #end set_attributes

    def copy_from(self, other, attrs) :
        "copies attributes from another GContext selected by the specified" \
        " GCATTR values."
        if not isinstance(other, GContext) :
            raise TypeError("object to copy settings from must also be a GContext")
        #end if
        res = self.conn.conn.core.CopyGC \
          (
            src_gc = other.id,
            dst_gc = self.id,
            value_mask = GCATTR.make_mask(attrs)
          )
        self.conn.conn.request_check(res.sequence)
    #end copy_from

    def destroy(self) :
        if self.id != None :
            if self.conn != None :
                try :
                    res = self.conn.conn.core.FreeGC(self.id)
                except xcffib.ConnectionException :
                    pass
                else :
                    self.conn.conn.request_check(res.sequence)
                #end try
                self.conn = None
            #end if
            self.id = None
        #end if
    #end destroy

    def __del__(self) :
        self.destroy()
    #end __del__(self)

    def copy_area \
      (
        self,
        src_drawable : XID,
        dst_drawable : XID,
        src_pos : Vector,
        dst_pos : Vector,
        dimensions : Vector
      ) :
        "does a CopyArea call from the specified part of the source" \
        " drawable to the specified position within the destination drawable."
        src_pos = Vector.from_tuple(src_pos)
        dst_pos = Vector.from_tuple(dst_pos)
        dimensions = Vector.from_tuple(dimensions)
        res = self.conn.conn.core.CopyArea \
          (
            src_drawable = src_drawable,
            dst_drawable = dst_drawable,
            gc = self.id,
            src_x = src_pos.x,
            src_y = src_pos.y,
            dst_x = dst_pos.x,
            dst_y = dst_pos.y,
            width = dimensions.x,
            height = dimensions.y
          )
        self.conn.conn.request_check(res.sequence)
    #end copy_area

    def copy_plane \
      (
        self,
        src_drawable : XID,
        dst_drawable : XID,
        src_pos : Vector,
        dst_pos : Vector,
        dimensions : Vector,
        bit_plane : int
      ) :
        "does a CopyPlane call from the specified part and bit plane of the" \
        " source drawable to the specified position within the destination" \
        " drawable."
        src_pos = Vector.from_tuple(src_pos)
        dst_pos = Vector.from_tuple(dst_pos)
        dimensions = Vector.from_tuple(dimensions)
        res = self.conn.conn.core.CopyPlane \
          (
            src_drawable = src_drawable,
            dst_drawable = dst_drawable,
            gc = self.id,
            src_x = src_pos.x,
            src_y = src_pos.y,
            dst_x = dst_pos.x,
            dst_y = dst_pos.y,
            width = dimensions.x,
            height = dimensions.y,
            bit_plane = bit_plane
          )
        self.conn.conn.request_check(res.sequence)
    #end copy_plane

    def copy_to_1bit(self, src_drawable : XID, dst_drawable : XID, dimensions : Vector) :
        "assuming src_drawable is an RGB drawable, while dst_drawable is" \
        " 1 bit deep, copies a suitable bit plane of the former to the" \
        " latter to produce a bilevel image."
        self.copy_plane \
          (
            src_drawable = src_drawable,
            dst_drawable = dst_drawable,
            src_pos = (0, 0),
            dst_pos = (0, 0),
            dimensions = dimensions,
            bit_plane = 1 << 15
              # use top green bit, avoid bottom bits because of antialiasing
          )
    #end copy_to_1bit

#end GContext

class Region :

    __slots__ = \
        (
            "__weakref__",
            "conn",
            "id",
        ) # to forestall typos

    _instances = WeakValueDictionary()

    def __new__(celf, conn, id) :
        self = celf._instances.get(id)
        if self == None :
            self = super().__new__(celf)
            self.conn = conn
            self.id = id
            celf._instances[id] = self
        #end if
        return \
            self
    #end __new__

    @staticmethod
    def _rects_to_x11(rects) :
        if (
                not isinstance(rects, (tuple, list))
            or
                not all(isinstance(r, Rect) for r in rects)
        ) :
            raise TypeError("rects is not a sequence of qahirah.Rect")
        #end if
        result = []
        for r in rects :
            r.assert_isint()
            result.append \
              (
                xproto.RECTANGLE.synthetic(r.left, r.top, r.width, r.height)
              )
        #end for
        return \
            len(result), result
    #end _rects_to_x11

    @staticmethod
    def _rects_from_x11(rects) :
        return \
            list \
              (
                Rect(r.x, r.y, r.width, r.height)
                for r in rects
              )
    #end _rects_from_x11

    @classmethod
    def create(celf, conn : Connection, rects) :
        if not isinstance(conn, Connection) :
            raise TypeError("conn must be a Connection")
        #end if
        conn.init_ext(xfixes.key)
        nr_rects, rects = celf._rects_to_x11(rects)
        id = conn.conn.generate_id()
        res = conn.conn(xfixes.key).CreateRegion(id, nr_rects, rects)
        conn.conn.request_check(res.sequence)
        return \
            celf(conn, id)
    #end create

    @classmethod
    def create_from_bitmap(celf, conn : Connection, pix : Pixmap) :
        if not isinstance(conn, Connection) :
            raise TypeError("conn must be a Connection")
        #end if
        if not isinstance(pix, Pixmap) :
            raise TypeError("pix must be a Pixmap")
        #end if
        if pix.conn != conn :
            raise ValueError("pix was not created on this Connection")
        #end if
        conn.init_ext(xfixes.key)
        id = conn.conn.generate_id()
        res = conn.conn(xfixes.key).CreateRegionFromBitmap(id, pix.id)
        conn.conn.request_check(res.sequence)
        return \
            celf(conn, id)
    #end create_from_bitmap

    # TODO: create from window, create from GC,
    # SetRegion, CopyRegion, UnionRegion, IntersectRection, SubtractRegion,
    # InvertRegion, TranslateRegion, RegionExtents, ExpandRegion

    def fetch(self) :
        res = self.conn.conn(xfixes.key).FetchRegion(self.id)
        reply = res.reply()
        return \
          (
            Rect(reply.extents.x, reply.extents.y, reply.extents.width, reply.extents.height),
            self._rects_from_x11(reply.rectangles)
          )
    #end fetch

    async def fetch_async(self) :
        res = self.conn.conn(xfixes.key).FetchRegion(self.id)
        reply = await self.conn.wait_for_reply(res)
        return \
            self._rects_from_x11(reply.rectangles)
    #end fetch_async

    def destroy(self) :
        if self.conn != None :
            if self.id != None :
                res = self.conn.conn(xfixes.key).DestroyRegion(self.id)
                self.conn.conn.request_check(res.sequence)
                self.id = None
            #end if
            self.conn = None
        #end if
    #end destroy

    def __del__(self) :
        self.destroy()
    #end __del__

    # more TBD

#end Region

#+
# Convenience classes
#-

class BUTTON_STATE(enum.Enum) :
    "states in which to display a button."
    NORMAL = 0
    HIGHLIGHTED = 1
    DISABLED = 2
#end BUTTON_STATE

class ButtonHandler :
    "convenience class for implementing simple buttons that respond to clicks." \
    " You pass two callbacks: handle_draw, which actually renders the" \
    " button, and handle_click, which performs the button action.\n" \
    "\n" \
    "handle_draw is invoked as handle_draw(ctx, dimensions, state, *additional_args)" \
    " while handle_click is invoked as handle_click(*args)."

    def __init__ \
      (
        self,
        parent : Window,
        bounds : Rect,
        gravity : int,
        handle_draw, handle_draw_args,
        handle_click, handle_click_args,
        enabled : bool,
        use_xrender : bool
      ) :
        self.button = Window.create \
          (
            conn = parent.conn,
            depth = xcffib.XCB_COPY_FROM_PARENT,
            parent = parent,
            bounds = bounds,
            border_width = 0,
            window_class = xproto.WindowClass.InputOutput,
            visual = xcffib.XCB_COPY_FROM_PARENT,
            set_attrs =
                (
                    (WINATTR.EVENTMASK,
                            xproto.EventMask.Exposure
                        |
                            xproto.EventMask.ButtonPress
                        |
                            xproto.EventMask.ButtonRelease
                        |
                            xproto.EventMask.EnterWindow
                        |
                            xproto.EventMask.LeaveWindow,
                    ),
                    (WINATTR.WINGRAVITY, gravity),
                )
          )
        self.handle_draw = handle_draw
        self.handle_draw_args = handle_draw_args
        self.handle_click = handle_click
        self.handle_click_args = handle_click_args
        for evt, handler in \
            (
                (X.Expose, self.handle_expose),
                (X.ButtonPress, self.handle_press),
                (X.EnterNotify, self.handle_enter),
                (X.LeaveNotify, self.handle_leave),
                (X.ButtonRelease, self.handle_release),
            ) \
        :
            self.button.add_event_filter(handler, selevents = {evt})
        #end for
        self.dimensions = bounds.dimensions
        self.surface = self.button.create_surface(parent.conn.conn.pref_screen, bounds.dimensions, use_xrender)
        self.ctx = qahirah.Context.create(self.surface)
        self.button.set_mapped(True)
        self.enabled = enabled
        self.pressed = self.entered = False
    #end __init__

    def set_enabled(self, enabled : bool) :
        if enabled != self.enabled :
            self.enabled = enabled
            self.handle_expose(None, None)
        #end if
    #end set_enabled

    def handle_expose(self, button, evt) :
        if self.enabled :
            if self.pressed and self.entered :
                state = BUTTON_STATE.HIGHLIGHTED
            else :
                state = BUTTON_STATE.NORMAL
            #end if
        else :
            state = BUTTON_STATE.DISABLED
        #end if
        self.handle_draw(self.ctx, self.dimensions, state, *self.handle_draw_args)
        self.surface.flush()
    #end handle_expose

    def handle_press(self, button, evt) :
        if self.enabled :
            self.pressed = True
            self.handle_expose(button, evt)
        #end if
    #end handle_press

    def handle_enter(self, button, evt) :
        if self.enabled :
            self.entered = True
            if self.pressed :
                self.handle_expose(button, evt)
            #end if
        #end if
    #end handle_enter

    def handle_leave(self, button, evt) :
        self.entered = False
        if self.pressed :
            self.handle_expose(button, evt)
        #end if
    #end handle_leave

    def handle_release(self, button, evt) :
        if self.pressed and self.entered :
            self.handle_click(*self.handle_click_args)
        #end if
        self.pressed = False
        self.handle_expose(button, evt)
    #end handle_release

#end ButtonHandler

#+
# Cleanup
#-

def _atexit() :
    # disable all __del__ methods at process termination to avoid segfaults
    for cłass in (Window, Pixmap, Cursor, GContext, Region) :
        delattr(cłass, "__del__")
    #end for
#end _atexit
atexit.register(_atexit)
del _atexit
