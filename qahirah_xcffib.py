"""Extension to Qahirah to adapt its generic XCB support to work specifically
with the xcffib binding.
"""
#+
# Copyright 2017, 2021 Lawrence D'Oliveiro <ldo@geek-central.gen.nz>.
# Licensed under the GNU Lesser General Public License v2.1 or later.
#-

from weakref import \
    ref as weak_ref
import asyncio
import qahirah
import cffi
import xcffib
from xcffib import \
    xproto, \
    render as xrender

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

class ConnWrapper :

    __slots__ = ("__weakref__", "conn", "loop") # to forestall typos

    def __init__(self, conn, loop = None) :
        _get_conn(conn) # just a sanity check
        if loop == None :
            loop = asyncio.get_event_loop()
        #end if
        self.conn = conn
        self.loop = loop
    #end __init__

    async def wait_for_event(self) :

        result = self.loop.create_future()
        w_self = weak_ref(self)

        def handle_conn_readable() :
            self = w_self()
            assert self != None, "parent ConnWrapper has gone away"
            event = self.conn.poll_for_event()
            if event != None :
                self.loop.remove_reader(self.conn.get_file_descriptor())
                result.set_result(event)
            elif conn.has_error() :
                raise RuntimeError("error on XCB connection")
            else :
                print("XCB conn readable but no event") # debug
            #end if
        #end handle_conn_readable

    #begin wait_for_event
        self.loop.add_reader(self.conn.get_file_descriptor(), handle_conn_readable)
        return await result
    #end wait_for_event

#end ConnWrapper
