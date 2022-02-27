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
    ref as weak_ref
import asyncio
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

#+
# Needed Cairo interface types
#-

def def_xcffib_subclass(base_class, xcffib_module, xcffib_name, substructs = None) :
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
    xcffib_module = xproto,
    xcffib_name = "VISUALTYPE"
  )
XCBRenderDirectFormat = def_xcffib_subclass \
  (
    base_class = qahirah.XCBRenderDirectFormat,
    xcffib_module = xproto,
    xcffib_name = "DIRECTFORMAT"
  )
XCBScreen = def_xcffib_subclass \
  (
    base_class = qahirah.XCBScreen,
    xcffib_module = xproto,
    xcffib_name = "SCREEN"
  )
XCBRenderPictFormInfo = def_xcffib_subclass \
  (
    base_class = qahirah.XCBRenderPictFormInfo,
    xcffib_module = xrender,
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
# Event loop
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

    __slots__ = ("__weakref__", "conn", "loop", "_conn_fd", "_event_filters", "_reply_queue", "last_sequence")
      # to forestall typos

    sequence_jump = 1 << 30
      # hopefully sequence numbers should never jump by this much at once

    def __init__(self, conn, loop = None) :
        _get_conn(conn) # just a sanity check
        if loop == None :
            loop = get_event_loop()
        #end if
        self.conn = conn
        self.loop = loop
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
            except xcffib.ConnectionException :
                event = None
            #end try
            had_event = event != None
            if had_event :
                event_filters = self._event_filters[:]
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
                action(conn_err, arg)
            #end for
        #end if
    #end _handle_conn_readable

    def add_event_filter(self, action, arg) :
        "installs a filter which gets to see all incoming events."
        if (
            any
              (
                elt["action"] == action and elt["arg"] == arg
                for i in range(len(self._event_filters))
                for elt in (self._event_filters[i],)
              )
        ) :
            raise KeyError("attempt to install duplicate action+arg")
        #end if
        newelt = (action, arg)
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
            if isinstance(event, xcffib.ConnectionException) :
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
    #end easy_create_window

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
        await self.await_reply(res)
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
            reply = res.reply()
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
